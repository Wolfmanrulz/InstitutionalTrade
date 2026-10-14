# Institutional Stock Trend Scanner & Charting System
**Version:** 8.0 (Optimized DB Architecture)  
**Asset Class:** Indian Equities (NSE)  
**Timeframe:** Daily (Swing/Position Trading)  

---

## 1. Strategy Criteria & Filters

The system uses a multi-layered approach: a broad Market Regime filter, a strict Minervini V2 pre-filter, and a precise Indicator Confluence entry/exit logic.

### A. Market Regime Filter (Macro Context)
*Entries are strictly blocked if the overall market is weak.*
1. **Nifty 50 Trend:** Nifty 50 Close > 200 EMA.
2. **Market Breadth:** > 50% of the universe stocks must be trading above their respective 200 EMAs.

### B. Minervini V2 Pre-Filter (Stage 2 Uptrend)
*Filters out counter-trend and weak momentum stocks before evaluating short-term triggers.*
1. **Price Position:** Close > 50 SMA, 150 SMA, and 200 SMA.
2. **SMA Alignment:** 50 SMA > 150 SMA > 200 SMA.
3. **Trend Duration:** 200 SMA must be trending up for at least 1 month (Current 200 SMA > 200 SMA 21 days ago).
4. **Relative Strength (RS):** 6-Month Return > 30%.

### C. Entry Triggers (Indicator Confluence)
*All conditions must be TRUE simultaneously on the daily candle.*
1. **Trend:** EMA 20 > EMA 50.
2. **Momentum:** MACD Line > MACD Signal Line.
3. **Strength:** RSI (14) > 55.
4. **Value/Institutional Support:** Close > 20-day VWAP.
5. **Trend Strength:** ADX (14) > 30.
6. **Volume:** Current Volume > 1.5x 20-day Volume SMA.

### D. Exit Logic (Risk Management)
*Positions are exited when the first of the following occurs:*
1. **Initial Stop Loss:** 1.5x ATR (14) below the entry price.
2. **Threshold 4 Exit:** 4 out of the following 5 conditions are TRUE:
   - EMA 20 < EMA 50
   - MACD < 0
   - RSI < 50
   - Close < (VWAP - 0.2 * ATR)
   - ADX < 20

---

## 2. Backtesting Analysis & Results

We tested the Baseline strategy against Minervini V2 variations on a 10-year Nifty 500 dataset (70/30 train/test split).

### Final Performance Metrics (Test Period)

| Metric | Baseline Strategy | Hybrid V2 (RS > 30%) | Improvement |
| :--- | :--- | :--- | :--- |
| **Total Return** | 23.91% | **64.62%** | +40.71% |
| **Max Drawdown** | 28.62% | **22.49%** | -6.13% (Better) |
| **Win Rate** | 33.33% | **38.89%** | +5.56% |
| **Profit Factor** | 1.36 | **2.13** | +0.77 |
| **Total Trades** | 81 | **72** | -9 (Higher Quality) |

*Analysis: The Minervini V2 filter successfully eliminated low-quality "bull traps," reducing trade frequency but dramatically increasing the Profit Factor and reducing drawdowns.*

---

## 3. Data Structure (SQLite Database)

**File:** `ohlc_10yr.db`

### Table 1: `daily_ohlc` (Raw Data)
Stores raw market data downloaded via `yfinance`.
* **Primary Key:** `(symbol, date)`
* **Columns:** `symbol` (TEXT), `date` (TEXT), `open`, `high`, `low`, `close`, `adj_close`, `volume` (REAL)

### Table 2: `daily_indicators` (Pre-calculated Math)
Stores heavy mathematical calculations to ensure instant UI loading. Boolean signals are *not* stored here to allow on-the-fly parameter tweaking.
* **Primary Key:** `(symbol, date)`
* **Columns:** All columns from `daily_ohlc` PLUS:
  * `ema20`, `ema50`, `ema200` (REAL)
  * `macd`, `macd_signal` (REAL)
  * `rsi`, `atr`, `adx` (REAL)
  * `vwap`, `vol_sma` (REAL)
  * `sma50`, `sma150`, `sma200`, `rs_6m` (REAL)

---

## 4. Code Architecture & File Structure

The project uses a **Hybrid Architecture**: heavy indicators are stored in the DB, while boolean logic and trade simulations are computed in RAM on the fly.

### Core Files
1. **`populate_indicators_db.py`**
   * **Role:** One-time initialization script.
   * **Function:** Reads `daily_ohlc`, calculates all mathematical indicators, and writes them to the `daily_indicators` table.

2. **`Institutional_Scanner_App_v8.0.py`**
   * **Role:** Main UI Application (Tkinter).
   * **Features:** Institutional Dark Blue UI, auto-updates DB, reads from `daily_indicators`, computes booleans on the fly, enforces Market Regime entry blocking.

3. **`stock_chart_viewer_v3.py`**
   * **Role:** Standalone Interactive Charting Module.
   * **Features:** Matplotlib integration, Line/Candlestick types, 1M-ALL timeframes, interactive crosshair, draggable status panel with real-time PASS/FAIL status.

---

## 5. Execution & Maintenance Guide

### Initial Setup
1. Ensure Python 3.10+ is installed with dependencies: `pandas`, `numpy`, `sqlite3`, `yfinance`, `matplotlib`, `tkinter`.
2. Run the population script once to build the optimized database:
   ```bash
   python populate_indicators_db.py