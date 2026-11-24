from __future__ import annotations

from dataclasses import dataclass, field
from itertools import groupby

from app.broker.costs import IndianEquityCosts
from app.broker.simulated import SimulatedBroker
from app.config import Settings
from app.data.feed import INTERVAL_MINUTES, DataFeed
from app.engine.core import TradingEngine
from app.engine.metrics import compute_metrics
from app.models import Bar, Trade
from app.risk.manager import RiskManager
from app.strategies import build_strategy


@dataclass
class BacktestResult:
    metrics: dict
    trades: list[Trade]
    equity: list[tuple[str, float]]
    events: list[tuple[str, str, str]] = field(default_factory=list)
    symbols_without_data: list[str] = field(default_factory=list)


def make_engine(strategy_name: str, params: dict, interval: str, s: Settings) -> TradingEngine:
    intraday = interval != "1d"
    broker = SimulatedBroker(s.initial_capital,
                             IndianEquityCosts(product="intraday" if intraday else "delivery"),
                             s.slippage_bps, s.margin_rate)
    return TradingEngine(build_strategy(strategy_name, params, s.allow_short), broker,
                         RiskManager(s), s, INTERVAL_MINUTES[interval], intraday)


def run_on_bars(bars_by_symbol: dict[str, list[Bar]], strategy_name: str, params: dict,
                interval: str, s: Settings) -> BacktestResult:
    engine = make_engine(strategy_name, params, interval, s)
    all_bars = sorted((b for bars in bars_by_symbol.values() for b in bars), key=lambda b: (b.ts, b.symbol))
    equity: list[tuple[str, float]] = []
    for ts, group in groupby(all_bars, key=lambda b: b.ts):
        for bar in group:
            engine.process_bar(bar)
        equity.append((ts.isoformat(), round(engine.broker.equity(), 2)))

    # Close anything still open at the final price.
    if all_bars:
        last = all_bars[-1]
        for sym in list(engine.broker.positions):
            engine.broker.close_position(sym, engine.broker.last_price[sym], last.ts, "end of backtest")
        if equity:
            equity[-1] = (equity[-1][0], round(engine.broker.equity(), 2))

    # Benchmark: equal-weight buy & hold, gross of costs.
    rets = [(bars[-1].close - bars[0].open) / bars[0].open * 100 for bars in bars_by_symbol.values() if bars]
    bench = sum(rets) / len(rets) if rets else None

    return BacktestResult(
        metrics=compute_metrics(engine.broker.trades, equity, s.initial_capital, bench),
        trades=engine.broker.trades,
        equity=equity,
        events=[(t.isoformat(), lvl, m) for t, lvl, m in engine.events],
        symbols_without_data=[k for k, v in bars_by_symbol.items() if not v],
    )


def run_backtest(feed: DataFeed, strategy_name: str, symbols: list[str], interval: str,
                 period: str, params: dict, s: Settings) -> BacktestResult:
    data = {sym.upper(): feed.history(sym, interval, period) for sym in symbols}
    return run_on_bars(data, strategy_name, params, interval, s)
