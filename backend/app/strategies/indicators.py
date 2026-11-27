"""Indicator math in numpy. Each returns an array aligned with the input."""
from __future__ import annotations

import numpy as np


def ema(x: np.ndarray, n: int) -> np.ndarray:
    out = np.empty_like(x, dtype=float)
    if len(x) == 0:
        return out
    a = 2 / (n + 1)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def rsi(close: np.ndarray, n: int = 14) -> np.ndarray:
    """Wilder's RSI."""
    out = np.full(len(close), np.nan)
    if len(close) <= n:
        return out
    d = np.diff(close)
    gain, loss = np.clip(d, 0, None), np.clip(-d, 0, None)
    ag, al = gain[:n].mean(), loss[:n].mean()
    for i in range(n, len(close)):
        if i > n:
            ag = (ag * (n - 1) + gain[i - 1]) / n
            al = (al * (n - 1) + loss[i - 1]) / n
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int = 14) -> np.ndarray:
    prev = np.concatenate([[close[0]], close[:-1]])
    tr = np.maximum(high - low, np.maximum(abs(high - prev), abs(low - prev)))
    return ema(tr, n)


def supertrend(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int = 10,
               mult: float = 3.0) -> tuple[np.ndarray, np.ndarray]:
    """Supertrend line and direction (+1 up / -1 down). Standard final-band algorithm."""
    a = atr(high, low, close, n)
    mid = (high + low) / 2
    up_basic, dn_basic = mid - mult * a, mid + mult * a
    up, dn = up_basic.copy(), dn_basic.copy()
    line = np.empty(len(close))
    trend = np.ones(len(close), dtype=int)
    for i in range(len(close)):
        if i > 0:
            up[i] = max(up_basic[i], up[i - 1]) if close[i - 1] > up[i - 1] else up_basic[i]
            dn[i] = min(dn_basic[i], dn[i - 1]) if close[i - 1] < dn[i - 1] else dn_basic[i]
            if trend[i - 1] == 1:
                trend[i] = -1 if close[i] < up[i] else 1
            else:
                trend[i] = 1 if close[i] > dn[i] else -1
        line[i] = up[i] if trend[i] == 1 else dn[i]
    return line, trend


def session_vwap(bars) -> float | None:
    """Volume-weighted average of the typical price over the given (today's) bars."""
    pv = sum((b.high + b.low + b.close) / 3 * b.volume for b in bars)
    v = sum(b.volume for b in bars)
    return pv / v if v > 0 else None
