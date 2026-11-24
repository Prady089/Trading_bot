"""Scanner: downloads NIFTY 50 + index candles, retrains every model variant, ranks stocks.

Champion / challenger:
- Every model in MODEL_SPECS is retrained each refresh and scored by walk-forward testing.
- Every model's forecasts are written to a log and scored one hour later against what the stock
  actually did. That live record is the only honest measure of whether a model works.
- The CHAMPION's forecasts drive the app (top picks, Auto bot). A challenger replaces it only after
  beating it on live forecasts over the same candles (see `maybe_promote`), or by manual choice.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta
from typing import Callable

import numpy as np

from app.config import IST
from app.data.feed import INTERVAL_MINUTES, DataFeed
from app.predict.model import (BAR_MINUTES, DEFAULT_CHAMPION, HORIZON_BARS, available_models, build_context,
                               build_features, make_model)

log = logging.getLogger("scanner")

INDICES = ["NIFTY", "BANKNIFTY"]          # forecast and scored, tradable as futures
CONTEXT = ["NIFTY", "BANKNIFTY", "INDIAVIX"]
PROMOTE_MIN_CANDLES = 150                 # ~1.5 weeks of live forecasts before a model can be promoted
PROMOTE_IC_MARGIN = 0.02                  # challenger must beat the champion's live IC by this much
LEADERBOARD_DAYS = 15


class Scanner:
    def __init__(self, feed: DataFeed, universe: list[str], interval: str = "15m", period: str = "60d",
                 store=None, clock: Callable[[], datetime] = lambda: datetime.now(IST)):
        self.feed, self.universe, self.interval, self.period = feed, universe, interval, period
        self.store, self.clock = store, clock
        self.on_event: Callable[[str, str], None] = lambda msg, level="info": None
        self.result: dict | None = None
        self.error: str | None = None
        self._lock = threading.Lock()
        self._refreshing = threading.Event()

    @property
    def refreshing(self) -> bool:
        return self._refreshing.is_set()

    @property
    def champion(self) -> str:
        models = available_models()
        name = self.store.kv_get("champion_model", DEFAULT_CHAMPION) if self.store is not None else DEFAULT_CHAMPION
        return name if name in models else next(iter(models))

    def set_champion(self, name: str, reason: str = "manual choice") -> None:
        if name not in available_models():
            raise ValueError(f"Unknown model {name}. Choose from {list(available_models())}")
        old = self.champion
        if self.store is not None:
            self.store.kv_set("champion_model", name)
        if name != old:
            self.on_event(f"Model champion: {old} -> {name} ({reason})", "info")

    def refresh(self) -> dict | None:
        if not self._lock.acquire(blocking=False):
            return self.result  # a refresh is already running
        self._refreshing.set()
        try:
            self._refresh()
            self.error = None
        except Exception as e:  # noqa: BLE001
            log.exception("scanner refresh failed")
            self.error = str(e)
        finally:
            self._refreshing.clear()
            self._lock.release()
        return self.result

    def _refresh(self) -> None:
        now = self.clock()
        step = timedelta(minutes=INTERVAL_MINUTES[self.interval])
        data = self.feed.history_many(self.universe + CONTEXT, self.interval, self.period)
        # Drop the candle still forming: its volume/range are partial, unlike every candle the
        # models trained on, so predicting from it skews the features.
        data = {s: [b for b in bars if b.ts + step <= now] for s, bars in data.items()}
        ctx = build_context(data.get("NIFTY", []), data.get("BANKNIFTY"), data.get("INDIAVIX"))
        frames = {s: build_features(data[s.upper()], ctx) for s in self.universe if len(data.get(s.upper(), [])) > 40}
        index_frames = {s: build_features(data[s], ctx) for s in INDICES if len(data.get(s, [])) > 40}
        if self.store is not None:
            self._resolve({**frames, **index_frames}, now)

        champion = self.champion
        runs: dict[str, dict] = {}
        for name in available_models():
            try:
                m = make_model(name)
                stats = m.fit(frames)
                runs[name] = {"stats": stats, "stocks": m.predict_latest(frames),
                              "index": m.predict_latest(index_frames) if index_frames else []}
            except Exception as e:  # noqa: BLE001 - one broken challenger must not take down the app
                log.exception("model %s failed", name)
                if name == champion:
                    raise
                runs[name] = {"error": str(e)}
        live = runs[champion]
        data_as_of = max((s["as_of"] for s in live["stocks"]), default=None)
        self.result = {
            "generated_at": datetime.now(IST).isoformat(timespec="seconds"),
            "data_as_of": data_as_of,
            "universe_size": len(self.universe),
            "stocks_scored": len(live["stocks"]),
            "missing": sorted(s for s in self.universe if s not in frames),
            "context_available": ctx is not None,
            "champion": champion,
            "model": live["stats"],
            "models": {k: v.get("stats", {"error": v.get("error")}) for k, v in runs.items()},
            "stocks": live["stocks"],
            "index": {i["symbol"]: {**i, "by_model": {k: next((x["predicted_return_pct"] for x in v.get("index", [])
                                                                if x["symbol"] == i["symbol"]), None)
                                                      for k, v in runs.items()}}
                      for i in live["index"]},
        }
        if self.store is not None:
            for name, r in runs.items():
                if "stats" in r:
                    self._log(name, r, data_as_of, now)
            self.maybe_promote()

    # ---------- live accuracy log ----------
    def _log(self, name: str, run: dict, data_as_of: str | None, now: datetime) -> None:
        self.store.add_model_run(run["stats"], data_as_of)
        today = now.date().isoformat()
        rows = [(s["as_of"], s["symbol"], name, i + 1, s["last_price"], s["predicted_return_pct"],
                 run["stats"]["trained_at"]) for i, s in enumerate(x for x in run["stocks"] if x["as_of"][:10] == today)]
        rows += [(s["as_of"], s["symbol"], name, 0, s["last_price"], s["predicted_return_pct"],
                  run["stats"]["trained_at"]) for s in run["index"] if s["as_of"][:10] == today]
        self.store.add_predictions(rows)

    def _resolve(self, frames: dict, now: datetime) -> None:
        """Score open forecasts: actual return = close 1 hour later / close at forecast - 1."""
        horizon = timedelta(minutes=HORIZON_BARS * BAR_MINUTES)
        closes = {s: dict(zip((t.isoformat() for t in f["ts"]), f["close"])) for s, f in frames.items()}
        done = []
        for r in self.store.unresolved_predictions():
            ts = datetime.fromisoformat(r["bar_ts"])
            sym_closes = closes.get(r["symbol"], {})
            later = sym_closes.get((ts + horizon).isoformat())
            if later is not None:
                base = sym_closes.get(r["bar_ts"], r["price"])  # exact close; stored price is rounded
                done.append((round((later / base - 1) * 100, 4), r["bar_ts"], r["symbol"]))
            elif ts.date() < now.date():
                done.append((None, r["bar_ts"], r["symbol"]))  # day ended before the hour was up
        self.store.resolve_predictions(done)

    def _since(self, days: int | None) -> str | None:
        return (self.clock() - timedelta(days=days)).date().isoformat() if days else None

    def leaderboard(self, days: int = LEADERBOARD_DAYS) -> list[dict]:
        """Live score of every model, on the candles that ALL models forecast (a fair comparison)."""
        if self.store is None:
            return []
        models = list(available_models())
        rows = {m: [r for r in self.store.resolved_predictions(self._since(days), m) if r["rank"] > 0] for m in models}
        common = set.intersection(*({r["bar_ts"] for r in rs} for rs in rows.values())) if rows else set()
        latest = {m: (self.store.model_runs(1, m) or [{}])[-1] for m in models}
        champ = self.champion
        out = []
        for m in models:
            kind_desc = available_models()[m][2]
            out.append({
                "model": m, "description": kind_desc, "champion": m == champ,
                "live": _score([r for r in rows[m] if r["bar_ts"] in common]),
                "walk_forward": {k: latest[m].get(k) for k in (
                    "direction_accuracy_pct", "always_up_pct", "information_coefficient", "top5_avg_return_pct",
                    "market_avg_return_pct", "fold_ic", "trained_at")},
            })
        return out

    def maybe_promote(self) -> str | None:
        """Promote a challenger that beats the champion on live forecasts over the same candles."""
        board = {r["model"]: r["live"] for r in self.leaderboard()}
        champ = self.champion
        c = board.get(champ)
        if not c or c["candles"] < PROMOTE_MIN_CANDLES or c["information_coefficient"] is None:
            return None
        best = None
        for m, s in board.items():
            if m == champ or s["information_coefficient"] is None or s["candles"] < PROMOTE_MIN_CANDLES:
                continue
            beats = (s["information_coefficient"] >= c["information_coefficient"] + PROMOTE_IC_MARGIN
                     and (s["top5_avg_return_pct"] or 0) >= (c["top5_avg_return_pct"] or 0))
            if beats and (best is None or s["information_coefficient"] > board[best]["information_coefficient"]):
                best = m
        if best:
            self.set_champion(best, f"live IC {board[best]['information_coefficient']} vs "
                                    f"{c['information_coefficient']} over {board[best]['candles']} candles")
        return best

    def live_accuracy(self, days: int | None = None, model: str | None = None) -> dict:
        """How a model's real-time forecasts turned out (default: the champion)."""
        if self.store is None:
            return {}
        model = model or self.champion
        rows = self.store.resolved_predictions(self._since(days), model)
        stock_rows = [r for r in rows if r["rank"] > 0]
        out = {"model": model, "counts": self.store.prediction_counts(model), **_score(stock_rows)}
        by_day: dict[str, list[dict]] = {}
        for r in stock_rows:
            by_day.setdefault(r["bar_ts"][:10], []).append(r)
        out["by_day"] = [{"day": d, **_score(rs)} for d, rs in sorted(by_day.items())]
        out["recent_top_picks"] = [
            {k: r[k] for k in ("bar_ts", "symbol", "rank", "price", "predicted_return_pct", "actual_return_pct")}
            for r in reversed(stock_rows) if r["rank"] <= 5][:25]
        out["index"] = {s: _direction([r for r in rows if r["symbol"] == s]) for s in INDICES}
        return out

    def refresh_async(self) -> None:
        if not self.refreshing:
            threading.Thread(target=self.refresh, name="scanner", daemon=True).start()

    def top(self, n: int) -> list[dict]:
        return (self.result or {}).get("stocks", [])[:n]


