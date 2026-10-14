import sqlite3
import pandas as pd
import numpy as np
from collections import defaultdict
import warnings
import time

warnings.filterwarnings('ignore')

DB_PATH = r"D:\Project\Institutional Stock Trend Scanner V3.0\ohlc_10yr.db"
INITIAL_CAPITAL = 1_000_000.0
RISK_PCT = 0.010  # 1% risk per trade
ATR_MULT = 1.5

def load_and_prepare_data():
    print("📊 Loading pre-calculated indicators...")
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM daily_indicators ORDER BY symbol, date", conn)
    conn.close()
    
    df['date'] = pd.to_datetime(df['date'], format='mixed')
    
    # Compute Booleans on the fly
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

    df['exit_cond_ema'] = df['ema20'] < df['ema50']
    df['exit_cond_macd'] = df['macd'] < 0
    df['exit_cond_rsi'] = df['rsi'] < 50
    df['exit_cond_vwap'] = df['adj_close'] < (df['vwap'] - (df['atr'] * 0.2))
    df['exit_cond_adx'] = df['adx'] < 20
    
    # Market Regime fields
    df['nifty_ok'] = np.where(df['symbol'] == '^NSEI', df['adj_close'] > df['ema200'], False)
    df['stock_above_200'] = np.where(df['symbol'] != '^NSEI', df['adj_close'] > df['ema200'], False)
    
    print(f"✅ Loaded {len(df):,} rows. Preparing daily snapshots...")
    return df

def run_simulation(df, use_trailing_atr=False):
    strategy_name = "TRAILING ATR" if use_trailing_atr else "STATIC ATR (Baseline)"
    print(f"🔄 Running {strategy_name} simulation...")
    
    daily_data = defaultdict(dict)
    for row in df.itertuples(index=False):
        daily_data[row.date][row.symbol] = row
        
    dates = sorted(daily_data.keys())
    
    capital = INITIAL_CAPITAL
    positions = {}
    trades = []
    peak_equity = INITIAL_CAPITAL
    max_drawdown = 0.0
    
    for current_date in dates:
        day = daily_data[current_date]
        
        # 1. Market Regime Check
        nifty_row = day.get('^NSEI')
        nifty_ok = bool(nifty_row.nifty_ok) if nifty_row is not None and not pd.isna(getattr(nifty_row, 'ema200', np.nan)) else False
        
        stocks = [row for sym, row in day.items() if sym != '^NSEI' and not pd.isna(getattr(row, 'ema200', np.nan))]
        breadth = (sum(1 for row in stocks if row.stock_above_200) / len(stocks)) if stocks else 0
        allow_entries = nifty_ok and (breadth > 0.50)
        
        # 2. Mark-to-Market & Drawdown
        current_equity = capital + sum(pos['shares'] * day[sym].adj_close for sym, pos in positions.items() if sym in day)
        if current_equity > peak_equity: peak_equity = current_equity
        dd = (peak_equity - current_equity) / peak_equity if peak_equity > 0 else 0
        if dd > max_drawdown: max_drawdown = dd
        
        # 3. Exits
        exits = []
        for sym, pos in list(positions.items()):
            row = day.get(sym)
            if row is None: continue
            
            # Update Trailing Stop if applicable
            if use_trailing_atr:
                pos['highest_high'] = max(pos['highest_high'], float(row.high))
                new_trailing_stop = pos['highest_high'] - (ATR_MULT * float(row.atr))
                pos['stop_loss'] = max(pos['stop_loss'], new_trailing_stop)
            
            # Check ATR Stop
            if float(row.low) <= pos['stop_loss']:
                exits.append((sym, pos['stop_loss'], "ATR Stop"))
            else:
                # Check Threshold 4
                neg_count = sum([row.exit_cond_ema, row.exit_cond_macd, row.exit_cond_rsi, 
                                 row.exit_cond_vwap, row.exit_cond_adx])
                if neg_count >= 4:
                    exits.append((sym, float(row.adj_close), f"Threshold 4 ({neg_count})"))
                    
        for sym, exit_price, reason in exits:
            pos = positions.pop(sym)
            pnl = (exit_price - pos['entry']) * pos['shares']
            capital += pos['shares'] * exit_price
            trades.append({'pnl': pnl, 'return': (exit_price/pos['entry'])-1})
            
        # 4. Entries
        if allow_entries:
            current_equity = capital + sum(pos['shares'] * day[sym].adj_close for sym, pos in positions.items() if sym in day)
            for sym, row in day.items():
                if sym == '^NSEI' or sym in positions: continue
                if row.long_entry and row.adj_close > 0 and not pd.isna(row.atr):
                    entry = float(row.adj_close)
                    initial_stop = entry - (ATR_MULT * float(row.atr))
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
                                'highest_high': float(row.high) # For trailing
                            }
                            
    # End-of-period liquidation
    if dates and positions:
        final_day = daily_data[dates[-1]]
        for sym, pos in list(positions.items()):
            row = final_day.get(sym)
            if row is not None and not pd.isna(getattr(row, 'adj_close', np.nan)):
                exit_price = float(row.adj_close)
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
        'Strategy': strategy_name,
        'Total Return %': ((capital - INITIAL_CAPITAL) / INITIAL_CAPITAL) * 100,
        'Max Drawdown %': max_drawdown * 100,
        'Win Rate %': (len(wins) / len(trades)) * 100,
        'Profit Factor': (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else np.inf,
        'Total Trades': len(trades)
    }

if __name__ == "__main__":
    try:
        start_time = time.time()
        df = load_and_prepare_data()
        
        # Run Baseline (Static ATR)
        res_static = run_simulation(df, use_trailing_atr=False)
        
        # Run New Strategy (Trailing ATR)
        res_trailing = run_simulation(df, use_trailing_atr=True)
        
        print("\n" + "="*85)
        print("BACKTEST COMPARISON: STATIC ATR vs. TRAILING ATR")
        print("="*85)
        
        results_df = pd.DataFrame([res_static, res_trailing])
        results_df = results_df.set_index('Strategy')
        
        # Format for clean printing
        pd.set_option('display.float_format', lambda x: '%.2f' % x)
        print(results_df.to_string())
        print("="*85)
        print(f"⏱️ Total Execution Time: {time.time() - start_time:.1f} seconds")
        
    except Exception as e:
        print(f"❌ Critical Error: {e}")
        import traceback
        traceback.print_exc()