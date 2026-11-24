"""Performance metrics. Win rate alone is misleading - read it alongside
profit factor, expectancy, drawdown and the buy-and-hold benchmark."""
from __future__ import annotations

import math
from collections import OrderedDict

from app.models import Trade


def compute_metrics(trades: list[Trade], equity: list[tuple[str, float]], initial: float,
                    benchmark_return_pct: float | None = None) -> dict:
    final = equity[-1][1] if equity else initial
    wins = [t.net_pnl for t in trades if t.net_pnl > 0]
    losses = [t.net_pnl for t in trades if t.net_pnl <= 0]
    gross_win, gross_loss = sum(wins), -sum(losses)

    # Max drawdown on the equity curve
    peak, max_dd = initial, 0.0
    for _, e in equity:
        peak = max(peak, e)
        max_dd = max(max_dd, (peak - e) / peak if peak else 0)

    # Daily returns -> Sharpe (annualised, 252 trading days, rf = 0)
    daily: OrderedDict[str, float] = OrderedDict()
    for ts, e in equity:
        daily[ts[:10]] = e
    vals = [initial, *daily.values()]
    rets = [(b - a) / a for a, b in zip(vals, vals[1:]) if a]
    sharpe = None
    if len(rets) > 1:
        mean = sum(rets) / len(rets)
        sd = math.sqrt(sum((r - mean) ** 2 for r in rets) / (len(rets) - 1))
        sharpe = round(mean / sd * math.sqrt(252), 2) if sd > 0 else None

    n = len(trades)
    total_return = (final - initial) / initial * 100
    return {
        "initial_capital": round(initial, 2),
        "final_equity": round(final, 2),
        "net_pnl": round(final - initial, 2),
        "total_return_pct": round(total_return, 2),
        "benchmark_return_pct": None if benchmark_return_pct is None else round(benchmark_return_pct, 2),
        "num_trades": n,
        "win_rate_pct": round(len(wins) / n * 100, 2) if n else None,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else None,
        "expectancy": round(sum(t.net_pnl for t in trades) / n, 2) if n else None,
        "avg_win": round(gross_win / len(wins), 2) if wins else None,
        "avg_loss": round(-gross_loss / len(losses), 2) if losses else None,
        "max_drawdown_pct": round(max_dd * 100, 2),
        "sharpe": sharpe,
        "total_charges": round(sum(t.charges for t in trades), 2),
        "gross_pnl": round(sum(t.gross_pnl for t in trades), 2),
        "trading_days": len(daily),
    }
