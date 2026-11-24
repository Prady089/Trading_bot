"""Short-term return predictors.

For every stock and every 15-minute candle we compute features using ONLY data up to
that candle, and learn to predict the return over the next hour (4 candles, same day).

Several model variants compete (see MODEL_SPECS):
- ridge_base: regularised linear model on the stock's own price/volume features (the original).
- ridge_ctx:  same, plus market context (NIFTY / BANKNIFTY trend, India VIX, strength vs the index).
- lgbm_ctx:   LightGBM gradient-boosted trees on the same features; can learn non-linear effects
              such as "momentum works, except when VIX is high".

Every model is scored by WALK-FORWARD testing: the most recent 25% of candles is split into 5
consecutive windows; for each window the model is trained only on data that ended at least one
hour before the window starts (a purge gap, so no training target overlaps the test period),
then tested on that window. That is how it would have performed if run live over those weeks.
"""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

from app.config import IST
from app.models import Bar
from app.strategies.indicators import atr, ema, rsi

HORIZON_BARS = 4          # 4 x 15m = 1 hour
BAR_MINUTES = 15
BASE_FEATURES = ["ret_1", "ret_4", "ret_16", "ret_day", "rsi", "ema_gap",
                 "vol_ratio", "range_pos", "atr_pct", "tod"]
CTX_FEATURES = ["mkt_ret_1", "mkt_ret_4", "mkt_ret_day", "bank_ret_4",
                "vix", "vix_chg_4", "rel_ret_4", "rel_ret_day"]
FEATURES = BASE_FEATURES  # backwards-compatible name
RIDGE_LAMBDA = 10.0
TARGET_CLIP = 0.03        # winsorise targets at +/-3% so single spikes don't dominate
WF_FOLDS = 5
WF_TEST_FRAC = 0.25

MODEL_SPECS: dict[str, tuple[str, list[str], str]] = {
    "ridge_base": ("ridge", BASE_FEATURES, "Linear model, stock's own price action only (original)"),
    "ridge_ctx": ("ridge", BASE_FEATURES + CTX_FEATURES, "Linear model + market context (NIFTY, BANKNIFTY, VIX)"),
    "lgbm_ctx": ("lgbm", BASE_FEATURES + CTX_FEATURES, "LightGBM trees + market context"),
}
DEFAULT_CHAMPION = "ridge_base"


def lgbm_available() -> bool:
    try:
        import lightgbm  # noqa: F401
        return True
    except Exception:  # noqa: BLE001 - ImportError, or OSError when a system lib (libgomp) is missing
        return False


def available_models() -> dict[str, tuple[str, list[str], str]]:
    ok = lgbm_available()
    return {k: v for k, v in MODEL_SPECS.items() if v[0] != "lgbm" or ok}


# ---------- features ----------
def _frame(bars: list[Bar]) -> pd.DataFrame:
    return pd.DataFrame({
        "ts": [b.ts for b in bars], "open": [b.open for b in bars], "high": [b.high for b in bars],
        "low": [b.low for b in bars], "close": [b.close for b in bars], "volume": [b.volume for b in bars],
    })


def build_context(nifty: list[Bar], bank: list[Bar] | None = None, vix: list[Bar] | None = None) -> pd.DataFrame | None:
    """Market-wide features per 15m candle, joined onto every stock by timestamp."""
    if not nifty:
        return None
    n = _frame(nifty)
    day = pd.Series([t.date() for t in n["ts"]])
    ctx = pd.DataFrame({"ts": n["ts"]})
    c = n["close"]
    ctx["mkt_ret_1"] = c.pct_change(1)
    ctx["mkt_ret_4"] = c.pct_change(4)
    ctx["mkt_ret_day"] = c / n.groupby(day)["open"].transform("first") - 1
    if bank:
        b = _frame(bank).set_index("ts")["close"]
        ctx["bank_ret_4"] = ctx["ts"].map(b.pct_change(4))
    if vix:
        v = _frame(vix).set_index("ts")["close"]
        ctx["vix"] = ctx["ts"].map(np.log(v / 15.0))          # 0 = VIX of 15 (calm); +0.4 = VIX ~22
        ctx["vix_chg_4"] = ctx["ts"].map(v.pct_change(4))
    return ctx.replace([np.inf, -np.inf], np.nan)


