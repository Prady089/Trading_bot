"""Live forecast log: forecasts are stored, scored 1h later, and forming candles are ignored."""
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from app.config import IST
from app.data.feed import DataFeed
from app.live.service import with_return
from app.models import Bar
from app.predict.scanner import Scanner
from app.storage.db import Store


class Feed15(DataFeed):
    """Random-walk 15m candles for several symbols over several sessions."""
    SYMS = ("AAA", "BBB", "CCC", "DDD", "EEE", "FFF")

    def __init__(self, days=6, seed=1):
        rng = np.random.default_rng(seed)
        self.bars = {}
        start = datetime(2026, 1, 5, 9, 15, tzinfo=IST)  # Monday
        for sym in self.SYMS:
            p, out = 100.0, []
            for d in range(days):
                day = start + timedelta(days=d)
                for i in range(25):  # 09:15 .. 15:15
                    o = p
                    p *= 1 + rng.normal(0, 0.003)
                    out.append(Bar(sym, day + timedelta(minutes=15 * i), o, max(o, p) * 1.001,
                                   min(o, p) * 0.999, p, 1000 + rng.integers(0, 500)))
            self.bars[sym] = out

    def history(self, symbol, interval, period):
        return self.bars.get(symbol, [])

    def latest_completed(self, symbol, interval, now):
        return self.bars.get(symbol, [])


def test_forecasts_logged_and_scored(tmp_path):
    store, feed = Store(str(tmp_path / "a.db")), Feed15()
    now = {"t": datetime(2026, 1, 10, 11, 1, tzinfo=IST)}  # last day (Sat in data; fine for the test)
    sc = Scanner(feed, list(Feed15.SYMS), store=store, clock=lambda: now["t"])

    sc.refresh()
    assert sc.error is None
    # 10:45 is the last completed candle at 11:01 (11:00 is still forming and must be ignored).
    assert sc.result["data_as_of"].startswith("2026-01-10T10:45")
    assert store.prediction_counts("ridge_base") == {"total": 6, "resolved": 0, "scans": 1}
    n_models = len(sc.result["models"])
    assert n_models >= 2 and store.prediction_counts()["total"] == 6 * n_models

    now["t"] = datetime(2026, 1, 10, 12, 1, tzinfo=IST)  # 11:45 candle (= 10:45 + 1h) has closed
    sc.refresh()
    acc = sc.live_accuracy()
    assert acc["forecasts"] == 6 and acc["candles"] == 1
    r = next(x for x in store.resolved_predictions() if x["symbol"] == "AAA")
    c = {b.ts: b.close for b in feed.bars["AAA"]}
    t0 = datetime(2026, 1, 10, 10, 45, tzinfo=IST)
    assert abs(r["actual_return_pct"] - (c[t0 + timedelta(hours=1)] / c[t0] - 1) * 100) < 1e-3
    assert len(store.model_runs()) == 2 * n_models
    assert {r["model"] for r in sc.leaderboard()} == set(sc.result["models"])


def test_trade_model_correct():
    base = {"entry_price": 100.0, "qty": 10, "net_pnl": 5.0, "exit_price": 101.0}
    assert with_return({**base, "predicted_return_pct": 0.2})["model_correct"] is True
    assert with_return({**base, "predicted_return_pct": -0.2})["model_correct"] is False
    assert with_return({**base, "predicted_return_pct": None})["model_correct"] is None


def test_real_scanner_has_service_interface():
    """The live service calls these on the real Scanner; keep them in sync with FakeScanner."""
    for name in ("refresh", "refresh_async", "top", "refreshing", "result", "live_accuracy"):
        assert hasattr(Scanner(Feed15(days=1), ["AAA"]), name), name


def test_context_features_and_index_forecasts(tmp_path):
    """With NIFTY/BANKNIFTY/VIX candles present, context features are filled and indices get forecasts."""
    feed = Feed15()
    for sym, base in (("NIFTY", "AAA"), ("BANKNIFTY", "BBB"), ("INDIAVIX", "CCC")):
        feed.bars[sym] = [Bar(sym, b.ts, b.open, b.high, b.low, b.close, 0) for b in feed.bars[base]]
    store = Store(str(tmp_path / "c.db"))
    sc = Scanner(feed, list(Feed15.SYMS), store=store, clock=lambda: datetime(2026, 1, 10, 11, 1, tzinfo=IST))
    sc.refresh()
    assert sc.error is None and sc.result["context_available"]
    assert set(sc.result["index"]) == {"NIFTY", "BANKNIFTY"}
    assert store.prediction_counts("ridge_ctx")["total"] == 6 + 2  # 6 stocks + 2 indices


def test_walk_forward_has_purge_gap():
    """Walk-forward runs several folds and never trains on targets that overlap a test window."""
    from app.predict import model as M
    feed = Feed15(days=8)
    rows = pd.concat([M.build_features(feed.bars[s]).assign(symbol=s) for s in Feed15.SYMS])
    rows = rows.dropna(subset=M.BASE_FEATURES + ["target"]).sort_values("ts")
    fits = []

    class Spy(M.Predictor):
        def _fit_xy(self, X, y):
            fits.append(len(y))
            super()._fit_xy(X, y)
    wf = M.walk_forward(rows, Spy("ridge", M.BASE_FEATURES))
    assert wf["folds"] >= 3 and wf["always_up_pct"] is not None
    # Each fold trains on strictly more history than the one before (expanding window).
    assert len(fits) == wf["folds"] and fits == sorted(fits) and len(set(fits)) == len(fits)
    # Purge gap: the last training candle is >= 1h before the test window, so its target can't peek in.
    for last_train, test_start in wf["_fold_bounds"]:
        assert test_start - last_train >= pd.Timedelta(hours=1)


def test_champion_switch(tmp_path):
    store = Store(str(tmp_path / "d.db"))
    sc = Scanner(Feed15(), list(Feed15.SYMS), store=store)
    assert sc.champion == "ridge_base"
    sc.set_champion("ridge_ctx")
    assert sc.champion == "ridge_ctx" and store.kv_get("champion_model") == "ridge_ctx"
    import pytest
    with pytest.raises(ValueError):
        sc.set_champion("nope")
