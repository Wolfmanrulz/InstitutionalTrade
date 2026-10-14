import tkinter as tk
from tkinter import ttk
import sqlite3
import pandas as pd
import numpy as np
import yfinance as yf
import threading
from datetime import datetime
import warnings
import logging

logging.getLogger('yfinance').setLevel(logging.CRITICAL)
warnings.filterwarnings('ignore')

from stock_chart_viewer_v3 import StockChartViewer
#included trailing ATR stop loss

DB_PATH = r"D:\Project\Institutional Stock Trend Scanner V3.0\ohlc_10yr.db"

# --- INSTITUTIONAL COLOR PALETTE ---
C_BG_MAIN = '#0B1120'      # Deep Navy
C_BG_PANEL = '#151E32'     # Slate Navy
C_BG_HEADER = '#1A253A'    # Header Blue
C_BG_HOVER = '#2A3B55'     # Selection Blue
C_BORDER = '#2A3B55'       # Subtle Border
C_TEXT_PRI = '#E2E8F0'     # Crisp White
C_TEXT_SEC = '#94A3B8'     # Muted Gray
C_GREEN = '#00E676'        # Terminal Green
C_RED = '#FF5252'          # Terminal Red
C_GOLD = '#FFD700'         # Institutional Gold

class StockScannerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Institutional Trend Scanner v8.0")
        self.root.geometry("1300x850")
        self.root.minsize(1100, 700)
        self.root.configure(bg=C_BG_MAIN)
        self.apply_institutional_theme()
        
        self.full_df = None
        self.focus_data = []
        self.universe_data = []
        
        self.build_ui()
        self.log("Initializing system... Checking data & Market Regime...")
        
        self.update_thread = threading.Thread(target=self.run_startup_update, daemon=True)
        self.update_thread.start()

    def apply_institutional_theme(self):
        style = ttk.Style()
        style.theme_use('clam')
        
        style.configure('.', background=C_BG_MAIN, foreground=C_TEXT_PRI, fieldbackground=C_BG_PANEL)
        style.configure('TFrame', background=C_BG_MAIN)
        style.configure('TLabel', background=C_BG_MAIN, foreground=C_TEXT_PRI, font=('Segoe UI', 10))
        
        style.configure('TButton', background=C_BG_HEADER, foreground=C_TEXT_PRI, borderwidth=1, focusthickness=3, font=('Segoe UI', 10, 'bold'))
        style.map('TButton', background=[('active', C_BG_HOVER)])
        
        style.configure('Treeview', background=C_BG_PANEL, foreground=C_TEXT_PRI, fieldbackground=C_BG_PANEL, rowheight=28, borderwidth=0, font=('Segoe UI', 10))
        style.configure('Treeview.Heading', background=C_BG_HEADER, foreground=C_TEXT_SEC, font=('Segoe UI', 10, 'bold'), borderwidth=1)
        style.map('Treeview', background=[('selected', C_BG_HOVER)])

    def build_ui(self):
        top_frame = ttk.Frame(self.root, padding=15)
        top_frame.pack(fill=tk.X)
        
        self.regime_banner = tk.Label(top_frame, text="⏳ CALCULATING MARKET REGIME...", 
                                      font=('Segoe UI', 12, 'bold'), fg=C_TEXT_PRI, bg=C_BG_HEADER, 
                                      pady=12, justify=tk.LEFT, anchor='w', padx=20)
        self.regime_banner.pack(fill=tk.X)

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=15, pady=10)
        self.notebook.configure(style='TNotebook')
        
        self.focus_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.focus_frame, text="  🎯 FOCUS LIST (BUY SIGNALS)  ")
        self.focus_search = ttk.Entry(self.focus_frame, font=('Segoe UI', 10))
        self.focus_search.pack(fill=tk.X, padx=15, pady=15)
        self.focus_search.bind("<KeyRelease>", lambda e: self.update_trees())
        
        self.focus_tree = self.create_sortable_treeview(self.focus_frame, ('Symbol', 'Date', 'Close', 'ADX', 'RSI', 'Vol Mult'))
        self.focus_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=15, pady=10)
        focus_scroll = ttk.Scrollbar(self.focus_frame, orient=tk.VERTICAL, command=self.focus_tree.yview)
        self.focus_tree.configure(yscroll=focus_scroll.set)
        focus_scroll.pack(side=tk.RIGHT, fill=tk.Y, pady=10)

        self.universe_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.universe_frame, text="  🌐 UNIVERSE WATCHLIST  ")
        self.uni_search = ttk.Entry(self.universe_frame, font=('Segoe UI', 10))
        self.uni_search.pack(fill=tk.X, padx=15, pady=15)
        self.uni_search.bind("<KeyRelease>", lambda e: self.update_trees())
        
        self.universe_tree = self.create_sortable_treeview(self.universe_frame, ('Symbol', 'Date', 'Close', 'Trend', 'ADX', 'RSI'))
        self.universe_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=15, pady=10)
        uni_scroll = ttk.Scrollbar(self.universe_frame, orient=tk.VERTICAL, command=self.universe_tree.yview)
        self.universe_tree.configure(yscroll=uni_scroll.set)
        uni_scroll.pack(side=tk.RIGHT, fill=tk.Y, pady=10)

        log_frame = ttk.Frame(self.root, padding=15)
        log_frame.pack(fill=tk.X)
        self.log_text = tk.Text(log_frame, height=4, font=('Consolas', 9), state=tk.DISABLED, 
                                bg='#050810', fg=C_GREEN, bd=1, relief=tk.FLAT, insertbackground=C_GREEN)
        self.log_text.pack(fill=tk.X)

    def create_sortable_treeview(self, parent, columns):
        tree = ttk.Treeview(parent, columns=columns, show='headings')
        for col in columns:
            tree.heading(col, text=col, command=lambda _col=col: self.sort_column(tree, _col, False))
            tree.column(col, width=120, anchor=tk.CENTER)
        tree.column('Symbol', width=150)
        tree.bind("<Double-1>", lambda e: self.on_stock_click(e, tree))
        return tree

    def sort_column(self, tree, col, reverse):
        l = [(tree.set(k, col), k) for k in tree.get_children('')]
        try: l = [(float(x[0]), x[1]) for x in l]
        except ValueError: pass
        l.sort(reverse=reverse)
        for index, (val, k) in enumerate(l): tree.move(k, '', index)
        tree.heading(col, command=lambda: self.sort_column(tree, col, not reverse))

    def log(self, msg):
        def _log():
            self.log_text.config(state=tk.NORMAL)
            self.log_text.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
            self.log_text.see(tk.END)
            self.log_text.config(state=tk.DISABLED)
        self.root.after(0, _log)

    def run_startup_update(self):
        try:
            self.update_database()
            self.calculate_and_display_signals()
        except Exception as e:
            self.log(f"❌ Critical Error: {e}")

    def update_database(self):
        self.log("Checking for new market data...")
        try:
            conn = sqlite3.connect(DB_PATH)
            max_date_df = pd.read_sql_query("SELECT MAX(date) as max_date FROM daily_indicators", conn)
            max_date_str = max_date_df['max_date'].iloc[0]
            
            if not max_date_str or pd.isna(max_date_str):
                self.log("❌ daily_indicators table is empty. Run populate_indicators_db.py.")
                conn.close()
                return

            max_date = pd.to_datetime(max_date_str)
            today = pd.to_datetime(datetime.now().date())
            
            if max_date.date() >= today.date():
                self.log("✅ Database is up to date.")
                conn.close()
                return
                
            start_date = (max_date + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
            end_date = (today + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
            symbols_df = pd.read_sql_query("SELECT DISTINCT symbol FROM daily_indicators", conn)
            symbols = symbols_df['symbol'].tolist()
            conn.close()
            
            self.log(f"Downloading & calculating indicators from {start_date}...")
            new_data = []
            for i in range(0, len(symbols), 50):
                batch = symbols[i:i+50]
                try:
                    df_batch = yf.download(batch, start=start_date, end=end_date, auto_adjust=True, progress=False)
                    if df_batch.empty: continue
                    if isinstance(df_batch.columns, pd.MultiIndex):
                        for sym in batch:
                            if sym in df_batch.columns.get_level_values(1):
                                sym_df = df_batch.xs(sym, axis=1, level=1).copy()
                                sym_df['symbol'] = sym
                                sym_df = sym_df.reset_index().rename(columns={'Date': 'date'})
                                sym_df['open'], sym_df['high'], sym_df['low'], sym_df['close'] = sym_df['Open'], sym_df['High'], sym_df['Low'], sym_df['Close']
                                adj_col = 'Adj Close' if 'Adj Close' in sym_df.columns else 'Close'
                                sym_df['adj_close'], sym_df['volume'] = sym_df[adj_col], sym_df['Volume']
                                new_data.append(sym_df[['symbol', 'date', 'open', 'high', 'low', 'close', 'adj_close', 'volume']])
                except: pass
            
            if new_data:
                final_df = pd.concat(new_data, ignore_index=True)
                final_df['date'] = final_df['date'].dt.strftime('%Y-%m-%d')
                conn = sqlite3.connect(DB_PATH)
                final_df.to_sql('daily_ohlc', conn, if_exists='append', index=False)
                
                affected_symbols = final_df['symbol'].unique().tolist()
                placeholders = ','.join(['?'] * len(affected_symbols))
                existing = pd.read_sql_query(f"SELECT symbol, date, open, high, low, close, adj_close, volume FROM daily_ohlc WHERE symbol IN ({placeholders}) ORDER BY symbol, date", conn, params=affected_symbols)
                conn.close()
                
                for col in ['open', 'high', 'low', 'close', 'adj_close']: existing[col] = pd.to_numeric(existing[col], errors='coerce')
                existing['date'] = pd.to_datetime(existing['date'], format='mixed')
                
                ind_results = []
                for symbol, group in existing.groupby('symbol'):
                    group = group.sort_values('date').reset_index(drop=True)
                    c, h, l, v = group['adj_close'], group['high'], group['low'], group['volume']
                    group['ema20'] = c.ewm(span=20, adjust=False).mean()
                    group['ema50'] = c.ewm(span=50, adjust=False).mean()
                    group['ema200'] = c.ewm(span=200, adjust=False).mean()
                    ema12 = c.ewm(span=12, adjust=False).mean()
                    ema26 = c.ewm(span=26, adjust=False).mean()
                    group['macd'] = ema12 - ema26
                    group['macd_signal'] = group['macd'].ewm(span=9, adjust=False).mean()
                    delta = c.diff()
                    gain = delta.where(delta > 0, 0.0)
                    loss = -delta.where(delta < 0, 0.0)
                    avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
                    avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()
                    group['rsi'] = 100 - (100 / (1 + (avg_gain / avg_loss)))
                    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
                    group['atr'] = tr.ewm(alpha=1/14, adjust=False).mean()
                    up_mov, down_mov = h.diff(), -l.diff()
                    plus_dm = np.where((up_mov > down_mov) & (up_mov > 0), up_mov, 0.0)
                    minus_dm = np.where((down_mov > up_mov) & (down_mov > 0), down_mov, 0.0)
                    smooth_tr = tr.ewm(alpha=1/14, adjust=False).mean()
                    smooth_plus = pd.Series(plus_dm, index=group.index).ewm(alpha=1/14, adjust=False).mean()
                    smooth_minus = pd.Series(minus_dm, index=group.index).ewm(alpha=1/14, adjust=False).mean()
                    plus_di = 100 * smooth_plus / smooth_tr
                    minus_di = 100 * smooth_minus / smooth_tr
                    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
                    group['adx'] = dx.ewm(alpha=1/14, adjust=False).mean()
                    group['vol_sma'] = v.rolling(20).mean()
                    group['vwap'] = (c * v).rolling(20).sum() / v.rolling(20).sum()
                    group['sma50'] = c.rolling(50).mean()
                    group['sma150'] = c.rolling(150).mean()
                    group['sma200'] = c.rolling(200).mean()
                    group['rs_6m'] = c.pct_change(126)
                    ind_results.append(group)
                    
                ind_df = pd.concat(ind_results, ignore_index=True)
                ind_df['date'] = ind_df['date'].dt.strftime('%Y-%m-%d')
                conn = sqlite3.connect(DB_PATH)
                ind_df.to_sql('daily_indicators', conn, if_exists='replace', index=False)
                conn.close()
                self.log("✅ Updated DB with new data and recalculated indicators.")
            else:
                self.log("No new data found.")
        except Exception as e:
            self.log(f" Error updating DB: {e}")

    def calculate_and_display_signals(self):
        self.log("Loading pre-calculated indicators...")
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_sql_query("SELECT * FROM daily_indicators ORDER BY symbol, date", conn)
        conn.close()
        df['date'] = pd.to_datetime(df['date'], format='mixed')
        
        self.log("Calculating Market Regime...")
        all_dates = sorted(df['date'].unique(), reverse=True)
        last_strong_str = "N/A"
        
        nifty_df = df[df['symbol'] == '^NSEI'][['date', 'adj_close', 'ema200']].copy()
        nifty_df['nifty_ok'] = nifty_df['adj_close'] > nifty_df['ema200']
        nifty_ok_by_date = nifty_df.set_index('date')['nifty_ok'].to_dict()

        stocks_df = df[df['symbol'] != '^NSEI'][['date', 'adj_close', 'ema200']].dropna()
        stocks_df['above_200'] = stocks_df['adj_close'] > stocks_df['ema200']
        breadth_ok_by_date = (stocks_df.groupby('date')['above_200'].mean() > 0.50).to_dict()

        current_date = df['date'].max()
        nifty_above_200 = nifty_ok_by_date.get(current_date, False)
        breadth_positive = breadth_ok_by_date.get(current_date, False)
        
        for d in all_dates:
            if nifty_ok_by_date.get(d, False) and breadth_ok_by_date.get(d, False):
                last_strong_str = d.strftime('%Y-%m-%d')
                break

        if nifty_above_200 and breadth_positive:
            regime_text = "  ✅  STRONG MARKET REGIME  |  FULL RISK (1.0%) ALLOWED"
            regime_color = "#064E3B" # Dark Green
            regime_fg = C_GREEN
            allow_entries = True
        else:
            failing = []
            if not nifty_above_200: failing.append("Nifty < 200 EMA")
            if not breadth_positive: failing.append("Breadth < 50%")
            regime_text = f"  ⚠️  WEAK MARKET REGIME  |  DO NOT TRADE  |  Failing: {' & '.join(failing)}  |  Last Strong: {last_strong_str}"
            regime_color = "#7F1D1D" # Dark Red
            regime_fg = C_RED
            allow_entries = False
            
        self.root.after(0, lambda: self.regime_banner.config(text=regime_text, bg=regime_color, fg=regime_fg))

        self.focus_data = []
        self.universe_data = []

        for symbol, group in df.groupby('symbol'):
            if len(group) < 750: continue
            group = group.sort_values('date').reset_index(drop=True)
            c = group['adj_close']
            group['minervini_v2'] = (
                (c > group['sma50']) & (c > group['sma150']) & (c > group['sma200']) &
                (group['sma50'] > group['sma150']) & (group['sma150'] > group['sma200']) &
                (group['sma200'] > group['sma200'].shift(21)) &
                (group['rs_6m'] > 0.30)
            )
            group['long_entry'] = (group['ema20'] > group['ema50']) & (group['macd'] > group['macd_signal']) & \
                                  (group['rsi'] > 55) & (group['adj_close'] > group['vwap']) & \
                                  (group['adx'] > 30) & (group['volume'] > (group['vol_sma'] * 1.5)) & \
                                  (group['minervini_v2'])

            last = group.iloc[-1]
            last_date = last['date'].strftime('%Y-%m-%d')
            last_close = round(last['adj_close'], 2)
            last_adx = round(last['adx'], 1)
            last_rsi = round(last['rsi'], 1)
            vol_mult = round(last['volume'] / last['vol_sma'], 2) if last['vol_sma'] > 0 else 0
            trend = "Bullish" if last['ema20'] > last['ema50'] else "Bearish"

            self.universe_data.append((symbol, last_date, last_close, trend, last_adx, last_rsi))
            if last['long_entry'] and allow_entries:
                self.focus_data.append((symbol, last_date, last_close, last_adx, last_rsi, vol_mult))

        self.full_df = df 
        self.root.after(0, self.update_trees)
        self.log(f"✅ Scan complete. Market Regime: {'STRONG' if allow_entries else 'WEAK'}")

    def update_trees(self):
        for item in self.focus_tree.get_children(): self.focus_tree.delete(item)
        for item in self.universe_tree.get_children(): self.universe_tree.delete(item)
        focus_q = self.focus_search.get().lower()
        for row in self.focus_data:
            if any(focus_q in str(v).lower() for v in row): self.focus_tree.insert('', tk.END, values=row)
        uni_q = self.uni_search.get().lower()
        for row in self.universe_data:
            if any(uni_q in str(v).lower() for v in row): self.universe_tree.insert('', tk.END, values=row)

    def on_stock_click(self, event, tree):
        selection = tree.selection()
        if not selection: return
        symbol = tree.item(selection[0], 'values')[0]
        StockChartViewer(self.root, symbol)

if __name__ == "__main__":
    root = tk.Tk()
    app = StockScannerApp(root)
    root.mainloop()