from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class Bar:
    """One OHLCV candle. `ts` is the bar START time, timezone-aware (IST)."""
    symbol: str
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Signal:
    """What the strategy wants to hold after this bar: +1 long, -1 short, 0 flat."""
    direction: int
    reason: str = ""
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None


@dataclass
class Order:
    symbol: str
    side: Side
    qty: int
    is_entry: bool
    reason: str
    created_ts: datetime
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    source: str = ""   # "auto" | "manual" | "" (backtest)
    predicted_return_pct: float | None = None  # model's 1h forecast at entry


@dataclass
class Position:
    symbol: str
    qty: int              # signed: +long / -short
    avg_price: float
    entry_ts: datetime
    stop_price: float | None
    target_price: float | None
    entry_charges: float
    entry_reason: str
    source: str = ""
    predicted_return_pct: float | None = None

    @property
    def direction(self) -> int:
        return 1 if self.qty > 0 else -1

    def to_dict(self) -> dict:
        d = asdict(self)
        d["entry_ts"] = self.entry_ts.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Position":
        d = dict(d)
        d["entry_ts"] = datetime.fromisoformat(d["entry_ts"])
        return cls(**d)


@dataclass
class Trade:
    """A completed round trip."""
    symbol: str
    direction: int
    qty: int
    entry_ts: datetime
    entry_price: float
    exit_ts: datetime
    exit_price: float
    gross_pnl: float
    charges: float
    net_pnl: float
    entry_reason: str
    exit_reason: str
    source: str = ""
    predicted_return_pct: float | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["entry_ts"] = self.entry_ts.isoformat()
        d["exit_ts"] = self.exit_ts.isoformat()
        return d
