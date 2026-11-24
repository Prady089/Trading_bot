"""Indian equity (NSE) transaction charges.

Rates reflect a typical discount broker (Zerodha/Upstox style) as of 2025.
They change from time to time - verify against your broker's charges page.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.models import Side


@dataclass(frozen=True)
class IndianEquityCosts:
    product: str = "intraday"           # "intraday" (MIS) or "delivery" (CNC)

    # Brokerage: lower of flat Rs / % of turnover, per executed order
    intraday_brokerage_flat: float = 20.0
    intraday_brokerage_pct: float = 0.03
    delivery_brokerage_flat: float = 0.0

    # Statutory (percent of turnover)
    STT_INTRADAY_SELL_PCT = 0.025
    STT_DELIVERY_PCT = 0.1               # both buy and sell
    EXCHANGE_TXN_PCT = 0.00297           # NSE
    SEBI_FEE_PER_CRORE = 10.0
    STAMP_INTRADAY_BUY_PCT = 0.003
    STAMP_DELIVERY_BUY_PCT = 0.015
    GST_PCT = 18.0                       # on brokerage + exchange + SEBI fee

    def breakdown(self, side: Side, price: float, qty: int) -> dict[str, float]:
        turnover = price * qty
        if self.product == "intraday":
            brokerage = min(self.intraday_brokerage_flat, turnover * self.intraday_brokerage_pct / 100)
            stt = turnover * self.STT_INTRADAY_SELL_PCT / 100 if side == Side.SELL else 0.0
            stamp = turnover * self.STAMP_INTRADAY_BUY_PCT / 100 if side == Side.BUY else 0.0
        else:
            brokerage = self.delivery_brokerage_flat
            stt = turnover * self.STT_DELIVERY_PCT / 100
            stamp = turnover * self.STAMP_DELIVERY_BUY_PCT / 100 if side == Side.BUY else 0.0
        exchange = turnover * self.EXCHANGE_TXN_PCT / 100
        sebi = turnover * self.SEBI_FEE_PER_CRORE / 1e7
        gst = (brokerage + exchange + sebi) * self.GST_PCT / 100
        parts = dict(brokerage=brokerage, stt=stt, exchange=exchange, sebi=sebi, stamp=stamp, gst=gst)
        parts["total"] = sum(parts.values())
        return parts

    def charges(self, side: Side, price: float, qty: int) -> float:
        return round(self.breakdown(side, price, qty)["total"], 2)


@dataclass(frozen=True)
class IndianFuturesCosts:
    """NSE index futures charges per executed order (discount broker).

    STT on futures sell side was 0.02% from Oct 2024; Budget 2026 proposed raising it. The default
    here is the higher 0.05% so the simulator errs on the side of costs. Override with FUT_STT_SELL_PCT.
    """
    brokerage_flat: float = 20.0
    brokerage_pct: float = 0.03
    stt_sell_pct: float = float(__import__("os").getenv("FUT_STT_SELL_PCT", 0.05))
    EXCHANGE_TXN_PCT = 0.00173           # NSE futures
    SEBI_FEE_PER_CRORE = 10.0
    STAMP_BUY_PCT = 0.002
    GST_PCT = 18.0

    def breakdown(self, side: Side, price: float, qty: int) -> dict[str, float]:
        turnover = price * qty
        brokerage = min(self.brokerage_flat, turnover * self.brokerage_pct / 100)
        stt = turnover * self.stt_sell_pct / 100 if side == Side.SELL else 0.0
        stamp = turnover * self.STAMP_BUY_PCT / 100 if side == Side.BUY else 0.0
        exchange = turnover * self.EXCHANGE_TXN_PCT / 100
        sebi = turnover * self.SEBI_FEE_PER_CRORE / 1e7
        gst = (brokerage + exchange + sebi) * self.GST_PCT / 100
        parts = dict(brokerage=brokerage, stt=stt, exchange=exchange, sebi=sebi, stamp=stamp, gst=gst)
        parts["total"] = sum(parts.values())
        return parts

    def charges(self, side: Side, price: float, qty: int) -> float:
        return round(self.breakdown(side, price, qty)["total"], 2)
