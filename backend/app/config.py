"""Central settings. Everything tunable lives here and can be overridden via env vars / .env."""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

IST = ZoneInfo("Asia/Kolkata")
BACKEND_DIR = Path(__file__).resolve().parent.parent

# A liquid starter universe from NIFTY 50.
DEFAULT_SYMBOLS = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "SBIN", "ITC", "LT", "AXISBANK", "BHARTIARTL",
]


# NIFTY 50 constituents (index is rebalanced every 6 months - check niftyindices.com
# and update this list). Symbols with no data are skipped automatically.
NIFTY_50 = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK", "BAJAJ-AUTO", "BAJFINANCE",
    "BAJAJFINSV", "BEL", "BHARTIARTL", "CIPLA", "COALINDIA", "DRREDDY", "EICHERMOT", "ETERNAL",
    "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE", "HINDALCO", "HINDUNILVR", "ICICIBANK", "INDIGO",
    "INFY", "ITC", "JIOFIN", "JSWSTEEL", "KOTAKBANK", "LT", "M&M", "MARUTI", "MAXHEALTH",
    "NESTLEIND", "NTPC", "ONGC", "POWERGRID", "RELIANCE", "SBILIFE", "SBIN", "SHRIRAMFIN",
    "SUNPHARMA", "TATACONSUM", "TMPV", "TATASTEEL", "TCS", "TECHM", "TITAN", "TRENT",
    "ULTRACEMCO", "WIPRO",
]


def _f(name: str, default: float) -> float:
    return float(os.getenv(name, default))


# Index futures in the simulator. Intraday only (squared off at 15:15 like stocks), priced off the
# live index. Lot sizes are revised by NSE from time to time - check the latest NSE circular.
FUTURES = {
    "NIFTY-FUT": {"name": "NIFTY 50 futures", "underlying": "NIFTY", "lot_size": int(_f("NIFTY_LOT_SIZE", 65))},
    "BANKNIFTY-FUT": {"name": "BANK NIFTY futures", "underlying": "BANKNIFTY",
                      "lot_size": int(_f("BANKNIFTY_LOT_SIZE", 30))},
}
FUTURES_MARGIN_PCT = _f("FUTURES_MARGIN_PCT", 12.0)   # SPAN + exposure, roughly 10-13% for index futures


@dataclass(frozen=True)
class Settings:
    # Account
    initial_capital: float = _f("INITIAL_CAPITAL", 100_000)
    margin_rate: float = _f("MARGIN_RATE", 1.0)  # 1.0 = no leverage; 0.2 = 5x intraday leverage

    # Execution realism
    slippage_bps: float = _f("SLIPPAGE_BPS", 3)  # 3 bps = 0.03% per fill

    # Risk
    risk_per_trade_pct: float = _f("RISK_PER_TRADE_PCT", 1.0)   # % of equity lost if stop hits
    max_position_pct: float = _f("MAX_POSITION_PCT", 20.0)      # max notional per position, % of equity
    max_open_positions: int = int(_f("MAX_OPEN_POSITIONS", 5))
    max_daily_loss_pct: float = _f("MAX_DAILY_LOSS_PCT", 2.0)   # halt new entries for the day after this
    default_stop_loss_pct: float = _f("DEFAULT_STOP_LOSS_PCT", 1.0)
    default_take_profit_pct: float = _f("DEFAULT_TAKE_PROFIT_PCT", 2.0)
    allow_short: bool = os.getenv("ALLOW_SHORT", "true").lower() == "true"

    # NSE session (IST)
    market_open: time = time(9, 15)
    market_close: time = time(15, 30)
    no_new_entries_after: time = time(15, 0)   # bar *end* time
    square_off_at: time = time(15, 15)         # bar *start* time; brokers auto square-off ~15:20

    # Storage / API
    db_path: str = os.getenv("DB_PATH", str(BACKEND_DIR / "data" / "trading.db"))
    api_key: str = os.getenv("APP_API_KEY", "")  # if set, required for start/stop/backtest
    cors_origins: list[str] = field(
        default_factory=lambda: os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
    )

    def with_overrides(self, **kw) -> "Settings":
        return replace(self, **{k: v for k, v in kw.items() if v is not None})


settings = Settings()