def build_features(bars: list[Bar], ctx: pd.DataFrame | None = None) -> pd.DataFrame:
    df = _frame(bars)
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
    day = pd.Series([t.date() for t in df["ts"]])
    df["day"] = day
    df["ret_1"] = c.pct_change(1)
    df["ret_4"] = c.pct_change(4)
    df["ret_16"] = c.pct_change(16)
    df["ret_day"] = c / df.groupby("day")["open"].transform("first") - 1
    df["rsi"] = (rsi(c.to_numpy(), 14) - 50) / 50
    df["ema_gap"] = ema(c.to_numpy(), 9) / ema(c.to_numpy(), 21) - 1
    df["vol_ratio"] = np.log1p(v) - np.log1p(v.rolling(20, min_periods=5).mean())
    hh, ll = h.rolling(20, min_periods=5).max(), l.rolling(20, min_periods=5).min()
    df["range_pos"] = ((c - ll) / (hh - ll).replace(0, np.nan)) - 0.5
    df["atr_pct"] = atr(h.to_numpy(), l.to_numpy(), c.to_numpy(), 14) / c
    df["tod"] = [((t.hour * 60 + t.minute) - (9 * 60 + 15)) / 375 for t in df["ts"]]

    # Market context. Missing context (e.g. index feed down) is filled with 0 = "neutral".
    if ctx is not None:
        df = df.merge(ctx, on="ts", how="left")
    for col in ("mkt_ret_1", "mkt_ret_4", "mkt_ret_day", "bank_ret_4", "vix", "vix_chg_4"):
        if col not in df:
            df[col] = 0.0
        df[col] = df[col].fillna(0.0)
    df["rel_ret_4"] = df["ret_4"] - df["mkt_ret_4"]
    df["rel_ret_day"] = df["ret_day"] - df["mkt_ret_day"]

    fut = c.shift(-HORIZON_BARS) / c - 1
    same_day = day.shift(-HORIZON_BARS) == day
    df["target"] = fut.where(same_day).clip(-TARGET_CLIP, TARGET_CLIP)
    prev_close = df.groupby("day")["close"].last().shift(1)
    df["prev_close"] = day.map(prev_close)
    return df.replace([np.inf, -np.inf], np.nan)


# ---------- models ----------
class Predictor:
    def __init__(self, kind: str = "ridge", features: list[str] | None = None, name: str = "ridge_base") -> None:
        self.kind, self.features, self.name = kind, list(features or BASE_FEATURES), name
        self.w: np.ndarray | None = None
        self.b = 0.0
        self.mu: np.ndarray | None = None
        self.sd: np.ndarray | None = None
        self.gbm = None
        self.stats: dict = {}

    def _fit_xy(self, X: np.ndarray, y: np.ndarray) -> None:
        if self.kind == "lgbm":
            import lightgbm as lgb
            # Deliberately conservative (shallow trees, big leaves, strong L2): intraday returns are
            # mostly noise, and a flexible model would happily memorise it.
            params = {"objective": "regression", "learning_rate": 0.03, "num_leaves": 15,
                      "min_data_in_leaf": 300, "bagging_fraction": 0.8, "bagging_freq": 1,
                      "feature_fraction": 0.8, "lambda_l2": 10.0, "seed": 42, "num_threads": 2,
                      "verbose": -1}
            self.gbm = lgb.train(params, lgb.Dataset(X, y * 100), num_boost_round=200)  # % units
            return
        self.mu, self.sd = X.mean(0), X.std(0) + 1e-12
        Z = np.clip((X - self.mu) / self.sd, -5, 5)
        self.b = float(y.mean())
        A = Z.T @ Z + RIDGE_LAMBDA * np.eye(Z.shape[1])
        self.w = np.linalg.solve(A, Z.T @ (y - self.b))

    def _predict_x(self, X: np.ndarray) -> np.ndarray:
        if self.kind == "lgbm":
            assert self.gbm is not None
            return self.gbm.predict(X) / 100
        assert self.w is not None
        return np.clip((X - self.mu) / self.sd, -5, 5) @ self.w + self.b

    def fit(self, frames: dict[str, pd.DataFrame]) -> dict:
        df = pd.concat([f.assign(symbol=s) for s, f in frames.items() if len(f) > 40], ignore_index=True)
        rows = df.dropna(subset=self.features + ["target"]).sort_values("ts")
        if len(rows) < 200:
            raise ValueError("Not enough data to train the model")
        wf = walk_forward(rows, self)
        wf.pop("_fold_bounds", None)
        # Refit on everything for live use.
        self._fit_xy(rows[self.features].to_numpy(dtype=float), rows["target"].to_numpy())
        self.stats = {
            "model": self.name,
            "trained_at": datetime.now(IST).isoformat(timespec="seconds"),
            "horizon_minutes": HORIZON_BARS * BAR_MINUTES,
            "train_rows": int(len(rows)),
            **wf,
            "feature_weights": ({f: round(float(w), 5) for f, w in zip(self.features, self.w)}
                                if self.kind == "ridge" else self._importance()),
        }
        return self.stats

    def _importance(self) -> dict:
        imp = self.gbm.feature_importance("gain")
        tot = imp.sum() or 1.0
        return {f: round(float(v / tot), 3) for f, v in sorted(zip(self.features, imp), key=lambda x: -x[1])}

    def predict_latest(self, frames: dict[str, pd.DataFrame]) -> list[dict]:
        out = []
        for sym, f in frames.items():
            ok = f.dropna(subset=self.features)
            if ok.empty or ok.index[-1] != f.index[-1]:
                continue  # latest bar lacks features
            r = ok.iloc[-1]
            p = float(self._predict_x(r[self.features].to_numpy(dtype=float)[None, :])[0])
            prev = r["prev_close"]
            out.append({
                "symbol": sym,
                "last_price": round(float(r["close"]), 2),
                "as_of": r["ts"].isoformat(),
                "change_today_pct": None if pd.isna(prev) else round(float(r["close"] / prev - 1) * 100, 2),
                "predicted_return_pct": round(p * 100, 3),
                "signals": explain(r),
            })
        out.sort(key=lambda x: x["predicted_return_pct"], reverse=True)
        return out


