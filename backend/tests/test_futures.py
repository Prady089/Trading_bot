"""Index futures in the paper account: lots, margin, P&L, charges, stops. Offline."""
from datetime import timedelta

import pytest

from app.broker.costs import IndianFuturesCosts
from app.config import FUTURES, FUTURES_MARGIN_PCT, Settings
from app.live.service import TradingService
from app.models import Side
from app.storage.db import Store
from tests.test_service import DAY, FakeFeed, FakeScanner, minute_bars

LOT = FUTURES["NIFTY-FUT"]["lot_size"]


def make(tmp_path, capital):
    s = Settings(initial_capital=capital, slippage_bps=0, db_path=str(tmp_path / "f.db"))
    feed = FakeFeed()
    scanner = FakeScanner([])
    scanner.result["index"] = {"NIFTY": {"symbol": "NIFTY", "last_price": 25_000.0, "predicted_return_pct": 0.1}}
    return feed, TradingService(feed, Store(s.db_path), scanner, s)


def test_buy_one_lot_uses_margin_not_full_value(tmp_path):
    feed, svc = make(tmp_path, 500_000)
    t0 = DAY.replace(hour=11)
    svc.clock = lambda: t0
    feed.bars["NIFTY-FUT"] = minute_bars("NIFTY-FUT", [25_000.0], t0 - timedelta(minutes=1))
    r = svc.manual_order("NIFTY-FUT", "BUY", None, None, 0.5, 1.0, lots=1)
    assert r["position"]["qty"] == LOT
    assert r["position"]["predicted_return_pct"] == 0.1      # the index forecast is stored on the trade

    pf = svc.portfolio()
    (pos,) = pf["positions"]
    margin = LOT * 25_000 * FUTURES_MARGIN_PCT / 100
    assert pos["instrument"] == "FUT" and pos["lots"] == 1
    assert pos["invested"] == pytest.approx(margin)          # only the margin is tied up
    assert pf["equity"] == pytest.approx(500_000 - pos["entry_charges"], abs=0.01)
    assert pf["cash"] == pytest.approx(500_000 - pos["entry_charges"] - margin, abs=0.01)


def test_target_hit_pnl_and_charges(tmp_path):
    feed, svc = make(tmp_path, 500_000)
    t0 = DAY.replace(hour=11)
    svc.clock = lambda: t0
    feed.bars["NIFTY-FUT"] = minute_bars("NIFTY-FUT", [25_000.0], t0 - timedelta(minutes=1))
    svc.manual_order("NIFTY-FUT", "BUY", None, None, 0.5, 1.0, lots=1)
    # Index rallies: the 2nd candle's high (25,252.6) crosses the 1% target (25,250), which fills.
    feed.bars["NIFTY-FUT"] = minute_bars("NIFTY-FUT", [25_100, 25_240, 25_240], t0 + timedelta(minutes=1))
    svc.monitor(t0 + timedelta(minutes=10))
    (t,) = svc.trades()
    assert t["exit_reason"] == "take-profit"
    assert t["gross_pnl"] == pytest.approx(250 * LOT)       # 250 points x lot size
    c = IndianFuturesCosts()
    expected = c.charges(Side.BUY, 25_000, LOT) + c.charges(Side.SELL, 25_250, LOT)
    assert t["charges"] == pytest.approx(expected, abs=0.02)
    assert t["model_correct"] is True


def test_short_and_not_enough_margin(tmp_path):
    feed, svc = make(tmp_path, 100_000)        # one NIFTY lot needs ~Rs 2 lakh margin
    t0 = DAY.replace(hour=11)
    svc.clock = lambda: t0
    feed.bars["NIFTY-FUT"] = minute_bars("NIFTY-FUT", [25_000.0], t0 - timedelta(minutes=1))
    with pytest.raises(ValueError, match="Not enough margin"):
        svc.manual_order("NIFTY-FUT", "SELL", None, None, 0.5, 1.0, lots=1)

    feed, svc = make(tmp_path / "b", 500_000)
    svc.clock = lambda: t0
    feed.bars["NIFTY-FUT"] = minute_bars("NIFTY-FUT", [25_000.0], t0 - timedelta(minutes=1))
    svc.manual_order("NIFTY-FUT", "SELL", None, None, 0.5, 1.0, lots=1)
    feed.bars["NIFTY-FUT"] = minute_bars("NIFTY-FUT", [25_050, 25_200], t0 + timedelta(minutes=1))
    svc.monitor(t0 + timedelta(minutes=5))
    (t,) = svc.trades()
    assert t["exit_reason"] == "stop-loss" and t["net_pnl"] < -125 * LOT * 0.99


def test_futures_quote_endpoint_data(tmp_path):
    _, svc = make(tmp_path, 500_000)
    q = {f["symbol"]: f for f in svc.futures()}
    n = q["NIFTY-FUT"]
    assert n["lot_value"] == 25_000 * LOT
    assert n["affordable_lots"] == int(500_000 // (25_000 * LOT * FUTURES_MARGIN_PCT / 100))
    assert n["predicted_profit_per_lot"] == pytest.approx(25_000 * LOT * 0.001)


def test_auto_futures_follows_index_forecast(tmp_path):
    feed, svc = make(tmp_path, 500_000)
    t0 = DAY.replace(hour=11)
    svc.clock = lambda: t0
    svc.scanner.result["index"]["BANKNIFTY"] = {"symbol": "BANKNIFTY", "last_price": 56_000.0,
                                                "predicted_return_pct": -0.07}
    svc.scanner.result["index"]["NIFTY"]["predicted_return_pct"] = 0.03   # below the 0.06% minimum
    feed.bars["NIFTY-FUT"] = minute_bars("NIFTY-FUT", [25_000.0], t0 - timedelta(minutes=1))
    feed.bars["BANKNIFTY-FUT"] = minute_bars("BANKNIFTY-FUT", [56_000.0], t0 - timedelta(minutes=1))

    assert svc.auto_enter(t0) == []                         # futures auto is off by default
    svc.update_settings({"futures_auto_enabled": True})
    assert svc.auto_enter(t0) == ["BANKNIFTY-FUT"]          # only the forecast that clears the bar
    (pos,) = svc.portfolio()["positions"]
    assert pos["symbol"] == "BANKNIFTY-FUT" and pos["side"] == "SHORT" and pos["source"] == "auto"
    assert pos["lots"] == 1 and pos["predicted_return_pct"] == -0.07
    assert svc.auto_enter(t0) == []                         # never doubles up on the same index


def test_auto_futures_skips_without_margin(tmp_path):
    feed, svc = make(tmp_path, 100_000)
    t0 = DAY.replace(hour=11)
    svc.clock = lambda: t0
    feed.bars["NIFTY-FUT"] = minute_bars("NIFTY-FUT", [25_000.0], t0 - timedelta(minutes=1))
    svc.update_settings({"futures_auto_enabled": True})
    assert svc.auto_enter(t0) == []
    assert svc.portfolio()["positions"] == []
