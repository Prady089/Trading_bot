"""CLI backtest. Example (from backend/):
    python -m scripts.run_backtest --strategy opening_range --interval 15m --period 60d
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import DEFAULT_SYMBOLS, settings  # noqa: E402
from app.data.feed import YFinanceFeed  # noqa: E402
from app.engine.backtest import run_backtest  # noqa: E402
from app.strategies import REGISTRY  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", default="ema_crossover", choices=list(REGISTRY))
    ap.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS[:5]))
    ap.add_argument("--interval", default="15m")
    ap.add_argument("--period", default="60d")
    ap.add_argument("--all", action="store_true", help="run every strategy")
    a = ap.parse_args()

    symbols = [s.strip() for s in a.symbols.split(",") if s.strip()]
    feed = YFinanceFeed(settings)
    strategies = list(REGISTRY) if a.all else [a.strategy]
    print(f"Symbols: {', '.join(symbols)} | {a.interval} | {a.period} | capital Rs {settings.initial_capital:,.0f}\n")
    for name in strategies:
        r = run_backtest(feed, name, symbols, a.interval, a.period, {}, settings)
        m = r.metrics
        print(f"== {name} ==")
        for k, v in m.items():
            print(f"  {k:<22} {v}")
        if r.symbols_without_data:
            print(f"  (no data for: {', '.join(r.symbols_without_data)})")
        print()


if __name__ == "__main__":
    main()
