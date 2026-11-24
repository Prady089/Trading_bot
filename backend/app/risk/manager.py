"""Risk manager: position sizing + guard rails. Every entry goes through here."""
from __future__ import annotations

import math
from datetime import date

from app.config import Settings


class RiskManager:
    def __init__(self, s: Settings):
        self.s = s
        self.day: date | None = None
        self.day_start_equity = 0.0
        self.halted = False
        self.halt_reason = ""

    def on_bar(self, d: date, equity: float) -> None:
        if d != self.day:
            self.day, self.day_start_equity, self.halted, self.halt_reason = d, equity, False, ""
        elif not self.halted and equity <= self.day_start_equity * (1 - self.s.max_daily_loss_pct / 100):
            self.halted = True
            self.halt_reason = f"daily loss limit {self.s.max_daily_loss_pct}% hit"

    def can_open(self, open_positions: int) -> bool:
        return not self.halted and open_positions < self.s.max_open_positions

    def size(self, price: float, stop_pct: float, equity: float, available: float) -> int:
        """Qty such that hitting the stop loses ~risk_per_trade_pct of equity, within caps."""
        if price <= 0 or stop_pct <= 0:
            return 0
        by_risk = equity * self.s.risk_per_trade_pct / 100 / (price * stop_pct / 100)
        by_cap = equity * self.s.max_position_pct / 100 / price
        by_margin = available / (price * self.s.margin_rate)
        return max(0, math.floor(min(by_risk, by_cap, by_margin)))
