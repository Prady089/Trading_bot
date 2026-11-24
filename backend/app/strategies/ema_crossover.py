from app.models import Signal
from app.strategies.base import History, Strategy
from app.strategies.indicators import ema


class EmaCrossover(Strategy):
    name = "ema_crossover"
    description = "Trend following: long when fast EMA > slow EMA, short when below."
    default_params = {"fast": 9, "slow": 21}

    @property
    def warmup(self) -> int:
        return self.params["slow"] * 3

    def on_bar(self, hist: History, position: int) -> Signal:
        c = hist.close
        f, s = ema(c, self.params["fast"])[-1], ema(c, self.params["slow"])[-1]
        d = self._dir(1 if f > s else -1)
        return Signal(d, f"EMA{self.params['fast']} {'>' if f > s else '<'} EMA{self.params['slow']}")
