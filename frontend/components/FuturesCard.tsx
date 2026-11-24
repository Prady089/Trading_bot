"use client";

import { useState } from "react";
import { api, type FuturesQuote } from "@/lib/api";
import { money, num, pct, signedMoney, tone } from "@/lib/format";

/** One index future (NIFTY / BANKNIFTY): forecast, lot economics and a lots-based order form. */
export default function FuturesCard({
  f, manual, marketOpen, onTraded,
}: {
  f: FuturesQuote;
  manual: boolean;
  marketOpen: boolean;
  onTraded: (msg: string, ok: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const [lots, setLots] = useState("1");
  const [sl, setSl] = useState("0.5");
  const [tp, setTp] = useState("1.0");
  const [busy, setBusy] = useState(false);

  const n = Math.max(0, Math.floor(Number(lots || 0)));
  const value = n * f.lot_value;
  const margin = n * f.margin_per_lot;
  const riskRs = (value * Number(sl || 0)) / 100;
  const rewardRs = (value * Number(tp || 0)) / 100;

  const order = async (side: "BUY" | "SELL") => {
    setBusy(true);
    try {
      const r = await api<{ position: { avg_price: number }; market_open: boolean }>("/api/orders", {
        method: "POST",
        body: JSON.stringify({
          symbol: f.symbol, side, lots: n,
          stop_loss_pct: sl ? Number(sl) : null, target_pct: tp ? Number(tp) : null,
        }),
      });
      onTraded(`${side === "BUY" ? "Bought" : "Sold"} ${n} lot(s) ${f.symbol} @ ${num(r.position.avg_price)}` +
        (r.market_open ? "" : " (practice fill)"), true);
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
        <span className="pick-main">
          <span className="pick-sym">{f.underlying} FUT {f.held && <span className="pill long">HELD</span>}</span>
          <span className="muted small">
            {f.last_price != null ? num(f.last_price) : "–"} · <span className={tone(f.change_today_pct)}>{pct(f.change_today_pct)} today</span>
          </span>
          <span className="muted small">Lot {f.lot_size} · 1 lot ≈ {money(f.lot_value)} · margin ≈ {money(f.margin_per_lot)}</span>
        </span>
        <span className="pick-pred">
          <span className={`pred ${tone(f.predicted_return_pct)}`}>{pct(f.predicted_return_pct)}</span>
          <span className="muted small">{signedMoney(f.predicted_profit_per_lot)} / lot / 1h</span>
        </span>
      </button>

      {open && manual && (
        <div className="order">
          <div className="order-grid">
            <label>Lots<input type="number" inputMode="numeric" min="1" step="1" value={lots} onChange={(e) => setLots(e.target.value)} /></label>
            <label>Stop-loss %<input type="number" inputMode="decimal" step="0.1" min="0" value={sl} onChange={(e) => setSl(e.target.value)} /></label>
            <label>Target %<input type="number" inputMode="decimal" step="0.1" min="0" value={tp} onChange={(e) => setTp(e.target.value)} /></label>
          </div>
          <p className="muted small">
            {n} lot(s) = {n * f.lot_size} units ≈ {money(value)} exposure, blocks ≈ {money(margin)} margin
            ({f.margin_pct}%). Stop risks ≈ <span className="down">{money(riskRs)}</span>, target pays ≈{" "}
            <span className="up">{money(rewardRs)}</span>, before charges.
            {f.affordable_lots < n && <> <span className="warn-text">You can afford {f.affordable_lots} lot(s) right now.</span></>}
            {!marketOpen && <> Market closed: fills at the last traded price.</>}
          </p>
          <div className="order-actions">
            <button className="btn buy" disabled={busy || n <= 0 || f.held} onClick={() => order("BUY")}>Buy</button>
            <button className="btn sell" disabled={busy || n <= 0 || f.held} onClick={() => order("SELL")}>Sell</button>
          </div>
        </div>
      )}
    </div>
  );
}
