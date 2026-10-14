import sqlite3
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import timedelta
import warnings
import time

warnings.filterwarnings('ignore')

DB_PATH = r"D:\Project\Institutional Stock Trend Scanner V3.0\ohlc_10yr.db"
INITIAL_CAPITAL = 1_000_000.0
RISK_PCT = 0.010  # 1% risk per trade
ATR_STOP_MULT = 1.5

# --- INSTITUTIONAL CHART THEME ---
C_BG = '#0B1120'
C_PANEL = '#151E32'
C_TEXT = '#E2E8F0'
C_GREEN = '#00E676'
C_RED = '#FF5252'
C_GOLD = '#FFD700'
C_BLUE = '#38BDF8'

def parse_volume(x):
    if isinstance(x, (bytes, bytearray)): return int.from_bytes(x, byteorder='little')
    try: return int(float(x))
    except: return 0

def load_and_calculate_indicators():
    print("📊 Loading data from daily_indicators...")
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM daily_indicators ORDER BY symbol, date", conn)
    conn.close()
    
    df['date'] = pd.to_datetime(df['date'], format='mixed')
    
    # Compute Booleans on the fly (Hybrid Architecture)
    c = df['adj_close']
    df['minervini_v2'] = (
        (c > df['sma50']) & (c > df['sma150']) & (c > df['sma200']) &
        (df['sma50'] > df['sma150']) & (df['sma150'] > df['sma200']) &
        (df['sma200'] > df['sma200'].shift(21)) &
        (df['rs_6m'] > 0.30)
    )
    
    df['long_entry'] = (df['ema20'] > df['ema50']) & (df['macd'] > df['macd_signal']) & \
                       (df['rsi'] > 55) & (df['adj_close'] > df['vwap']) & \
                       (df['adx'] > 30) & (df['volume'] > (df['vol_sma'] * 1.5)) & \
                       (df['minervini_v2'])

    # Exit conditions
    df['exit_cond_ema'] = df['ema20'] < df['ema50']
    df['exit_cond_macd'] = df['macd'] < 0
    df['exit_cond_rsi'] = df['rsi'] < 50
    df['exit_cond_vwap'] = df['adj_close'] < (df['vwap'] - (df['atr'] * 0.2))
    df['exit_cond_adx'] = df['adx'] < 20
    
    # Market Regime fields
    df['nifty_ok'] = np.where(df['symbol'] == '^NSEI', df['adj_close'] > df['ema200'], False)
    df['stock_above_200'] = np.where(df['symbol'] != '^NSEI', df['adj_close'] > df['ema200'], False)
    
    print(f"✅ Loaded {len(df):,} rows across {df['symbol'].nunique()} symbols.")
    return df

