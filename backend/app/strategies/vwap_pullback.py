from datetime import date, time

from app.models import Signal
from app.strategies.base import History, Strategy
from app.strategies.indicators import atr, ema, session_vwap


class VwapPullback(Strategy):
    name = "vwap_pullback"
    description = ("Intraday trend pullback: when price trends above VWAP (and EMA20 > EMA50), buy the dip "
                   "that touches VWAP and closes back above it. Mirror image for shorts. Stop 1 ATR beyond VWAP, "
                   "target 2x risk, exit if price closes back through VWAP. Max one trade per stock per day.")
    default_params = {"fast": 20, "slow": 50, "atr_period": 14, "atr_stop": 1.0, "reward_risk": 2.0,
                      "start_hhmm": 1000, "max_stop_pct": 1.5}

    def __init__(self, params: dict, allow_short: bool = True):
        super().__init__(params, allow_short)
        self._traded: dict[str, date] = {}

    @property
    def warmup(self) -> int:
        return self.params["slow"] * 2

    def on_bar(self, hist: History, position: int) -> Signal:
        p = self.params
        today = hist.today()
        vwap = session_vwap(today)
        if vwap is None:
            return Signal(0 if position == 0 else position)
        b = hist.last
        if position > 0:
            return Signal(1 if b.close >= vwap else 0, "closed below VWAP")
        if position < 0:
            return Signal(-1 if b.close <= vwap else 0, "closed above VWAP")

        start = time(int(p["start_hhmm"]) // 100, int(p["start_hhmm"]) % 100)
        if b.ts.time() < start or self._traded.get(b.symbol) == b.ts.date():
            return Signal(0)
        c = hist.close
        f, s = ema(c, int(p["fast"]))[-1], ema(c, int(p["slow"]))[-1]
        a = atr(hist.high, hist.low, c, int(p["atr_period"]))[-1]
        prev = today[-2] if len(today) > 1 else None
        if prev is None:
            return Signal(0)

        d = 0
        if f > s and prev.close > vwap and b.low <= vwap <= b.close:
            d = 1    # uptrend, dipped to VWAP, held above it
        elif f < s and prev.close < vwap and b.high >= vwap >= b.close:
            d = -1   # downtrend, rallied to VWAP, rejected
        d = self._dir(d)
        if d == 0:
            return Signal(0)
        stop_price = vwap - d * p["atr_stop"] * a
        stop = abs(b.close - stop_price) / b.close * 100
        if stop <= 0.05 or stop > p["max_stop_pct"]:
            return Signal(0)
        self._traded[b.symbol] = b.ts.date()
        return Signal(d, f"pullback to VWAP {vwap:.2f} in {'up' if d > 0 else 'down'}trend",
                      stop_loss_pct=round(stop, 3), take_profit_pct=round(stop * p["reward_risk"], 3))
