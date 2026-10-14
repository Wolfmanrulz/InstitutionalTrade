import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime
import os
import warnings

warnings.filterwarnings('ignore')

DB_PATH = r"D:\Project\Institutional Stock Trend Scanner V3.0\ohlc_10yr.db"
OUTPUT_HTML = "Strategy_Trade_Report.html"
ATR_STOP_MULT = 1.5

# --- INSTITUTIONAL COLOR PALETTE ---
C_BG = '#0B1120'
C_PANEL = '#151E32'
C_HEADER = '#1A253A'
C_TEXT = '#E2E8F0'
C_TEXT_SEC = '#94A3B8'
C_GREEN = '#00E676'
C_RED = '#FF5252'
C_GOLD = '#FFD700'
C_BLUE = '#38BDF8'

def load_and_calculate():
    print("📊 Loading data and calculating signals...")
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM daily_indicators ORDER BY symbol, date", conn)
    conn.close()
    
    df['date'] = pd.to_datetime(df['date'], format='mixed')
    
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
    
    df['nifty_ok'] = np.where(df['symbol'] == '^NSEI', df['adj_close'] > df['ema200'], False)
    df['stock_above_200'] = np.where(df['symbol'] != '^NSEI', df['adj_close'] > df['ema200'], False)
    
    return df

def simulate_trades(df):
    print("⚙️ Simulating trades (1 Share per signal, Trailing ATR)...")
    dates = sorted(df['date'].unique())
    
    positions = {}
    trades = []
    
    def get_indicators(row):
        return {
            'ema20': row['ema20'], 'ema50': row['ema50'],
            'macd': row['macd'], 'macd_sig': row['macd_signal'],
            'rsi': row['rsi'], 'vwap': row['vwap'],
            'adx': row['adx'], 'vol_mult': row['volume'] / row['vol_sma'] if row['vol_sma'] > 0 else 0
        }

    for current_date in dates:
        day_df = df[df['date'] == current_date]
        day_data = {row['symbol']: row for _, row in day_df.iterrows()}
        
        # 1. Market Regime Check
        nifty_row = day_data.get('^NSEI')
        nifty_ok = bool(nifty_row['nifty_ok']) if nifty_row is not None and not pd.isna(nifty_row.get('ema200')) else False
        
        stocks = [row for sym, row in day_data.items() if sym != '^NSEI' and not pd.isna(row.get('ema200'))]
        breadth = (sum(1 for row in stocks if row['stock_above_200']) / len(stocks)) if stocks else 0
        allow_entries = nifty_ok and (breadth > 0.50)
        
        # 2. Process Exits (With Trailing ATR)
        for sym, pos in list(positions.items()):
            row = day_data.get(sym)
            if row is None: continue
            
            # --- TRAILING ATR LOGIC ---
            pos['highest_high'] = max(pos['highest_high'], float(row['high']))
            new_trailing_stop = pos['highest_high'] - (ATR_STOP_MULT * float(row['atr']))
            pos['stop_loss'] = max(pos['stop_loss'], new_trailing_stop)
            
            if float(row['low']) <= pos['stop_loss']:
                trades.append({
                    'Symbol': sym, 'Status': 'CLOSED', 'Entry Date': pos['entry_date'], 
                    'Entry Price': pos['entry_price'], 'Exit Date': current_date, 
                    'Exit Price': pos['stop_loss'], 'P&L': pos['stop_loss'] - pos['entry_price'],
                    'Reason': 'ATR Trailing Stop', 'Entry_Ind': pos['entry_ind']
                })
                del positions[sym]
            else:
                neg_count = sum([row['exit_cond_ema'], row['exit_cond_macd'], row['exit_cond_rsi'], 
                                 row['exit_cond_vwap'], row['exit_cond_adx']])
                if neg_count >= 4:
                    trades.append({
                        'Symbol': sym, 'Status': 'CLOSED', 'Entry Date': pos['entry_date'], 
                        'Entry Price': pos['entry_price'], 'Exit Date': current_date, 
                        'Exit Price': float(row['adj_close']), 'P&L': float(row['adj_close']) - pos['entry_price'],
                        'Reason': 'Threshold 4 Exit', 'Entry_Ind': pos['entry_ind']
                    })
                    del positions[sym]
                    
        # 3. Process Entries
        if allow_entries:
            for sym, row in day_data.items():
                if sym == '^NSEI' or sym in positions: continue
                if row['long_entry'] and row['adj_close'] > 0 and not pd.isna(row['atr']):
                    entry_price = float(row['adj_close'])
                    stop_loss = entry_price - (ATR_STOP_MULT * float(row['atr']))
                    positions[sym] = {
                        'entry_date': current_date, 'entry_price': entry_price,
                        'stop_loss': stop_loss, 'entry_ind': get_indicators(row),
                        'highest_high': float(row['high']) # Initialize for trailing
                    }
                    
    # 4. Process Open Trades
    latest_data = df.groupby('symbol').last().to_dict('index')
    
    for sym, pos in positions.items():
        latest = latest_data.get(sym, {})
        latest_price = latest.get('adj_close', pos['entry_price'])
        notional_pnl = latest_price - pos['entry_price']
        
        trades.append({
            'Symbol': sym, 'Status': 'OPEN', 'Entry Date': pos['entry_date'],
            'Entry Price': pos['entry_price'], 'Exit Date': 'OPEN',
            'Exit Price': latest_price, 'P&L': notional_pnl,
            'Reason': 'Active Position', 'Entry_Ind': pos['entry_ind'],
            'Current_Ind': get_indicators(pd.Series(latest)) if latest else pos['entry_ind']
        })
        
    return trades, df['date'].max()

