"""The trading engine. Backtests and live paper trading both call `process_bar`,
so whatever you measure in a backtest is exactly what runs live."""
from __future__ import annotations

from datetime import datetime, timedelta

from app.broker.simulated import SimulatedBroker
from app.config import Settings
from app.models import Bar, Order, Side
from app.risk.manager import RiskManager
from app.strategies.base import History, Strategy


class TradingEngine:
    def __init__(self, strategy: Strategy, broker: SimulatedBroker, risk: RiskManager,
                 settings: Settings, bar_minutes: int, intraday: bool):
        self.strategy = strategy
        self.broker = broker
        self.risk = risk
        self.s = settings
        self.bar_delta = timedelta(minutes=bar_minutes)
        self.intraday = intraday
        self.history: dict[str, History] = {}
        self.events: list[tuple[datetime, str, str]] = []  # (ts, level, message)

    def _log(self, ts: datetime, msg: str, level: str = "info") -> None:
        self.events.append((ts, level, msg))

    def warm(self, bar: Bar) -> None:
        """Feed history without trading (used when the live trader starts up)."""
        self.history.setdefault(bar.symbol, History()).append(bar)
        self.broker.mark(bar)

    def process_bar(self, bar: Bar) -> None:
        b, sym, t = self.broker, bar.symbol, bar.ts.time()
        n_trades = len(b.trades)

        # 1. Orders from the previous bar's close fill at this bar's open.
        b.fill_pending(bar)

        # 2. Intraday square-off.
        if self.intraday and t >= self.s.square_off_at:
            b.cancel_pending(sym)
            if sym in b.positions:
                b.close_position(sym, bar.open, bar.ts, "intraday square-off")

        # 3. Stop-loss / take-profit inside this bar.
        b.check_stops(bar)
        b.mark(bar)
        for tr in b.trades[n_trades:]:
            self._log(bar.ts, f"EXIT {sym} {'LONG' if tr.direction > 0 else 'SHORT'} x{tr.qty} "
                              f"@ {tr.exit_price:.2f} ({tr.exit_reason}) net {tr.net_pnl:+.2f}")

        hist = self.history.setdefault(sym, History())
        hist.append(bar)

        # 4. Risk bookkeeping (daily loss limit).
        was_halted = self.risk.halted
        self.risk.on_bar(bar.ts.date(), b.equity())
        if self.risk.halted and not was_halted:
            self._log(bar.ts, f"Trading halted: {self.risk.halt_reason}", "warn")

        # 5. Strategy decides at the bar close; orders queue for the next open.
        if self.intraday and t >= self.s.square_off_at:
            return
        if len(hist) < self.strategy.warmup:
            return
        pos = b.positions.get(sym)
        cur = pos.direction if pos else 0
        sig = self.strategy.on_bar(hist, cur)
        if sig.direction == cur:
            return

        if pos:
            b.submit(Order(sym, Side.SELL if cur > 0 else Side.BUY, abs(pos.qty), False,
                           sig.reason or "signal exit", bar.ts))
        if sig.direction == 0:
            return

        bar_end = (bar.ts + self.bar_delta).time()
        if self.intraday and bar_end >= self.s.no_new_entries_after:
            return
        open_after = len(b.positions) - (1 if pos else 0)
        if not self.risk.can_open(open_after):
            return
        sl = sig.stop_loss_pct or self.s.default_stop_loss_pct
        tp = sig.take_profit_pct or self.s.default_take_profit_pct
        qty = self.risk.size(bar.close, sl, b.equity(), b.available_margin())
        if qty <= 0:
            return
        side = Side.BUY if sig.direction > 0 else Side.SELL
        b.submit(Order(sym, side, qty, True, sig.reason, bar.ts, sl, tp))
        self._log(bar.ts, f"SIGNAL {sym} {'LONG' if side == Side.BUY else 'SHORT'} x{qty} - {sig.reason}")