def simulate_window(df_window):
    """Runs the portfolio simulation on a specific 3-year data slice with Trailing ATR."""
    daily_data = {}
    for date, group in df_window.groupby('date'):
        daily_data[date] = {row['symbol']: row for _, row in group.iterrows()}
        
    dates = sorted(daily_data.keys())
    if not dates: return None

    capital = INITIAL_CAPITAL
    positions = {}
    trades = []
    peak_equity = INITIAL_CAPITAL
    max_drawdown = 0.0

    for current_date in dates:
        day = daily_data[current_date]
        
        # 1. Market Regime
        nifty_row = day.get('^NSEI')
        nifty_ok = bool(nifty_row['nifty_ok']) if nifty_row is not None and not pd.isna(nifty_row.get('ema200')) else False
        
        stocks = [row for sym, row in day.items() if sym != '^NSEI' and not pd.isna(row.get('ema200'))]
        if stocks:
            above_200 = sum(1 for row in stocks if row['stock_above_200'])
            breadth = above_200 / len(stocks)
        else:
            breadth = 0
            
        allow_entries = nifty_ok and (breadth > 0.50)

        # 2. Mark-to-Market & Drawdown
        current_equity = capital + sum(pos['shares'] * day[sym]['adj_close'] for sym, pos in positions.items() if sym in day)
        if current_equity > peak_equity: peak_equity = current_equity
        dd = (peak_equity - current_equity) / peak_equity if peak_equity > 0 else 0
        if dd > max_drawdown: max_drawdown = dd

        # 3. Exits (With Trailing ATR Update)
        exits = []
        for sym, pos in list(positions.items()):
            if sym not in day: continue
            row = day[sym]
            
            # --- TRAILING ATR LOGIC ---
            pos['highest_high'] = max(pos['highest_high'], float(row['high']))
            new_trailing_stop = pos['highest_high'] - (ATR_STOP_MULT * float(row['atr']))
            pos['stop_loss'] = max(pos['stop_loss'], new_trailing_stop) # Ratchet up only
            
            if float(row['low']) <= pos['stop_loss']:
                exits.append((sym, pos['stop_loss'], "ATR Trailing Stop"))
            else:
                neg_count = sum([row['exit_cond_ema'], row['exit_cond_macd'], row['exit_cond_rsi'], row['exit_cond_vwap'], row['exit_cond_adx']])
                if neg_count >= 4:
                    exits.append((sym, float(row['adj_close']), "Threshold 4"))
                    
        for sym, price, reason in exits:
            pos = positions.pop(sym)
            pnl = (price - pos['entry']) * pos['shares']
            capital += pos['shares'] * price
            trades.append({'pnl': pnl, 'return': (price/pos['entry'])-1})

        # 4. Entries
        if allow_entries:
            current_equity = capital + sum(pos['shares'] * day[sym]['adj_close'] for sym, pos in positions.items() if sym in day)
            for sym, row in day.items():
                if sym == '^NSEI' or sym in positions: continue
                if row['long_entry'] and row['adj_close'] > 0 and not pd.isna(row['atr']):
                    entry = float(row['adj_close'])
                    initial_stop = entry - (ATR_STOP_MULT * float(row['atr']))
                    risk_per_share = entry - initial_stop
                    
                    if risk_per_share > 0:
                        risk_amt = current_equity * RISK_PCT
                        shares = int(risk_amt / risk_per_share)
                        if shares > 0 and (shares * entry) <= capital:
                            capital -= shares * entry
                            positions[sym] = {
                                'shares': shares, 
                                'entry': entry, 
                                'stop_loss': initial_stop,
                                'highest_high': float(row['high']) # Initialize for trailing
                            }

    # End-of-Period Liquidation
    if dates and positions:
        final_date = dates[-1]
        final_day = daily_data[final_date]
        for sym, pos in list(positions.items()):
            row = final_day.get(sym)
            if row is not None and not pd.isna(row.get('adj_close')):
                exit_price = float(row['adj_close'])
            else:
                exit_price = pos['entry']
            pnl = (exit_price - pos['entry']) * pos['shares']
            capital += pos['shares'] * exit_price
            trades.append({'pnl': pnl, 'return': (exit_price/pos['entry'])-1})

    # Calculate Metrics
    if not trades:
        return {'return': 0, 'win_rate': 0, 'profit_factor': 0, 'max_dd': max_drawdown*100, 'trades': 0}
        
    pnls = [t['pnl'] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    
    return {
        'return': ((capital - INITIAL_CAPITAL) / INITIAL_CAPITAL) * 100,
        'win_rate': (len(wins) / len(trades)) * 100 if trades else 0,
        'profit_factor': (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else np.inf,
        'max_dd': max_drawdown * 100,
        'trades': len(trades)
    }

def run_walk_forward(df):
    print("\n🔄 Starting 3-Year Rolling Walk-Forward Analysis (Trailing ATR)...")
    all_dates = sorted(df['date'].unique())
    
    window_days = 756 
    step_days = 252 
    
    results = []
    total_windows = (len(all_dates) - window_days) // step_days
    
    start_time = time.time()
    
    for i in range(0, total_windows + 1):
        start_idx = i * step_days
        end_idx = start_idx + window_days
        
        if end_idx > len(all_dates): break
        
        start_date = all_dates[start_idx]
        end_date = all_dates[end_idx - 1]
        
        df_window = df[(df['date'] >= start_date) & (df['date'] <= end_date)]
        
        metrics = simulate_window(df_window)
        if metrics:
            metrics['start'] = start_date
            metrics['end'] = end_date
            results.append(metrics)
            
        if i % 2 == 0 or i == total_windows:
            elapsed = time.time() - start_time
            print(f"  Processed Window {i+1}/{total_windows+1} ({start_date.date()} to {end_date.date()})...")

    print(f"✅ Walk-Forward complete in {time.time() - start_time:.1f}s.")
    return pd.DataFrame(results)

def plot_results(results_df):
    plt.style.use('dark_background')
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.patch.set_facecolor(C_BG)
    
    for ax in axes.flatten():
        ax.set_facecolor(C_PANEL)
        ax.tick_params(colors=C_TEXT)
        ax.spines['bottom'].set_color(C_PANEL)
        ax.spines['left'].set_color(C_PANEL)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.grid(True, color='#1E293B', linestyle='--', linewidth=0.5)

    axes[0,0].bar(results_df['start'].dt.date, results_df['return'], color=[C_GREEN if r >= 0 else C_RED for r in results_df['return']], alpha=0.8)
    axes[0,0].axhline(y=0, color=C_TEXT, linestyle='-', linewidth=0.5)
    axes[0,0].set_title('Total Return (%) per 3-Year Window (Trailing ATR)', color=C_GOLD, fontweight='bold')
    axes[0,0].set_ylabel('Return %', color=C_TEXT)
    axes[0,0].tick_params(axis='x', rotation=45)

    axes[0,1].bar(results_df['start'].dt.date, results_df['win_rate'], color=C_BLUE, alpha=0.8)
    axes[0,1].axhline(y=52.69, color=C_GOLD, linestyle='--', label='Historical Avg (52.69%)')
    axes[0,1].set_title('Win Rate (%) per 3-Year Window', color=C_GOLD, fontweight='bold')
    axes[0,1].set_ylabel('Win Rate %', color=C_TEXT)
    axes[0,1].legend(facecolor=C_PANEL, labelcolor=C_TEXT)
    axes[0,1].tick_params(axis='x', rotation=45)

    axes[1,0].bar(results_df['start'].dt.date, results_df['profit_factor'], color=C_GOLD, alpha=0.8)
    axes[1,0].axhline(y=1.90, color=C_GREEN, linestyle='--', label='Historical Avg (1.90)')
    axes[1,0].set_title('Profit Factor per 3-Year Window', color=C_GOLD, fontweight='bold')
    axes[1,0].set_ylabel('Profit Factor', color=C_TEXT)
    axes[1,0].legend(facecolor=C_PANEL, labelcolor=C_TEXT)
    axes[1,0].tick_params(axis='x', rotation=45)

    axes[1,1].bar(results_df['start'].dt.date, results_df['max_dd'], color=C_RED, alpha=0.8)
    axes[1,1].set_title('Max Drawdown (%) per 3-Year Window', color=C_GOLD, fontweight='bold')
    axes[1,1].set_ylabel('Max DD %', color=C_TEXT)
    axes[1,1].tick_params(axis='x', rotation=45)

    plt.tight_layout()
    plt.show()

if __name__ == "__main__":
    try:
        df = load_and_calculate_indicators()
        results = run_walk_forward(df)
        
        print("\n" + "="*85)
        print("WALK-FORWARD SUMMARY (3-Year Rolling Windows) - TRAILING ATR")
        print("="*85)
        print(results[['start', 'end', 'return', 'win_rate', 'profit_factor', 'max_dd', 'trades']].to_string(index=False))
        print("="*85)
        print(f"\nAverage Return: {results['return'].mean():.2f}%")
        print(f"Average Win Rate: {results['win_rate'].mean():.2f}%")
        print(f"Average Profit Factor: {results['profit_factor'].mean():.2f}")
        print(f"Average Max DD: {results['max_dd'].mean():.2f}%")
        
        print("\n Generating Institutional Charts...")
        plot_results(results)
        
    except Exception as e:
        print(f"❌ Critical Error: {e}")
        import traceback
        traceback.print_exc()