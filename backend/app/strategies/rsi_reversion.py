from app.models import Signal
from app.strategies.base import History, Strategy
from app.strategies.indicators import rsi


class RsiReversion(Strategy):
    name = "rsi_reversion"
    description = "Mean reversion: buy oversold (RSI<30), short overbought (RSI>70), exit near RSI 50."
    default_params = {"period": 14, "oversold": 30, "overbought": 70, "exit_level": 50}

    @property
    def warmup(self) -> int:
        return self.params["period"] * 4

    def on_bar(self, hist: History, position: int) -> Signal:
        p = self.params
        r = rsi(hist.close, p["period"])[-1]
        if position > 0 and r >= p["exit_level"]:
            return Signal(0, f"RSI {r:.0f} back to mean")
        if position < 0 and r <= p["exit_level"]:
            return Signal(0, f"RSI {r:.0f} back to mean")
        if position == 0:
            if r < p["oversold"]:
                return Signal(1, f"RSI {r:.0f} oversold")
            if r > p["overbought"]:
                return Signal(self._dir(-1), f"RSI {r:.0f} overbought")
        return Signal(position)