def _direction(rows: list[dict]) -> dict:
    p = np.array([r["predicted_return_pct"] for r in rows])
    a = np.array([r["actual_return_pct"] for r in rows])
    nz = (a != 0) & (p != 0)
    return {"forecasts": len(rows),
            "direction_accuracy_pct": round(float((np.sign(p[nz]) == np.sign(a[nz])).mean() * 100), 1) if nz.any() else None}


def _score(rows: list[dict]) -> dict:
    if not rows:
        return {"forecasts": 0, "candles": 0, "direction_accuracy_pct": None, "always_up_pct": None,
                "information_coefficient": None, "top5_avg_return_pct": None, "top5_hit_rate_pct": None,
                "market_avg_return_pct": None}
    p = np.array([r["predicted_return_pct"] for r in rows])
    a = np.array([r["actual_return_pct"] for r in rows])
    nz = a != 0
    top = np.array([0 < r["rank"] <= 5 for r in rows])
    return {
        "forecasts": len(rows),
        "candles": len({r["bar_ts"] for r in rows}),
        "direction_accuracy_pct": round(float((np.sign(p[nz]) == np.sign(a[nz])).mean() * 100), 1) if nz.any() else None,
        "always_up_pct": round(float((a[nz] > 0).mean() * 100), 1) if nz.any() else None,
        "information_coefficient": round(float(np.corrcoef(p, a)[0, 1]), 3)
        if len(rows) > 2 and p.std() > 0 and a.std() > 0 else None,
        "top5_avg_return_pct": round(float(a[top].mean()), 3) if top.any() else None,
        "top5_hit_rate_pct": round(float((a[top] > 0).mean() * 100), 1) if top.any() else None,
        "market_avg_return_pct": round(float(a.mean()), 3),
    }
