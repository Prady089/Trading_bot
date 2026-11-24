from datetime import date

from app.models import Signal
from app.strategies.base import History, Strategy


class OpeningRangeBreakout(Strategy):
    name = "opening_range"
    description = ("Intraday ORB: mark the high/low of the first N bars of the day; "
                   "go long on a close above it, short on a close below. One trade per day.")
    default_params = {"range_bars": 2}  # 2 x 15m = first 30 minutes

    def __init__(self, params: dict, allow_short: bool = True):
        super().__init__(params, allow_short)
        self._traded: dict[str, date] = {}

    def on_bar(self, hist: History, position: int) -> Signal:
        if position != 0:
            return Signal(position)  # exits handled by stop / target / square-off
        today = hist.today()
        n = self.params["range_bars"]
        if len(today) <= n:
            return Signal(0)
        sym, d = hist.last.symbol, hist.last.ts.date()
        if self._traded.get(sym) == d:
            return Signal(0)
        hi = max(b.high for b in today[:n])
        lo = min(b.low for b in today[:n])
        c = hist.last.close
        if c > hi:
            self._traded[sym] = d
            return Signal(1, f"breakout above opening range {hi:.2f}")
        if c < lo and self.allow_short:
            self._traded[sym] = d
            return Signal(-1, f"breakdown below opening range {lo:.2f}")
        return Signal(0)
