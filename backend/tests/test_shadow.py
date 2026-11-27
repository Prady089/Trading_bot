"""Shadow strategy accounts: replay since the start date, warm-up never trades. Offline."""
import math

import pytest
from datetime import date, datetime, timedelta

from app.config import IST, Settings
from app.live.shadow import SPECS, ShadowRunner
from app.storage.db import Store
from tests.test_engine import day_bars
from tests.test_service import FakeFeed


def wavy(sym, days):
    bars = []
    for d in range(days):
        day = datetime(2026, 1, 5) + timedelta(days=d)
        if day.weekday() < 5:
            bars += day_bars(sym, day, [100 + 4 * math.sin((d * 25 + i) / 3) for i in range(25)])
    return bars


def test_replay_trades_only_after_start(tmp_path):
    feed = FakeFeed()
    feed.bars = {"AAA": wavy("AAA", 14), "BBB": wavy("BBB", 14)}
    s = Settings(db_path=str(tmp_path / "s.db"))
    r = ShadowRunner(feed, Store(s.db_path), s, universe=["AAA", "BBB"])
    r.starts = {sp.id: date(2026, 1, 12) for sp in SPECS}
    r.clock = lambda: datetime(2026, 1, 20, 18, 0, tzinfo=IST)
    out = r.refresh()
    st = out["supertrend_15m"]
    assert st["metrics"]["num_trades"] > 0
    assert all(t["entry_ts"] >= "2026-01-12" for t in st["trades"])     # warm-up days never trade
    if not st["positions"]:
        assert st["equity"] == pytest.approx(st["initial_capital"] + st["realized_pnl"], abs=0.1)
    # deterministic: a second replay (e.g. after a restart) gives identical results
    again = r.refresh()["supertrend_15m"]
    assert again["realized_pnl"] == st["realized_pnl"] and again["metrics"]["num_trades"] == st["metrics"]["num_trades"]
    assert {a["id"] for a in r.summary()["accounts"]} == {sp.id for sp in SPECS}


def test_start_date_persists(tmp_path):
    s = Settings(db_path=str(tmp_path / "s.db"))
    store = Store(s.db_path)
    store.kv_set("shadow_start", {"supertrend_15m": "2026-01-01"})
    r = ShadowRunner(FakeFeed(), store, s)
    assert r.starts["supertrend_15m"] == date(2026, 1, 1)                # existing account keeps its start
    assert all(sp.id in store.kv_get("shadow_start") for sp in SPECS)    # new accounts get registered
