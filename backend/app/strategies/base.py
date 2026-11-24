from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque

import numpy as np

from app.models import Bar, Signal


class History:
    """Rolling window of a symbol's bars, exposed as numpy arrays. Contains only
    bars up to and including the current one - strategies cannot see the future."""

    def __init__(self, maxlen: int = 400):
        self.bars: deque[Bar] = deque(maxlen=maxlen)

    def append(self, bar: Bar) -> None:
        self.bars.append(bar)

    def __len__(self) -> int:
        return len(self.bars)

    @property
    def close(self) -> np.ndarray:
        return np.fromiter((b.close for b in self.bars), float, len(self.bars))

    @property
    def high(self) -> np.ndarray:
        return np.fromiter((b.high for b in self.bars), float, len(self.bars))

    @property
    def low(self) -> np.ndarray:
        return np.fromiter((b.low for b in self.bars), float, len(self.bars))

    @property
    def last(self) -> Bar:
        return self.bars[-1]

    def today(self) -> list[Bar]:
        d = self.bars[-1].ts.date()
        out = []
        for b in reversed(self.bars):
            if b.ts.date() != d:
                break
            out.append(b)
        return out[::-1]


class Strategy(ABC):
    name: str = "base"
    description: str = ""
    default_params: dict = {}

    def __init__(self, params: dict, allow_short: bool = True):
        self.params = {**self.default_params, **params}
        self.allow_short = allow_short

    @property
    def warmup(self) -> int:
        """Bars needed before the strategy can produce signals."""
        return 1

    @abstractmethod
    def on_bar(self, hist: History, position: int) -> Signal:
        """Called at each bar close. `position` is the current direction (+1/0/-1).
        Return the direction you want to hold from the next bar."""

    def _dir(self, d: int) -> int:
        return d if (d >= 0 or self.allow_short) else 0
