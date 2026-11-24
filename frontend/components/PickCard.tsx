"use client";

import { useState } from "react";
import { api, type Bot, type Pick } from "@/lib/api";
import { money, num, pct, signedMoney, tone } from "@/lib/format";

export default function PickCard({
  rank, pick, bot, manual, marketOpen, onTraded,
}: {
  rank: number;
  pick: Pick;
  bot: Bot | null;
  manual: boolean;
  marketOpen: boolean;
  onTraded: (msg: string, ok: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const [amount, setAmount] = useState(String(bot?.amount_per_trade ?? 20000));
  const [sl, setSl] = useState(String(bot?.stop_loss_pct ?? 0.75));
  const [tp, setTp] = useState(String(bot?.target_pct ?? 1.5));
  const [busy, setBusy] = useState(false);

  const qty = Math.floor(Number(amount || 0) / pick.last_price);
  const amt = Number(amount || 0);
  const expected = (amt * pick.predicted_return_pct) / 100;

  const order = async (side: "BUY" | "SELL") => {
    setBusy(true);
    try {
      const r = await api<{ position: { qty: number; avg_price: number }; market_open: boolean }>("/api/orders", {
        method: "POST",
        body: JSON.stringify({
          symbol: pick.symbol, side, amount: amt,
          stop_loss_pct: sl ? Number(sl) : null, target_pct: tp ? Number(tp) : null,
        }),
      });
      onTraded(
        `${side === "BUY" ? "Bought" : "Sold short"} ${Math.abs(r.position.qty)} ${pick.symbol} @ ₹${num(r.position.avg_price)}` +
          (r.market_open ? "" : " (practice fill)"),
        true,
      );
      setOpen(false);
    } catch (e) {
      onTraded((e as Error).message, false);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={`pick ${open ? "open" : ""}`}>
      <button className="pick-head" onClick={() => manual && setOpen(!open)} disabled={!manual} aria-expanded={open}>
        <span className="rank">{rank}</span>
        <span className="pick-main">
          <span className="pick-sym">
            {pick.symbol} {pick.held && <span className="pill long">HELD</span>}
          </span>
          <span className="muted small">
            {money(pick.last_price, true)} · <span className={tone(pick.change_today_pct)}>{pct(pick.change_today_pct)} today</span>
          </span>
        </span>
        <span className="pick-pred">
          <span className={`pred ${tone(pick.predicted_return_pct)}`}>{pct(pick.predicted_return_pct)}</span>
          <span className="muted small">{signedMoney(pick.predicted_profit)} / 1h</span>
        </span>
      </button>
      <div className="tags">
        {pick.signals.map((s) => <span key={s} className="tagchip">{s}</span>)}
      </div>

      {open && manual && (
        <div className="order">
          <div className="order-grid">
            <label>Amount ₹<input type="number" inputMode="decimal" min="0" value={amount} onChange={(e) => setAmount(e.target.value)} /></label>
            <label>Stop-loss %<input type="number" inputMode="decimal" step="0.1" min="0" value={sl} onChange={(e) => setSl(e.target.value)} /></label>
            <label>Target %<input type="number" inputMode="decimal" step="0.1" min="0" value={tp} onChange={(e) => setTp(e.target.value)} /></label>
          </div>
          <p className="muted small">
            {qty > 0 ? <>{qty} shares ≈ {money(qty * pick.last_price)}. Model expects {signedMoney(expected)} in 1 hour, before ~₹50 charges.</>
              : <>Amount too small for 1 share.</>}
            {!marketOpen && <> Market closed: fills at the last traded price.</>}
          </p>
          <div className="order-actions">
            <button className="btn buy" disabled={busy || qty <= 0 || pick.held} onClick={() => order("BUY")}>Buy</button>
            <button className="btn sell" disabled={busy || qty <= 0 || pick.held} onClick={() => order("SELL")}>Sell short</button>
          </div>
        </div>
      )}
    </div>
  );
}
