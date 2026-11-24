"""Paper account: manual orders, auto mode, stop/target/time exits, persistence. Offline."""
from datetime import datetime, timedelta

import numpy as np
import pytest

from app.config import IST, Settings
from app.data.feed import DataFeed
from app.live.service import TradingService
from app.models import Bar
from app.predict.model import Predictor, build_features
from app.storage.db import Store

DAY = datetime(2026, 1, 5, tzinfo=IST)  # a Monday


def minute_bars(sym: str, prices: list[float], start: datetime) -> list[Bar]:
    return [Bar(sym, start + timedelta(minutes=i), p, p * 1.0005, p * 0.9995, p, 1000)
            for i, p in enumerate(prices)]


class FakeFeed(DataFeed):
    def __init__(self):
        self.bars: dict[str, list[Bar]] = {}

    trading = True   # False simulates an NSE holiday: no candles for today

    def history(self, symbol, interval, period):
        sym = symbol.upper()
        if sym == "NIFTY" and sym not in self.bars:   # the service's holiday probe
            return [Bar("NIFTY", DAY.replace(hour=9, minute=15), 1, 1, 1, 1, 0)] if self.trading else []
        return self.bars.get(sym, [])

    def latest_completed(self, symbol, interval, now):
        return self.history(symbol, interval, "")


class FakeScanner:
    def __init__(self, stocks):
        self.result = {"stocks": stocks}
        self.refreshing = False

    def refresh(self):
        return self.result

    def refresh_async(self):
        pass

    def top(self, n):
        return self.result["stocks"][:n]


@pytest.fixture
def setup(tmp_path):
    s = Settings(initial_capital=100_000, slippage_bps=0, db_path=str(tmp_path / "t.db"))
    feed, store = FakeFeed(), Store(s.db_path)
    scanner = FakeScanner([
        {"symbol": "AAA", "last_price": 100.0, "predicted_return_pct": 0.3},
        {"symbol": "BBB", "last_price": 200.0, "predicted_return_pct": 0.2},
        {"symbol": "CCC", "last_price": 50.0, "predicted_return_pct": 0.01},  # below minimum
    ])
    svc = TradingService(feed, store, scanner, s)
    return s, feed, store, svc


def test_auto_enters_top_picks_and_exits_on_target_and_time(setup, monkeypatch):
    s, feed, store, svc = setup
    t0 = DAY.replace(hour=10, minute=0)
    feed.bars["AAA"] = minute_bars("AAA", [100.0], t0 - timedelta(minutes=1))
    feed.bars["BBB"] = minute_bars("BBB", [200.0], t0 - timedelta(minutes=1))
    svc.update_settings({"auto_enabled": True, "amount_per_trade": 10_000, "stop_loss_pct": 1,
                         "target_pct": 1, "max_positions": 3, "max_hold_minutes": 30,
                         "min_predicted_return_pct": 0.05})
    entered = svc.auto_enter(t0)
    assert entered == ["AAA", "BBB"]               # CCC skipped: prediction below minimum
    assert svc.broker.positions["AAA"].qty == 100  # Rs 10,000 / Rs 100

    # AAA rallies through its 1% target; BBB drifts flat until the 30-minute time exit.
    feed.bars["AAA"] = minute_bars("AAA", [100, 100.4, 101.5, 101.5], t0 + timedelta(minutes=1))
    feed.bars["BBB"] = minute_bars("BBB", [200.0] * 40, t0 + timedelta(minutes=1))
    svc.monitor(t0 + timedelta(minutes=45))

    rows = {t["symbol"]: t for t in svc.trades()}
    assert rows["AAA"]["exit_reason"] == "take-profit" and rows["AAA"]["net_pnl"] > 0
    assert rows["BBB"]["exit_reason"].startswith("time exit")
    assert rows["AAA"]["source"] == "auto"
    assert rows["AAA"]["return_pct"] == pytest.approx(rows["AAA"]["net_pnl"] / (100 * 100) * 100, abs=0.01)
    assert not svc.broker.positions


def test_manual_buy_stop_loss_and_persistence(setup, monkeypatch):
    s, feed, store, svc = setup
    t0 = DAY.replace(hour=11, minute=0)
    svc.clock = lambda: t0
    feed.bars["AAA"] = minute_bars("AAA", [100.0], t0 - timedelta(minutes=1))
    svc.manual_order("AAA", "BUY", amount=5_000, qty=None, stop_loss_pct=2, target_pct=None)
    assert svc.broker.positions["AAA"].source == "manual"

    # Restart: a new service instance restores the open position from the database.
    svc2 = TradingService(feed, store, svc.scanner, s)
    assert "AAA" in svc2.broker.positions

    feed.bars["AAA"] = minute_bars("AAA", [99, 97, 96], t0 + timedelta(minutes=1))
    svc2.monitor(t0 + timedelta(minutes=10))
    (t,) = svc2.trades()
    assert t["exit_reason"] == "stop-loss" and t["net_pnl"] < 0


def test_square_off_at_1515(setup):
    s, feed, store, svc = setup
    t0 = DAY.replace(hour=15, minute=0)
    feed.bars["AAA"] = minute_bars("AAA", [100.0], t0 - timedelta(minutes=1))
    svc.update_settings({"auto_enabled": True, "max_hold_minutes": 600, "target_pct": 50, "stop_loss_pct": 50})
    svc.auto_enter(t0 - timedelta(minutes=5))
    feed.bars["AAA"] = minute_bars("AAA", [100.0] * 20, t0)
    svc.monitor(t0 + timedelta(minutes=20))
    assert svc.trades()[0]["exit_reason"] == "intraday square-off"


def test_predictor_learns_a_real_signal():
    """If next-hour return genuinely depends on a feature, the model should find it."""
    rng = np.random.default_rng(0)
    frames = {}
    for k in range(8):
        bars, p = [], 100.0
        for d in range(25):
            day = DAY + timedelta(days=d)
            for i in range(25):
                # mean-reverting price: a fall in the last bar predicts a rise later
                p *= 1 + rng.normal(0, 0.002)
                ts = day.replace(hour=9, minute=15) + timedelta(minutes=15 * i)
                bars.append(Bar(f"S{k}", ts, p, p * 1.001, p * 0.999, p, 1000 + rng.integers(0, 500)))
                p = 100 + (p - 100) * 0.7  # strong pull back to 100
        frames[f"S{k}"] = build_features(bars)
    stats = Predictor().fit(frames)
    assert stats["direction_accuracy_pct"] > 55
    assert stats["information_coefficient"] > 0.1