def make_model(name: str) -> Predictor:
    kind, feats, _ = MODEL_SPECS[name]
    return Predictor(kind, feats, name)


def walk_forward(rows: pd.DataFrame, model: Predictor, folds: int = WF_FOLDS, test_frac: float = WF_TEST_FRAC) -> dict:
    """Train-then-test over consecutive recent windows, with a 1-hour purge gap before each window."""
    times = pd.Series(rows["ts"].unique()).sort_values().reset_index(drop=True)
    start = int(len(times) * (1 - test_frac))
    edges = np.linspace(start, len(times), folds + 1).astype(int)
    purge = pd.Timedelta(minutes=HORIZON_BARS * BAR_MINUTES)
    tested, fold_ic, bounds = [], [], []
    for a, b in zip(edges[:-1], edges[1:]):
        if b <= a:
            continue
        t0 = times[a]
        test = rows[(rows["ts"] >= t0) & ((rows["ts"] < times[b]) if b < len(times) else True)]
        train = rows[rows["ts"] < t0 - purge]
        if len(train) < 200 or test.empty:
            continue
        m = type(model)(model.kind, model.features, model.name)
        bounds.append((train["ts"].max(), t0))
        m._fit_xy(train[model.features].to_numpy(dtype=float), train["target"].to_numpy())
        t = test.assign(pred=m._predict_x(test[model.features].to_numpy(dtype=float)))
        tested.append(t)
        fold_ic.append(_ic(t["pred"].to_numpy(), t["target"].to_numpy()))
    if not tested:
        raise ValueError("Not enough data for walk-forward testing")
    t = pd.concat(tested)
    return {**score_frame(t), "test_rows": int(len(t)), "test_from": pd.Timestamp(times[start]).isoformat(),
            "folds": len(tested), "fold_ic": [None if x is None else round(x, 3) for x in fold_ic],
            "_fold_bounds": bounds}


def _ic(p: np.ndarray, y: np.ndarray) -> float | None:
    return float(np.corrcoef(p, y)[0, 1]) if len(y) > 2 and np.std(p) > 0 and np.std(y) > 0 else None


def score_frame(t: pd.DataFrame) -> dict:
    """t has columns ts, pred, target (fractions). Returns the accuracy metrics shown in the app."""
    p, y = t["pred"].to_numpy(), t["target"].to_numpy()
    nz = y != 0
    top5 = t.sort_values("pred", ascending=False).groupby("ts").head(5)
    ic = _ic(p, y)
    return {
        "direction_accuracy_pct": round(float((np.sign(p[nz]) == np.sign(y[nz])).mean() * 100), 1) if nz.any() else None,
        "always_up_pct": round(float((y[nz] > 0).mean() * 100), 1) if nz.any() else None,  # the "dumb" baseline
        "information_coefficient": None if ic is None else round(ic, 3),
        "top5_avg_return_pct": round(float(top5["target"].mean() * 100), 3),
        "top5_hit_rate_pct": round(float((top5["target"] > 0).mean() * 100), 1),
        "market_avg_return_pct": round(float(y.mean() * 100), 3),
    }


def explain(r: pd.Series) -> list[str]:
    """Plain-English tags describing what the stock is doing right now."""
    tags = []
    if abs(r["ret_day"]) >= 0.005:
        tags.append(f"{'Up' if r['ret_day'] > 0 else 'Down'} {abs(r['ret_day']) * 100:.1f}% since open")
    if abs(r["ret_4"]) >= 0.004:
        tags.append(f"{'Rising' if r['ret_4'] > 0 else 'Falling'} {abs(r['ret_4']) * 100:.1f}% last hour")
    rsi_v = r["rsi"] * 50 + 50
    if rsi_v >= 70:
        tags.append(f"Overbought (RSI {rsi_v:.0f})")
    elif rsi_v <= 30:
        tags.append(f"Oversold (RSI {rsi_v:.0f})")
    if r["vol_ratio"] >= np.log(1.8):
        tags.append(f"Volume {np.exp(r['vol_ratio']):.1f}x normal")
    if abs(r.get("rel_ret_day", 0)) >= 0.01:
        tags.append(f"{'Beating' if r['rel_ret_day'] > 0 else 'Lagging'} NIFTY by {abs(r['rel_ret_day']) * 100:.1f}%")
    tags.append("Uptrend" if r["ema_gap"] > 0 else "Downtrend")
    return tags
