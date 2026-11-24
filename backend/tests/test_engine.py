"""Offline tests on synthetic bars (no network)."""
from datetime import datetime, timedelta

import pytest

from app.broker.costs import IndianEquityCosts
from app.config import IST, Settings
from app.engine.backtest import run_on_bars
from app.models import Bar, Side
from app.strategies.base import History, Strategy
from app.models import Signal
from app import strategies


def day_bars(symbol: str, day: datetime, prices: list[float], minutes: int = 15) -> list[Bar]:
    start = day.replace(hour=9, minute=15, second=0, microsecond=0, tzinfo=IST)
    out = []
    for i, p in enumerate(prices):
        out.append(Bar(symbol, start + timedelta(minutes=minutes * i), p, p * 1.001, p * 0.999, p, 1000))
    return out


class AlwaysLong(Strategy):
    name = "always_long"

    def on_bar(self, hist: History, position: int) -> Signal:
        return Signal(1, "test")


@pytest.fixture(autouse=True)
def register():
    strategies.REGISTRY["always_long"] = AlwaysLong
    yield
    strategies.REGISTRY.pop("always_long", None)


S = Settings(initial_capital=100_000, slippage_bps=0, default_stop_loss_pct=50, default_take_profit_pct=500,
             max_position_pct=50, risk_per_trade_pct=100)


def test_intraday_charges_reasonable():
    c = IndianEquityCosts("intraday")
    buy, sell = c.charges(Side.BUY, 1000, 100), c.charges(Side.SELL, 1000, 100)
    # Rs 1L turnover each side.
    # BUY : brokerage 20 + exchange 2.97 + SEBI 0.10 + stamp 3 + GST 4.15
    # SELL: brokerage 20 + exchange 2.97 + SEBI 0.10 + STT 25 + GST 4.15
    assert buy == pytest.approx(30.22)
    assert sell == pytest.approx(52.22)


def test_fill_at_next_open_no_lookahead():
    bars = day_bars("ABC", datetime(2026, 1, 5), [100, 110, 120, 130])
    r = run_on_bars({"ABC": bars}, "always_long", {}, "15m", S)
    t = r.trades[0]
    # Signal at close of bar 0 -> filled at OPEN of bar 1 (110), not at 100.
    assert t.entry_price == pytest.approx(110)
    assert t.entry_ts == bars[1].ts


def test_intraday_square_off():
    prices = [100.0] * 25  # 09:15 .. 15:15
    bars = day_bars("ABC", datetime(2026, 1, 5), prices)
    r = run_on_bars({"ABC": bars}, "always_long", {}, "15m", S)
    assert len(r.trades) == 1
    assert r.trades[0].exit_reason == "intraday square-off"
    assert r.trades[0].exit_ts.hour == 15 and r.trades[0].exit_ts.minute == 15
    assert r.trades[0].net_pnl < 0  # flat price -> lose exactly the charges


def test_stop_loss_hits():
    s = Settings(initial_capital=100_000, slippage_bps=0, default_stop_loss_pct=1, default_take_profit_pct=50)
    bars = day_bars("ABC", datetime(2026, 1, 5), [100, 100, 95, 95])
    r = run_on_bars({"ABC": bars}, "always_long", {}, "15m", s)
    assert r.trades[0].exit_reason == "stop-loss"
    assert r.trades[0].exit_price == pytest.approx(95)  # gapped through 99 stop -> filled at open


@pytest.mark.parametrize("name", ["ema_crossover", "rsi_reversion", "opening_range"])
def test_builtin_strategies_run(name):
    import math
    bars = []
    for d in range(10):
        day = datetime(2026, 1, 5) + timedelta(days=d)
        if day.weekday() >= 5:
            continue
        bars += day_bars("ABC", day, [100 + 5 * math.sin((d * 25 + i) / 4) for i in range(25)])
    r = run_on_bars({"ABC": bars}, name, {}, "15m", Settings())
    assert r.metrics["trading_days"] > 0
    assert all(t.exit_ts >= t.entry_ts for t in r.trades)
