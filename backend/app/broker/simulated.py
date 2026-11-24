"""Simulated broker: realistic fills for paper trading and backtests.

Rules (designed to avoid look-ahead bias):
- Orders created at a bar's close fill at the NEXT bar's open, plus slippage.
- Stops/targets are checked against each bar's high/low. If both are hit in the
  same bar we assume the stop hit first (conservative).
- If price gaps through a stop, the fill is at the open (worse than the stop).
"""
from __future__ import annotations

from datetime import datetime

from app.broker.costs import IndianEquityCosts
from app.models import Bar, Order, Position, Side, Trade


class SimulatedBroker:
    def __init__(self, initial_capital: float, costs: IndianEquityCosts,
                 slippage_bps: float = 3.0, margin_rate: float = 1.0):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.costs = costs
        self.slippage = slippage_bps / 10_000
        self.margin_rate = margin_rate
        self.positions: dict[str, Position] = {}
        self.pending: list[Order] = []
        self.trades: list[Trade] = []
        self.last_price: dict[str, float] = {}
        self.total_charges = 0.0
        # Per-symbol overrides (e.g. index futures): symbol -> (margin_rate, costs model)
        self.instruments: dict[str, tuple[float, object]] = {}

    def margin_rate_for(self, symbol: str) -> float:
        return self.instruments[symbol][0] if symbol in self.instruments else self.margin_rate

    def costs_for(self, symbol: str):
        return self.instruments[symbol][1] if symbol in self.instruments else self.costs

    # ---------- account ----------
    def equity(self) -> float:
        return self.cash + sum(p.qty * self.last_price.get(s, p.avg_price) for s, p in self.positions.items())

    def used_margin(self) -> float:
        return sum(abs(p.qty) * self.last_price.get(s, p.avg_price) * self.margin_rate_for(s)
                   for s, p in self.positions.items())

    def available_margin(self) -> float:
        return self.equity() - self.used_margin()

    def submit(self, order: Order) -> None:
        self.pending.append(order)

    def cancel_pending(self, symbol: str) -> None:
        self.pending = [o for o in self.pending if o.symbol != symbol]

    # ---------- bar processing ----------
    def fill_pending(self, bar: Bar) -> None:
        """Fill this symbol's queued orders at the bar open. Exits before entries."""
        mine = [o for o in self.pending if o.symbol == bar.symbol]
        if not mine:
            return
        self.pending = [o for o in self.pending if o.symbol != bar.symbol]
        for o in sorted(mine, key=lambda o: o.is_entry):
            if o.is_entry:
                self._open(o, bar.open, bar.ts)
            elif bar.symbol in self.positions:
                self.close_position(bar.symbol, bar.open, bar.ts, o.reason)

    def check_stops(self, bar: Bar) -> None:
        p = self.positions.get(bar.symbol)
        if not p:
            return
        if p.direction > 0:
            if p.stop_price is not None and bar.low <= p.stop_price:
                self.close_position(bar.symbol, min(bar.open, p.stop_price), bar.ts, "stop-loss", slip=True)
            elif p.target_price is not None and bar.high >= p.target_price:
                self.close_position(bar.symbol, max(bar.open, p.target_price), bar.ts, "take-profit", slip=False)
        else:
            if p.stop_price is not None and bar.high >= p.stop_price:
                self.close_position(bar.symbol, max(bar.open, p.stop_price), bar.ts, "stop-loss", slip=True)
            elif p.target_price is not None and bar.low <= p.target_price:
                self.close_position(bar.symbol, min(bar.open, p.target_price), bar.ts, "take-profit", slip=False)

    def mark(self, bar: Bar) -> None:
        self.last_price[bar.symbol] = bar.close

    # ---------- fills ----------
    def _slipped(self, price: float, side: Side) -> float:
        return price * (1 + self.slippage) if side == Side.BUY else price * (1 - self.slippage)

    def _open(self, o: Order, ref_price: float, ts: datetime) -> None:
        if o.symbol in self.positions:
            return
        price = self._slipped(ref_price, o.side)
        # Re-check margin at the actual fill price.
        max_qty = int(self.available_margin() / (price * self.margin_rate_for(o.symbol))) if price > 0 else 0
        qty = min(o.qty, max_qty)
        if o.symbol in self.instruments and qty < o.qty:
            return  # futures trade in whole lots: never partially fill a lot
        if qty <= 0:
            return
        charges = self.costs_for(o.symbol).charges(o.side, price, qty)
        signed = qty if o.side == Side.BUY else -qty
        self.cash -= signed * price + charges
        self.total_charges += charges
        direction = 1 if signed > 0 else -1
        sl, tp = o.stop_loss_pct, o.take_profit_pct
        self.positions[o.symbol] = Position(
            symbol=o.symbol, qty=signed, avg_price=price, entry_ts=ts,
            stop_price=price * (1 - direction * sl / 100) if sl else None,
            target_price=price * (1 + direction * tp / 100) if tp else None,
            entry_charges=charges, entry_reason=o.reason, source=o.source,
            predicted_return_pct=o.predicted_return_pct,
        )
        self.last_price.setdefault(o.symbol, price)

    def market_order(self, o: Order, ref_price: float, ts: datetime) -> Position | None:
        """Fill an entry immediately at ref_price (+ slippage). Used by the live account."""
        if o.symbol in self.positions:
            return None
        self._open(o, ref_price, ts)
        return self.positions.get(o.symbol)

    def close_position(self, symbol: str, ref_price: float, ts: datetime, reason: str,
                       slip: bool = True) -> Trade | None:
        p = self.positions.pop(symbol, None)
        if not p:
            return None
        side = Side.SELL if p.qty > 0 else Side.BUY
        price = self._slipped(ref_price, side) if slip else ref_price
        qty = abs(p.qty)
        charges = self.costs_for(symbol).charges(side, price, qty)
        self.cash += p.qty * price - charges
        self.total_charges += charges
        gross = (price - p.avg_price) * p.qty
        total_charges = p.entry_charges + charges
        t = Trade(symbol=symbol, direction=p.direction, qty=qty, entry_ts=p.entry_ts,
                  entry_price=round(p.avg_price, 4), exit_ts=ts, exit_price=round(price, 4),
                  gross_pnl=round(gross, 2), charges=round(total_charges, 2),
                  net_pnl=round(gross - total_charges, 2),
                  entry_reason=p.entry_reason, exit_reason=reason, source=p.source,
                  predicted_return_pct=p.predicted_return_pct)
        self.trades.append(t)
        self.last_price[symbol] = price
        return t

    # ---------- persistence ----------
    def snapshot(self) -> dict:
        return {"cash": self.cash, "total_charges": self.total_charges,
                "last_price": self.last_price,
                "positions": {s: p.to_dict() for s, p in self.positions.items()}}

    def restore(self, snap: dict) -> None:
        self.cash = snap["cash"]
        self.total_charges = snap.get("total_charges", 0.0)
        self.last_price = dict(snap.get("last_price", {}))
        self.positions = {s: Position.from_dict(d) for s, d in snap.get("positions", {}).items()}
