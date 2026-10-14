import tkinter as tk
from tkinter import ttk
import sqlite3
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.dates import DateFormatter, num2date
from matplotlib.ticker import ScalarFormatter
import matplotlib.dates as mdates
import warnings

warnings.filterwarnings('ignore')

DB_PATH = r"D:\Project\Institutional Stock Trend Scanner V3.0\ohlc_10yr.db"

# --- CHART COLOR PALETTE ---
C_BG_MAIN = '#0B1120'
C_BG_PANEL = '#151E32'
C_TEXT_PRI = '#E2E8F0'
C_TEXT_SEC = '#94A3B8'
C_GREEN = '#00E676'
C_RED = '#FF5252'
C_BLUE = '#38BDF8'
C_GOLD = '#FFD700'

class StockChartViewer:
    def __init__(self, parent, symbol):
        self.symbol = symbol
        self.parent = parent
        self.win = tk.Toplevel(parent)
        self.win.title(f"Institutional Chart: {symbol}")
        self.win.geometry("1300x900")
        self.win.configure(bg=C_BG_MAIN)
        
        self.df = None
        self.nifty_ema200 = None
        self.buys = []
        self.sells = []
        self.current_chart_type = 'CANDLE'
        
        self.build_ui()
        self.load_and_process_data()
        self.plot_chart('6M')

    def build_ui(self):
        ctrl_frame = tk.Frame(self.win, bg=C_BG_MAIN)
        ctrl_frame.pack(fill=tk.X, padx=20, pady=15)
        
        tk.Label(ctrl_frame, text=f" {self.symbol}  |  INSTITUTIONAL CHART", font=('Segoe UI', 14, 'bold'), fg=C_GOLD, bg=C_BG_MAIN).pack(side=tk.LEFT, padx=10)
        
        type_frame = tk.Frame(ctrl_frame, bg=C_BG_MAIN)
        type_frame.pack(side=tk.LEFT, padx=30)
        tk.Label(type_frame, text="TYPE:", fg=C_TEXT_SEC, bg=C_BG_MAIN, font=('Segoe UI', 9, 'bold')).pack(side=tk.LEFT, padx=5)
        
        self.btn_line = tk.Button(type_frame, text="LINE", font=('Segoe UI', 9, 'bold'), bg=C_BG_PANEL, fg=C_TEXT_SEC, relief=tk.FLAT, padx=12, pady=2, command=lambda: self.change_chart_type('LINE'))
        self.btn_line.pack(side=tk.LEFT, padx=2)
        self.btn_candle = tk.Button(type_frame, text="CANDLE", font=('Segoe UI', 9, 'bold'), bg=C_BLUE, fg=C_BG_MAIN, relief=tk.FLAT, padx=12, pady=2, command=lambda: self.change_chart_type('CANDLE'))
        self.btn_candle.pack(side=tk.LEFT, padx=2)

        btn_frame = tk.Frame(ctrl_frame, bg=C_BG_MAIN)
        btn_frame.pack(side=tk.RIGHT, padx=10)
        self.periods = ['1M', '3M', '6M', '1Y', 'ALL']
        self.btn_vars = {}
        for p in self.periods:
            btn = tk.Button(btn_frame, text=p, font=('Segoe UI', 10, 'bold'), bg=C_BG_PANEL, fg=C_TEXT_SEC, relief=tk.FLAT, padx=15, pady=2, command=lambda period=p: self.change_period(period))
            btn.pack(side=tk.LEFT, padx=2)
            self.btn_vars[p] = btn
        self.btn_vars['6M' if '6M' in self.periods else '3M'].config(bg=C_BLUE, fg=C_BG_MAIN)

        self.fig, self.ax = plt.subplots(figsize=(14, 8))
        self.fig.patch.set_facecolor(C_BG_MAIN)
        self.ax.set_facecolor(C_BG_MAIN)
        self.ax.tick_params(colors=C_TEXT_SEC)
        self.ax.spines['bottom'].set_color(C_BG_PANEL)
        self.ax.spines['left'].set_color(C_BG_PANEL)
        self.ax.spines['top'].set_visible(False)
        self.ax.spines['right'].set_visible(False)
        self.ax.grid(True, color='#1E293B', linestyle='-', linewidth=0.5)
        
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.win)
        canvas_widget = self.canvas.get_tk_widget()
        canvas_widget.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        # Draggable Info Panel
        self.info_panel = tk.Frame(canvas_widget, bg=C_BG_PANEL, bd=1, relief='solid', cursor='fleur')
        self.info_panel.place(relx=1.0, rely=0.0, anchor='ne', x=-20, y=20)
        self.info_text = tk.Text(self.info_panel, bg=C_BG_PANEL, fg=C_TEXT_PRI, font=('Consolas', 9), height=13, width=40, bd=0, highlightthickness=0, state=tk.DISABLED)
        self.info_text.pack(padx=8, pady=8)
        self.info_text.tag_configure('header', foreground=C_TEXT_SEC)
        self.info_text.tag_configure('pass', foreground=C_GREEN)
        self.info_text.tag_configure('fail', foreground=C_RED)
        self.info_text.tag_configure('gold', foreground=C_GOLD)

        for widget in [self.info_panel, self.info_text]:
            widget.bind("<Button-1>", self.start_drag)
            widget.bind("<B1-Motion>", self.do_drag)

        self.canvas.mpl_connect('motion_notify_event', self.on_mouse_move)
        self.crosshair_v = self.ax.axvline(color=C_TEXT_SEC, linestyle=':', linewidth=0.8, visible=False)
        self.crosshair_h = self.ax.axhline(color=C_TEXT_SEC, linestyle=':', linewidth=0.8, visible=False)

    def start_drag(self, event):
        self.info_panel._drag_start_x = event.x
        self.info_panel._drag_start_y = event.y

    def do_drag(self, event):
        x = self.info_panel.winfo_x() + event.x - self.info_panel._drag_start_x
        y = self.info_panel.winfo_y() + event.y - self.info_panel._drag_start_y
        self.info_panel.place(x=x, y=y)

    def load_and_process_data(self):
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_sql_query(f"SELECT * FROM daily_indicators WHERE symbol='{self.symbol}' ORDER BY date", conn)
        nifty_df = pd.read_sql_query(f"SELECT date, adj_close, ema200 FROM daily_indicators WHERE symbol='^NSEI' ORDER BY date", conn)
        conn.close()
        
        if df.empty:
            self.info_text.config(state=tk.NORMAL)
            self.info_text.insert(tk.END, "❌ No data found.", 'fail')
            self.info_text.config(state=tk.DISABLED)
            return
            
        df['date'] = pd.to_datetime(df['date'], format='mixed')
        nifty_df['date'] = pd.to_datetime(nifty_df['date'], format='mixed')
        
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
                           
        self.df = df.dropna().reset_index(drop=True)
        self.df['date_num'] = mdates.date2num(self.df['date'])
        
        if not nifty_df.empty:
            last_stock_date = self.df['date'].max()
            nifty_val = nifty_df[nifty_df['date'] <= last_stock_date].iloc[-1]
            self.nifty_ema200 = nifty_val['ema200']
            self.nifty_close = nifty_val['adj_close']

        self.simulate_trades()

    def simulate_trades(self):
        self.buys = []
        self.sells = []
        in_trade = False
        stop_loss = 0
        for i in range(len(self.df)):
            row = self.df.iloc[i]
            if not in_trade:
                if row['long_entry']:
                    self.buys.append((row['date'], row['adj_close']))
                    in_trade = True
                    stop_loss = row['adj_close'] - (1.5 * row['atr'])
            else:
                exit_price = None
                if row['low'] <= stop_loss: exit_price = stop_loss
                else:
                    neg_count = sum([row['ema20'] < row['ema50'], row['macd'] < 0, row['rsi'] < 50, row['adj_close'] < (row['vwap'] - (row['atr'] * 0.2)), row['adx'] < 20])
                    if neg_count >= 4: exit_price = row['adj_close']
                if exit_price is not None:
                    self.sells.append((row['date'], exit_price))
                    in_trade = False

    def change_chart_type(self, chart_type):
        self.current_chart_type = chart_type
        self.btn_line.config(bg=C_BG_PANEL, fg=C_TEXT_SEC)
        self.btn_candle.config(bg=C_BG_PANEL, fg=C_TEXT_SEC)
        if chart_type == 'LINE': self.btn_line.config(bg=C_BLUE, fg=C_BG_MAIN)
        else: self.btn_candle.config(bg=C_BLUE, fg=C_BG_MAIN)
        current_period = '6M'
        for p, btn in self.btn_vars.items():
            if btn.cget('bg') == C_BLUE: current_period = p
        self.plot_chart(current_period)

    def change_period(self, period):
        for p, btn in self.btn_vars.items(): btn.config(bg=C_BG_PANEL, fg=C_TEXT_SEC)
        self.btn_vars[period].config(bg=C_BLUE, fg=C_BG_MAIN)
        self.plot_chart(period)

    def update_info_panel(self, row):
        nifty_status = "NO GO" if not (self.nifty_close and self.nifty_close > self.nifty_ema200) else "PASS"
        nifty_val_str = f"{self.nifty_close:.0f}/{self.nifty_ema200:.0f}" if self.nifty_ema200 else "N/A"
        ema_status = "PASS" if row['ema20'] > row['ema50'] else "FAIL"
        macd_status = "PASS" if row['macd'] > row['macd_signal'] else "FAIL"
        rsi_status = "PASS" if row['rsi'] > 55 else "FAIL"
        vwap_status = "PASS" if row['adj_close'] > row['vwap'] else "FAIL"
        adx_status = "PASS" if row['adx'] > 30 else "FAIL"
        vol_status = "PASS" if row['volume'] > (row['vol_sma'] * 1.5) else "FAIL"
        overall = "BUY" if all([s=="PASS" for s in [ema_status, macd_status, rsi_status, vwap_status, adx_status, vol_status]]) else "WAIT"
        action_color = "pass" if overall == "BUY" else "fail"

        self.info_text.config(state=tk.NORMAL)
        self.info_text.delete('1.0', tk.END)
        self.info_text.insert(tk.END, "REGIME & SIGNAL STATUS\n", 'gold')
        self.info_text.insert(tk.END, "─" * 35 + "\n", 'header')
        self.info_text.insert(tk.END, f"Nifty>200EMA: {nifty_val_str} ", 'header')
        self.info_text.insert(tk.END, f"[{nifty_status}]\n", 'fail' if nifty_status=="NO GO" else 'pass')
        self.info_text.insert(tk.END, f"EMA 20 > 50 : {row['ema20']:.0f}/{row['ema50']:.0f} ", 'header')
        self.info_text.insert(tk.END, f"[{ema_status}]\n", 'pass' if ema_status=="PASS" else 'fail')
        self.info_text.insert(tk.END, f"MACD > Sig  : {row['macd']:.1f}/{row['macd_signal']:.1f} ", 'header')
        self.info_text.insert(tk.END, f"[{macd_status}]\n", 'pass' if macd_status=="PASS" else 'fail')
        self.info_text.insert(tk.END, f"RSI > 55    : {row['rsi']:.1f}              ", 'header')
        self.info_text.insert(tk.END, f"[{rsi_status}]\n", 'pass' if rsi_status=="PASS" else 'fail')
        self.info_text.insert(tk.END, f"Close > VWAP: {row['adj_close']:.0f}/{row['vwap']:.0f} ", 'header')
        self.info_text.insert(tk.END, f"[{vwap_status}]\n", 'pass' if vwap_status=="PASS" else 'fail')
        self.info_text.insert(tk.END, f"ADX > 30    : {row['adx']:.1f}              ", 'header')
        self.info_text.insert(tk.END, f"[{adx_status}]\n", 'pass' if adx_status=="PASS" else 'fail')
        self.info_text.insert(tk.END, f"Vol > 1.5x  : {row['volume']/1e6:.1f}M/{(row['vol_sma']*1.5)/1e6:.1f}M ", 'header')
        self.info_text.insert(tk.END, f"[{vol_status}]\n", 'pass' if vol_status=="PASS" else 'fail')
        self.info_text.insert(tk.END, "─" * 35 + "\n", 'header')
        self.info_text.insert(tk.END, f"ACTION      : Risk: {'1.0' if overall=='BUY' else '0'}% ", 'header')
        self.info_text.insert(tk.END, f"{overall}\n", action_color)
        self.info_text.config(state=tk.DISABLED)

    def on_mouse_move(self, event):
        if event.inaxes == self.ax and self.df is not None:
            self.crosshair_v.set_visible(True)
            self.crosshair_h.set_visible(True)
            xdata = event.xdata
            if xdata is not None:
                mouse_date = num2date(xdata)
                if mouse_date.tzinfo is not None: mouse_date = mouse_date.replace(tzinfo=None)
                idx = (self.df['date'] - mouse_date).abs().idxmin()
                row = self.df.iloc[idx]
                self.crosshair_v.set_xdata([row['date_num']])
                self.crosshair_h.set_ydata([row['adj_close']])
                self.update_info_panel(row)
                self.fig.canvas.draw_idle()
        else:
            self.crosshair_v.set_visible(False)
            self.crosshair_h.set_visible(False)
            self.fig.canvas.draw_idle()

    def plot_chart(self, period):
        if self.df is None or self.df.empty: return
        self.ax.clear()
        self.ax.set_facecolor(C_BG_MAIN)
        self.ax.tick_params(colors=C_TEXT_SEC)
        self.ax.spines['bottom'].set_color(C_BG_PANEL)
        self.ax.spines['left'].set_color(C_BG_PANEL)
        self.ax.spines['top'].set_visible(False)
        self.ax.spines['right'].set_visible(False)
        self.ax.grid(True, color='#1E293B', linestyle='-', linewidth=0.5)
        
        formatter = ScalarFormatter(useOffset=False)
        formatter.set_scientific(False)
        self.ax.yaxis.set_major_formatter(formatter)
        
        self.crosshair_v = self.ax.axvline(color=C_TEXT_SEC, linestyle=':', linewidth=0.8, visible=False)
        self.crosshair_h = self.ax.axhline(color=C_TEXT_SEC, linestyle=':', linewidth=0.8, visible=False)

        max_date = self.df['date'].max()
        if period == '1M': plot_df = self.df[self.df['date'] >= (max_date - pd.DateOffset(months=1))]
        elif period == '3M': plot_df = self.df[self.df['date'] >= (max_date - pd.DateOffset(months=3))]
        elif period == '6M': plot_df = self.df[self.df['date'] >= (max_date - pd.DateOffset(months=6))]
        elif period == '1Y': plot_df = self.df[self.df['date'] >= (max_date - pd.DateOffset(years=1))]
        else: plot_df = self.df
        if plot_df.empty: return

        plot_df = plot_df[plot_df['adj_close'] > 0].copy()

        self.ax.plot(plot_df['date_num'], plot_df['ema20'], color=C_GOLD, linewidth=1.2, label='EMA 20', alpha=0.9)
        self.ax.plot(plot_df['date_num'], plot_df['ema50'], color=C_BLUE, linewidth=1.2, label='EMA 50', alpha=0.9)
        self.ax.plot(plot_df['date_num'], plot_df['vwap'], color='#A855F7', linewidth=1.0, linestyle='--', label='VWAP', alpha=0.8)

        if self.current_chart_type == 'LINE':
            self.ax.plot(plot_df['date_num'], plot_df['adj_close'], color=C_GREEN, linewidth=1.5, label='Price', zorder=2)
        else:
            width2 = 0.04
            up = plot_df[plot_df['adj_close'] >= plot_df['open']]
            down = plot_df[plot_df['adj_close'] < plot_df['open']]
            self.ax.vlines(up['date_num'], up['low'], up['high'], color=C_GREEN, linewidth=0.8)
            self.ax.vlines(down['date_num'], down['low'], down['high'], color=C_RED, linewidth=0.8)
            self.ax.bar(up['date_num'], up['adj_close']-up['open'], width2, bottom=up['open'], color=C_GREEN, align='center')
            self.ax.bar(down['date_num'], down['adj_close']-down['open'], width2, bottom=down['open'], color=C_RED, align='center')

        x_min, x_max = plot_df['date_num'].min(), plot_df['date_num'].max()
        x_range = x_max - x_min if x_max > x_min else 1
        self.ax.set_xlim(x_min - x_range * 0.02, x_max + x_range * 0.02)

        y_min = plot_df[['adj_close', 'low']].min().min()
        y_max = plot_df[['adj_close', 'high']].max().max()
        y_range = y_max - y_min if y_max > y_min else y_max * 0.1
        self.ax.set_ylim(y_min - y_range * 0.05, y_max + y_range * 0.05)
        self.ax.xaxis_date()

        start_date, end_date = plot_df['date'].min(), plot_df['date'].max()
        view_buys = [(d, p) for d, p in self.buys if start_date <= d <= end_date]
        view_sells = [(d, p) for d, p in self.sells if start_date <= d <= end_date]
        
        if view_buys:
            self.ax.scatter([mdates.date2num(d) for d, p in view_buys], [p for d, p in view_buys], marker='^', color=C_GREEN, s=120, zorder=5, label='BUY', edgecolors=C_BG_MAIN)
        if view_sells:
            self.ax.scatter([mdates.date2num(d) for d, p in view_sells], [p for d, p in view_sells], marker='v', color=C_RED, s=120, zorder=5, label='SELL', edgecolors=C_BG_MAIN)
            
        self.ax.set_title(f"{self.symbol}  |  {period} VIEW  |  {self.current_chart_type}", fontsize=14, color=C_TEXT_PRI, pad=15, fontweight='bold')
        self.ax.legend(facecolor=C_BG_PANEL, labelcolor=C_TEXT_SEC, loc='upper left', framealpha=0.9)
        
        if period in ['1M', '3M']: self.ax.xaxis.set_major_formatter(DateFormatter('%d %b'))
        elif period in ['6M', '1Y']: self.ax.xaxis.set_major_formatter(DateFormatter('%b %Y'))
        else: self.ax.xaxis.set_major_formatter(DateFormatter('%Y'))
        self.fig.autofmt_xdate(rotation=45)
        self.fig.tight_layout()
        
        if not plot_df.empty: self.update_info_panel(plot_df.iloc[-1])
        self.canvas.draw()

if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()
    app = StockChartViewer(root, "RELIANCE.NS")
    root.mainloop()