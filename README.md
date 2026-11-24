# TradeBot: NSE paper-trading bot (MVP)

An automated trading system for Indian equities (NSE) that trades **simulated money on live prices**.
You can use it to measure whether a strategy really works before any real money is involved.

```
frontend/  Next.js PWA (phone + web): live P&L, positions, backtests, history
backend/   Python: data feed → strategy → risk manager → simulated broker → SQLite
```

## Quick start (Windows)

**Backend**
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python -m pytest -q                          # offline tests
.\.venv\Scripts\python -m scripts.run_backtest --all          # backtest every strategy on real NSE data
.\.venv\Scripts\python -m uvicorn app.api.main:app --port 8000
```

**Frontend** (in a second terminal)
```powershell
cd frontend
npm install
npm run dev        # http://localhost:3000
```

The PWA installs to your home screen only on HTTPS. Locally it works as a normal web app.
After deploying (Vercel for the frontend, Railway or a VPS for the backend), open it on your phone
and choose "Add to Home screen".

## The app (4 tabs)

- **Home**: account value, today's P&L, Auto bot status, top picks, recent activity
- **Trading**: top 5 NIFTY 50 stocks ranked by predicted next-hour return. **Manual**: tap a stock, set amount, stop-loss and target, then Buy or Sell short. **Auto**: the bot trades the top picks by your rules.
- **Portfolio**: open positions (with Close), Auto vs Manual results, equity curve, trade history with ₹ and % profit
- **Settings**: auto-trading rules, strategy guide, account reset, backtest lab

## How it works

| Component | File | Notes |
|---|---|---|
| Predictors | `backend/app/predict/model.py` | Competing models predicting the 1-hour return: `ridge_base` (own price action), `ridge_ctx` and `lgbm_ctx` (plus NIFTY/BANKNIFTY trend, India VIX, strength vs index). Scored by 5-fold walk-forward testing with a 1-hour purge gap, against an "always up" baseline. |
| Scanner | `backend/app/predict/scanner.py` | Every 15 min: downloads NIFTY 50 + index candles, retrains all models, ranks stocks with the active (champion) model, logs every model's forecasts and scores them 1 hour later. A challenger becomes active only after beating the champion live (150+ candles, IC +0.02). |
| Index futures | `backend/app/config.py`, `broker/costs.py` | NIFTY / BANKNIFTY futures, intraday, priced off the live index (ignores the futures basis). Lot sizes, margin % and futures STT are env-configurable (`NIFTY_LOT_SIZE`, `BANKNIFTY_LOT_SIZE`, `FUTURES_MARGIN_PCT`, `FUT_STT_SELL_PCT`); verify against the latest NSE circular. |
| Paper account | `backend/app/live/service.py` | Manual + Auto trading, checks stops/targets on 1m candles every minute, persisted to SQLite |
| Market data | `backend/app/data/feed.py` | yfinance (free, may lag by a few minutes). Swap in Upstox/Dhan by implementing `DataFeed`. |
| Strategies | `backend/app/strategies/` | `ema_crossover`, `rsi_reversion`, `opening_range`. Add your own by subclassing `Strategy`. |
| Risk manager | `backend/app/risk/manager.py` | Risk-based sizing, position cap, max open positions, daily loss halt |
| Simulated broker | `backend/app/broker/simulated.py` | Next-bar-open fills, slippage, stops/targets, gap handling |
| NSE charges | `backend/app/broker/costs.py` | Brokerage, STT, exchange, SEBI, stamp duty, GST (verify current rates) |
| Engine | `backend/app/engine/core.py` | **One code path for both backtest and live trading** |
| API | `backend/app/api/main.py` | REST API for the PWA (`/docs` for Swagger) |

### Rules against fooling ourselves
- Signals are computed at a bar's **close** and filled at the **next bar's open**, so there is no look-ahead.
- If a stop and a target are both hit in the same bar, the **stop** is assumed to hit first.
- If price gaps through a stop, the fill is at the (worse) open price.
- All NSE charges and slippage are included. Compare every result against the **buy & hold** benchmark.
- Models are judged on **live** forecasts (made before the outcome existed), not just backtests, and
  must beat "always guess up", not 50%.
- The scanner ignores the 15m candle that is still forming, so live features match training features.

## Data limits (yfinance)
1m bars: last 7 days · 5m/15m/30m: last 60 days · 1h: ~2 years · 1d: decades.

## Roadmap
1. ✅ Data, backtester, baseline strategies, live paper trading, PWA dashboard
2. Upstox / Dhan live feed (real-time ticks instead of delayed polling)
3. ML model (LightGBM on engineered features) with walk-forward validation
4. Push notifications for trades and daily summaries
5. Deployment (Vercel + Railway) and PostgreSQL
6. Real-money execution via broker API, after weeks of consistent paper results and
   compliance with SEBI's retail algo framework