def get_indicators_html(ind_dict, is_current=False):
    if not ind_dict: return "N/A"
    prefix = "Cur" if is_current else "Ent"
    return f"""
    <div style="font-size: 11px; line-height: 1.4;">
        <span style="color:{C_TEXT_SEC}">{prefix} EMA:</span> {ind_dict['ema20']:.1f}/{ind_dict['ema50']:.1f}<br>
        <span style="color:{C_TEXT_SEC}">{prefix} MACD:</span> {ind_dict['macd']:.2f}/{ind_dict['macd_sig']:.2f}<br>
        <span style="color:{C_TEXT_SEC}">{prefix} RSI:</span> {ind_dict['rsi']:.1f} | <span style="color:{C_TEXT_SEC}">ADX:</span> {ind_dict['adx']:.1f}<br>
        <span style="color:{C_TEXT_SEC}">{prefix} Vol:</span> {ind_dict['vol_mult']:.2f}x
    </div>
    """

def generate_html_report(all_trades, latest_date):
    print(" Generating HTML Report with Tabs...")
    
    df_trades = pd.DataFrame(all_trades)
    closed_trades = df_trades[df_trades['Status'] == 'CLOSED']
    open_trades = df_trades[df_trades['Status'] == 'OPEN']
    
    total_capital_invested = df_trades['Entry Price'].sum()
    realized_profit = closed_trades['P&L'].sum() if not closed_trades.empty else 0
    notional_profit = open_trades['P&L'].sum() if not open_trades.empty else 0
    total_net_profit = realized_profit + notional_profit
    win_rate = (len(closed_trades[closed_trades['P&L'] > 0]) / len(closed_trades) * 100) if not closed_trades.empty else 0

    df_trades['SortDate'] = pd.to_datetime(df_trades['Entry Date'])
    df_trades = df_trades.sort_values(by=['Status', 'SortDate'], ascending=[False, False]).drop(columns=['SortDate'])
    
    open_rows_list = []
    closed_rows_list = []
    
    for _, row in df_trades.iterrows():
        pnl_color = C_GREEN if row['P&L'] >= 0 else C_RED
        status_badge = f'<span style="background-color: {C_BLUE}; color: {C_BG}; padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 12px;">{row["Status"]}</span>'
        
        entry_ind_html = get_indicators_html(row.get('Entry_Ind'), False)
        current_ind_html = get_indicators_html(row.get('Current_Ind'), True) if row['Status'] == 'OPEN' else '<span style="color:#555">N/A (Closed)</span>'
        
        row_html = f"""
        <tr style="background-color: {C_PANEL if row['Status'] == 'OPEN' else 'transparent'}; border-left: 3px solid {C_BLUE if row['Status'] == 'OPEN' else 'transparent'};">
            <td>{status_badge}</td>
            <td>{row['Symbol']}</td>
            <td>{pd.to_datetime(row['Entry Date']).strftime('%Y-%m-%d')}</td>
            <td>₹{row['Entry Price']:.2f}</td>
            <td>{'' + f"{row['Exit Price']:.2f}" if row['Status'] == 'CLOSED' else f"{row['Exit Price']:.2f} <br><small style='color:{C_TEXT_SEC}'>(as of {latest_date.strftime('%Y-%m-%d')})</small>"}</td>
            <td style="color: {pnl_color}; font-weight: bold;">{'+' if row['P&L'] >= 0 else ''}₹{row['P&L']:.2f}</td>
            <td>{entry_ind_html}</td>
            <td>{current_ind_html}</td>
            <td style="color: {C_TEXT_SEC}; font-size: 13px;">{row['Reason']}</td>
        </tr>
        """
        if row['Status'] == 'OPEN':
            open_rows_list.append(row_html)
        else:
            closed_rows_list.append(row_html)
            
    open_rows = "".join(open_rows_list)
    closed_rows = "".join(closed_rows_list)

    html_template = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Institutional Strategy Trade Report</title>
    <style>
        :root {
            --bg-main: {C_BG}; --bg-panel: {C_PANEL}; --bg-header: {C_HEADER};
            --text-pri: {C_TEXT}; --text-sec: {C_TEXT_SEC};
            --green: {C_GREEN}; --red: {C_RED}; --gold: {C_GOLD}; --blue: {C_BLUE};
        }
        body { font-family: 'Segoe UI', Tahoma, sans-serif; background-color: var(--bg-main); color: var(--text-pri); margin: 0; padding: 40px; }
        .container { max-width: 1400px; margin: 0 auto; }
        header { text-align: center; margin-bottom: 40px; border-bottom: 2px solid var(--gold); padding-bottom: 20px; }
        header h1 { color: var(--gold); margin: 0; font-size: 2.2em; }
        header p { color: var(--text-sec); margin-top: 10px; }
        
        .summary-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 40px; }
        .card { background-color: var(--bg-panel); padding: 20px; border-radius: 8px; text-align: center; border: 1px solid #2A3B55; }
        .card h3 { margin: 0 0 10px 0; color: var(--text-sec); font-size: 14px; text-transform: uppercase; letter-spacing: 1px; }
        .card .value { font-size: 24px; font-weight: bold; color: var(--text-pri); }
        .card .value.green { color: var(--green); } .card .value.red { color: var(--red); } .card .value.gold { color: var(--gold); }
        
        .tab { overflow: hidden; border: 1px solid #2A3B55; background-color: var(--bg-header); border-radius: 8px 8px 0 0; display: flex; }
        .tab button { background-color: inherit; border: none; outline: none; cursor: pointer; padding: 14px 24px; transition: 0.3s; font-size: 16px; color: var(--text-sec); font-weight: bold; flex: 1; }
        .tab button:hover { background-color: #2A3B55; color: var(--text-pri); }
        .tab button.active { background-color: var(--bg-panel); color: var(--gold); border-bottom: 3px solid var(--gold); }
        .tabcontent { display: none; padding: 0; border: 1px solid #2A3B55; border-top: none; border-radius: 0 0 8px 8px; overflow: hidden; }
        
        table { width: 100%; border-collapse: collapse; background-color: var(--bg-panel); }
        th, td { padding: 12px 10px; text-align: left; border-bottom: 1px solid #2A3B55; vertical-align: top; }
        th { background-color: var(--bg-header); color: var(--gold); font-weight: 600; text-transform: uppercase; font-size: 12px; letter-spacing: 0.5px; position: sticky; top: 0; }
        tr:hover { background-color: #1E293B; }
        
        .footer { text-align: center; margin-top: 40px; color: var(--text-sec); font-size: 12px; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Institutional Strategy Trade Report (Trailing ATR)</h1>
            <p>Generated on {GEN_DATE} | Data up to {DATA_DATE} | Assumption: 1 Share per Signal</p>
        </header>

        <div class="summary-grid">
            <div class="card"><h3>Total Capital Invested</h3><div class="value gold">₹{TOTAL_CAPITAL}</div></div>
            <div class="card"><h3>Realized Profit (Closed)</h3><div class="value {REALIZED_CLASS}">{REALIZED_PROFIT}</div></div>
            <div class="card"><h3>Notional Profit (Open)</h3><div class="value {NOTIONAL_CLASS}">{NOTIONAL_PROFIT}</div></div>
            <div class="card"><h3>Total Net Profit</h3><div class="value {NET_CLASS}">{NET_PROFIT}</div></div>
            <div class="card"><h3>Win Rate (Closed)</h3><div class="value gold">{WIN_RATE}%</div></div>
            <div class="card"><h3>Open Positions</h3><div class="value" style="color: var(--blue);">{OPEN_COUNT}</div></div>
        </div>

        <div class="tab">
            <button class="tablinks" onclick="openTab(event, 'OpenPositions')" id="defaultOpen">🟢 Open Positions ({OPEN_COUNT})</button>
            <button class="tablinks" onclick="openTab(event, 'ClosedPositions')"> Closed Positions ({CLOSED_COUNT})</button>
        </div>

        <div id="OpenPositions" class="tabcontent">
            <table>
                <thead><tr><th>Status</th><th>Symbol</th><th>Entry Date</th><th>Entry Price</th><th>Latest Price</th><th>Notional P&L</th><th>Entry Signals</th><th>Current Signals</th><th>Reason</th></tr></thead>
                <tbody>{OPEN_ROWS}</tbody>
            </table>
        </div>

        <div id="ClosedPositions" class="tabcontent">
            <table>
                <thead><tr><th>Status</th><th>Symbol</th><th>Entry Date</th><th>Entry Price</th><th>Exit Price</th><th>Realized P&L</th><th>Entry Signals</th><th>Current Signals</th><th>Exit Reason</th></tr></thead>
                <tbody>{CLOSED_ROWS}</tbody>
            </table>
        </div>

        <div class="footer"><p>Institutional Stock Trend Scanner v8.0 | Hybrid DB Architecture</p></div>
    </div>

    <script>
        function openTab(evt, tabName) {
            var i, tabcontent, tablinks;
            tabcontent = document.getElementsByClassName("tabcontent");
            for (i = 0; i < tabcontent.length; i++) tabcontent[i].style.display = "none";
            tablinks = document.getElementsByClassName("tablinks");
            for (i = 0; i < tablinks.length; i++) tablinks[i].className = tablinks[i].className.replace(" active", "");
            document.getElementById(tabName).style.display = "block";
            evt.currentTarget.className += " active";
        }
        document.getElementById("defaultOpen").click();
    </script>
</body>
</html>
"""

    replacements = {
        "{C_BG}": C_BG, "{C_PANEL}": C_PANEL, "{C_HEADER}": C_HEADER,
        "{C_TEXT}": C_TEXT, "{C_TEXT_SEC}": C_TEXT_SEC,
        "{C_GREEN}": C_GREEN, "{C_RED}": C_RED, "{C_GOLD}": C_GOLD, "{C_BLUE}": C_BLUE,
        "{GEN_DATE}": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "{DATA_DATE}": latest_date.strftime('%Y-%m-%d'),
        "{TOTAL_CAPITAL}": f"{total_capital_invested:,.2f}",
        "{REALIZED_CLASS}": "green" if realized_profit >= 0 else "red",
        "{REALIZED_PROFIT}": f"{'+' if realized_profit >= 0 else ''}₹{realized_profit:,.2f}",
        "{NOTIONAL_CLASS}": "green" if notional_profit >= 0 else "red",
        "{NOTIONAL_PROFIT}": f"{'+' if notional_profit >= 0 else ''}₹{notional_profit:,.2f}",
        "{NET_CLASS}": "green" if total_net_profit >= 0 else "red",
        "{NET_PROFIT}": f"{'+' if total_net_profit >= 0 else ''}₹{total_net_profit:,.2f}",
        "{WIN_RATE}": f"{win_rate:.1f}",
        "{OPEN_COUNT}": str(len(open_trades)),
        "{CLOSED_COUNT}": str(len(closed_trades)),
        "{OPEN_ROWS}": open_rows,
        "{CLOSED_ROWS}": closed_rows
    }
    
    html_content = html_template
    for placeholder, value in replacements.items():
        html_content = html_content.replace(placeholder, str(value))

    with open(OUTPUT_HTML, 'w', encoding='utf-8') as f:
        f.write(html_content)
    print(f"✅ Report successfully generated: {os.path.abspath(OUTPUT_HTML)}")

if __name__ == "__main__":
    try:
        df = load_and_calculate()
        all_trades, latest_date = simulate_trades(df)
        generate_html_report(all_trades, latest_date)
    except Exception as e:
        print(f"❌ Critical Error: {e}")
        import traceback
        traceback.print_exc()