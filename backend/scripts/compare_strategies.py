"""Compare every strategy on the same data, with full NSE charges, and check consistency over time.

    python -m scripts.compare_strategies                    # 15m/60d and 1h/730d on NIFTY 50
    python -m scripts.compare_strategies --interval 1h --period 730d --json out.json

A strategy is only interesting if it is net profitable after charges AND profitable in most
sub-periods (not one lucky stretch) AND beats doing nothing (buy & hold) on a risk basis.
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import NIFTY_50, settings  # noqa: E402
from app.data.feed import YFinanceFeed  # noqa: E402
from app.engine.backtest import run_on_bars  # noqa: E402
from app.strategies import REGISTRY  # noqa: E402


def period_key(ts, interval: str) -> str:
    # 60 days of 15m -> weekly buckets; 2 years of 1h -> monthly buckets
    if interval in ("1m", "5m", "15m", "30m"):
        y, w, _ = ts.isocalendar()
        return f"{y}-W{w:02d}"
    return ts.strftime("%Y-%m")


def evaluate(bars, interval: str, s, strategies) -> list[dict]:
    rows = []
    for name in strategies:
        r = run_on_bars(bars, name, {}, interval, s)
        m = r.metrics
        by_period: dict[str, float] = defaultdict(float)
        for t in r.trades:
            by_period[period_key(t.exit_ts, interval)] += t.net_pnl
        periods = sorted(by_period)
        positive = sum(1 for k in periods if by_period[k] > 0)
        rows.append({
            "strategy": name, "interval": interval,
            "net_pnl": m["net_pnl"], "return_pct": m["total_return_pct"],
            "buy_hold_pct": m["benchmark_return_pct"], "trades": m["num_trades"],
            "win_rate_pct": m["win_rate_pct"], "profit_factor": m["profit_factor"],
            "expectancy": m["expectancy"], "max_dd_pct": m["max_drawdown_pct"], "sharpe": m["sharpe"],
            "charges": m["total_charges"], "gross_pnl": m["gross_pnl"],
            "periods": len(periods), "periods_positive": positive,
            "by_period": {k: round(by_period[k], 2) for k in periods},
        })
    return rows


def show(rows: list[dict]) -> None:
    hdr = f"{'strategy':<15}{'net Rs':>11}{'ret%':>7}{'B&H%':>7}{'trades':>7}{'win%':>6}{'PF':>6}" \
          f"{'exp Rs':>8}{'maxDD%':>7}{'charges':>9}{'periods +':>11}"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print(f"{r['strategy']:<15}{r['net_pnl']:>11,.0f}{r['return_pct']:>7.2f}{(r['buy_hold_pct'] or 0):>7.2f}"
              f"{r['trades']:>7}{(r['win_rate_pct'] or 0):>6.1f}{(r['profit_factor'] or 0):>6.2f}"
              f"{(r['expectancy'] or 0):>8.0f}{r['max_dd_pct']:>7.2f}{r['charges']:>9,.0f}"
              f"{r['periods_positive']:>6}/{r['periods']:<4}")
    print()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", help="only this interval (default: 15m/60d and 1h/730d)")
    ap.add_argument("--period")
    ap.add_argument("--capital", type=float, default=500_000)
    ap.add_argument("--json", help="write full results here")
    a = ap.parse_args()

    runs = [(a.interval, a.period or "60d")] if a.interval else [("15m", "60d"), ("1h", "730d")]
    s = settings.with_overrides(initial_capital=a.capital)
    feed = YFinanceFeed(s)
    out = []
    for interval, period in runs:
        bars = {k: v for k, v in feed.history_many(NIFTY_50, interval, period).items() if v}
        n = sum(len(v) for v in bars.values())
        first = min(v[0].ts for v in bars.values()).date()
        last = max(v[-1].ts for v in bars.values()).date()
        print(f"== {interval} | {len(bars)} stocks | {n:,} candles | {first} to {last} | "
              f"capital Rs {s.initial_capital:,.0f} | full charges + {s.slippage_bps} bps slippage ==")
        rows = evaluate(bars, interval, s, list(REGISTRY))
        show(rows)
        out += rows
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
