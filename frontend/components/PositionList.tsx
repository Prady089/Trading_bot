"use client";

import { useState } from "react";
import { api, type AccountPosition } from "@/lib/api";
import { istTime, money, num, pct, signedMoney, tone } from "@/lib/format";

export default function PositionList({
  positions, onChange, empty = "No open positions.",
}: {
  positions: AccountPosition[];
  onChange: (msg: string, ok: boolean) => void;
  empty?: string;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  if (!positions.length) return <div className="empty">{empty}</div>;

  const close = async (sym: string) => {
    setBusy(sym);
    try {
      const t = await api<{ net_pnl: number; return_pct: number }>(`/api/positions/${encodeURIComponent(sym)}/close`, { method: "POST" });
      onChange(`Closed ${sym}: ${signedMoney(t.net_pnl)} (${pct(t.return_pct)})`, true);
    } catch (e) {
      onChange((e as Error).message, false);
    } finally {
      setBusy(null);
    }
  };

  return (
    <ul className="list">
      {positions.map((p) => (
        <li key={p.symbol} className="list-row">
          <div className="list-main">
            <div>
              <strong>{p.symbol}</strong>{" "}
              <span className={`pill ${p.side === "LONG" ? "long" : "short"}`}>{p.side === "LONG" ? "BUY" : "SHORT"}</span>{" "}
              <span className="pill">{p.source.toUpperCase()}</span>
            </div>
            <div className="muted small">
              {p.instrument === "FUT"
                ? <>{p.lots} lot(s) ({Math.abs(p.qty)}) × {num(p.avg_price)} · margin {money(p.invested)}</>
                : <>{Math.abs(p.qty)} × {num(p.avg_price)}</>}
              {" "}· LTP {num(p.last_price)} · {istTime(p.entry_ts)}
            </div>
            <div className="muted small">
              SL {p.stop_price ? num(p.stop_price) : "none"} · Target {p.target_price ? num(p.target_price) : "none"}
            </div>
          </div>
          <div className="list-side">
            <div className={`strong ${tone(p.unrealized_pnl)}`}>{signedMoney(p.unrealized_pnl)}</div>
            <div className={`small ${tone(p.unrealized_pct)}`}>{pct(p.unrealized_pct)}</div>
            <button className="btn tiny" disabled={busy === p.symbol} onClick={() => close(p.symbol)}>
              {busy === p.symbol ? "…" : "Close"}
            </button>
          </div>
        </li>
      ))}
    </ul>
  );
}
