from datetime import time

from app.models import Signal
from app.strategies.base import History, Strategy
from app.strategies.indicators import supertrend


class SupertrendFollow(Strategy):
    name = "supertrend"
    description = ("Trend following with Supertrend (ATR bands): long while the trend is up, short while down. "
                   "Stop just beyond the Supertrend line, target at 2x the risk.")
    default_params = {"atr_period": 10, "multiplier": 3.0, "reward_risk": 2.0, "max_stop_pct": 2.0,
                      "start_hhmm": 930}

    @property
    def warmup(self) -> int:
        return self.params["atr_period"] * 5

    def on_bar(self, hist: History, position: int) -> Signal:
        p = self.params
        line, trend = supertrend(hist.high, hist.low, hist.close, int(p["atr_period"]), p["multiplier"])
        d, c = int(trend[-1]), hist.close[-1]
        if position != 0:
            # hold while the trend agrees, exit on a flip
            return Signal(position if d == position else 0, "Supertrend flipped")
        flipped = len(trend) > 1 and trend[-2] != d
        start = time(int(p["start_hhmm"]) // 100, int(p["start_hhmm"]) % 100)
        intraday = hist.last.ts.time() != time(0, 0)   # daily candles are stamped midnight
        if not flipped or (intraday and hist.last.ts.time() < start):
            return Signal(0)
        d = self._dir(d)
        if d == 0:
            return Signal(0)
        stop = min(abs(c - line[-1]) / c * 100, p["max_stop_pct"])
        if stop <= 0.05:
            return Signal(0)
        return Signal(d, f"Supertrend turned {'up' if d > 0 else 'down'} (line {line[-1]:.2f})",
                      stop_loss_pct=round(stop, 3), take_profit_pct=round(stop * p["reward_risk"], 3))
