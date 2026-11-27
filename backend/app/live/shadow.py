"""Shadow paper accounts: run rule-based strategies live, each in its own separate paper account.

Each account is rebuilt by replaying every completed candle since the account's start date through
the same engine the backtester uses (fills at the next candle's open, full charges, stops, 15:15
square-off). Replaying instead of saving engine state means a server restart can never corrupt or
skip anything, and live results are exactly comparable with backtests. Candles before the start date
only warm up the indicators; they never trade.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from itertools import groupby

from app.config import IST, NIFTY_50, Settings
from app.data.feed import INTERVAL_MINUTES, DataFeed
from app.engine.backtest import make_engine
from app.engine.metrics import compute_metrics
from app.storage.db import Store

log = logging.getLogger("shadow")


@dataclass(frozen=True)
class ShadowSpec:
    id: str
    title: str
    strategy: str
    interval: str          # "15m" intraday or "1d" swing
    history: str           # how much data to download (warm-up + test period)
    params: dict = field(default_factory=dict)
    overrides: dict = field(default_factory=dict)
    note: str = ""


SPECS = [
    ShadowSpec("supertrend_15m", "Supertrend (intraday)", "supertrend", "15m", "60d",
               note="15-min candles, long and short, squared off by 15:15."),
    ShadowSpec("opening_range_15m", "Opening range breakout (intraday)", "opening_range", "15m", "60d",
               note="Breakout of the first 30 minutes, one trade per stock per day."),
    ShadowSpec("ema_swing_1d", "EMA 20/50 swing (daily)", "ema_crossover", "1d", "2y",
               params={"fast": 20, "slow": 50},
               overrides={"allow_short": False, "default_stop_loss_pct": 12.0, "default_take_profit_pct": 1000.0},
               note="Daily candles, long only, holds for weeks. Delivery charges. Fills show a day late."),
]

CAPITAL = 500_000.0


class ShadowRunner:
    LOOP_SECONDS = 60
    EVERY = timedelta(minutes=15)

    def __init__(self, feed: DataFeed, store: Store, s: Settings, universe: list[str] | None = None):
        self.feed, self.store, self.s = feed, store, s
        self.universe = universe or NIFTY_50
        self.clock = lambda: datetime.now(IST)
        self.results: dict[str, dict] = {}
        self.updated_at: datetime | None = None
        self.error: str | None = None
        self._busy = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        starts = store.kv_get("shadow_start", {}) or {}
        today = self.clock().date().isoformat()
        for sp in SPECS:
            starts.setdefault(sp.id, today)
        store.kv_set("shadow_start", starts)
        self.starts = {k: date.fromisoformat(v) for k, v in starts.items()}

    # ---------- loop ----------
    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="shadow", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _due(self, now: datetime) -> bool:
        if self.updated_at is None:
            return True
        if now.weekday() >= 5:
            return False
        in_hours = self.s.market_open <= now.time() <= (datetime.combine(now.date(), self.s.market_close)
                                                         + timedelta(minutes=30)).time()
        # every 15 min in market hours (~2 min after each candle closes); otherwise once after close
        if in_hours:
            return now - self.updated_at >= self.EVERY and now.minute % 15 >= 2
        return self.updated_at.date() != now.date() and now.time() > self.s.market_close

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                if self._due(self.clock()):
                    self.refresh()
            except Exception as e:  # noqa: BLE001
                log.exception("shadow refresh failed")
                self.error = str(e)
            self._stop.wait(self.LOOP_SECONDS)

    # ---------- replay ----------
    def refresh(self) -> dict[str, dict]:
        if not self._busy.acquire(blocking=False):
            return self.results
        try:
            now = self.clock()
            data: dict[tuple[str, str], dict] = {}
            for sp in SPECS:
                key = (sp.interval, sp.history)
                if key not in data:
                    data[key] = self.feed.history_many(self.universe, sp.interval, sp.history)
                self.results[sp.id] = self.run_one(sp, data[key], now)
            self.updated_at, self.error = now, None
            return self.results
        finally:
            self._busy.release()

    def run_one(self, sp: ShadowSpec, bars_by_symbol: dict, now: datetime) -> dict:
        s = self.s.with_overrides(initial_capital=CAPITAL, **sp.overrides)
        start = self.starts[sp.id]
        step = timedelta(minutes=INTERVAL_MINUTES[sp.interval])
        if sp.interval == "1d":
            done = lambda b: b.ts.date() < now.date()          # today's daily candle is still forming
        else:
            done = lambda b: b.ts + step <= now
        bars = sorted((b for v in bars_by_symbol.values() for b in v if done(b)), key=lambda b: (b.ts, b.symbol))
        engine = make_engine(sp.strategy, sp.params, sp.interval, s)
        equity: list[tuple[str, float]] = []
        for ts, group in groupby(bars, key=lambda b: b.ts):
            live = ts.date() >= start
            for bar in group:
                if live:
                    engine.process_bar(bar)
                else:
                    engine.warm(bar)
            if live:
                equity.append((ts.isoformat(), round(engine.broker.equity(), 2)))
        b = engine.broker
        trades = b.trades
        m = compute_metrics(trades, equity, CAPITAL)
        last_ts = bars[-1].ts.isoformat() if bars else None
        positions = [{
            "symbol": sym, "side": "LONG" if p.qty > 0 else "SHORT", "qty": abs(p.qty),
            "entry_price": round(p.avg_price, 2), "entry_ts": p.entry_ts.isoformat(),
            "last_price": round(b.last_price.get(sym, p.avg_price), 2),
            "unrealized_pnl": round((b.last_price.get(sym, p.avg_price) - p.avg_price) * p.qty, 2),
            "stop_price": round(p.stop_price, 2) if p.stop_price else None,
            "target_price": round(p.target_price, 2) if p.target_price else None,
        } for sym, p in b.positions.items()]
        return {
            "id": sp.id, "title": sp.title, "strategy": sp.strategy, "interval": sp.interval, "note": sp.note,
            "params": {**engine.strategy.params}, "start_date": start.isoformat(), "initial_capital": CAPITAL,
            "equity": round(b.equity(), 2), "cash": round(b.cash, 2),
            "realized_pnl": round(sum(t.net_pnl for t in trades), 2),
            "unrealized_pnl": round(sum(p["unrealized_pnl"] for p in positions), 2),
            "metrics": m, "positions": positions,
            "trades": [t.to_dict() for t in trades[-50:]][::-1],
            "data_as_of": last_ts,
        }

    def summary(self) -> dict:
        return {
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "error": self.error,
            "accounts": [self.results[sp.id] for sp in SPECS if sp.id in self.results],
        }
