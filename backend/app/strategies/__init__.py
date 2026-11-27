from app.strategies.base import Strategy
from app.strategies.ema_crossover import EmaCrossover
from app.strategies.rsi_reversion import RsiReversion
from app.strategies.opening_range import OpeningRangeBreakout
from app.strategies.supertrend import SupertrendFollow
from app.strategies.vwap_pullback import VwapPullback

REGISTRY: dict[str, type[Strategy]] = {
    cls.name: cls for cls in (EmaCrossover, RsiReversion, OpeningRangeBreakout, SupertrendFollow, VwapPullback)
}


def build_strategy(name: str, params: dict | None = None, allow_short: bool = True) -> Strategy:
    if name not in REGISTRY:
        raise ValueError(f"Unknown strategy '{name}'. Available: {list(REGISTRY)}")
    return REGISTRY[name](params or {}, allow_short=allow_short)
