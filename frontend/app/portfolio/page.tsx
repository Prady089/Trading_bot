"use client";

import { useState } from "react";
import EquityChart from "@/components/EquityChart";
import MetricsGrid from "@/components/MetricsGrid";
import ModelAccuracy from "@/components/ModelAccuracy";
import PositionList from "@/components/PositionList";
import TradeList from "@/components/TradeList";
import { useToast } from "@/components/Toast";
import type { AccountTrade, EquityPoint, Portfolio } from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { money, pct, signedMoney, tone } from "@/lib/format";

type Filter = "" | "auto" | "manual";

export default function PortfolioPage() {
  const [filter, setFilter] = useState<Filter>("");
  const pf = usePoll<Portfolio>("/api/portfolio", 15_000);
  const trades = usePoll<AccountTrade[]>(`/api/trades?limit=200${filter ? `&source=${filter}` : ""}`, 30_000);
  const equity = usePoll<EquityPoint[]>("/api/equity", 60_000);
  const { show, node: toast } = useToast();
  const p = pf.data;

  const changed = (msg: string, ok: boolean) => {
    show(msg, ok);
    pf.reload();
    trades.reload();
    equity.reload();
  };

  return (
    <>
      <div className="page-head"><h1>Portfolio</h1></div>
      {pf.error && <div className="alert">Can&apos;t reach the backend: {pf.error}</div>}
      {!p && !pf.error && <div className="empty">Loading…</div>}

      {p && (
        <>
          <section className="card">
            <div className="metric-label">Account value</div>
            <div className="big">{money(p.equity)}</div>
            <div className={`small ${tone(p.equity - p.initial_capital)}`}>
              {signedMoney(p.equity - p.initial_capital)} ({pct(p.total_return_pct)}) since start · started with {money(p.initial_capital)}
            </div>
            <div className="mini-stats">
              <div><span className="muted small">Today</span><strong className={tone(p.today_realized_pnl)}>{signedMoney(p.today_realized_pnl)}</strong></div>
              <div><span className="muted small">Open P&L</span><strong className={tone(p.unrealized_pnl)}>{signedMoney(p.unrealized_pnl)}</strong></div>
              <div><span className="muted small">Cash</span><strong>{money(p.cash)}</strong></div>
              <div><span className="muted small">Invested</span><strong>{money(p.invested)}</strong></div>
            </div>
          </section>

          <section className="card">
            <h2>Auto vs Manual</h2>
            <div className="split">
              {(["auto", "manual"] as const).map((k) => (
                <div key={k} className="split-col">
                  <div className="metric-label">{k === "auto" ? "🤖 Auto bot" : "✋ Manual"}</div>
                  <div className={`metric-value ${tone(p.by_source[k].net_pnl)}`}>{signedMoney(p.by_source[k].net_pnl)}</div>
                  <div className="muted small">
                    {p.by_source[k].trades} trades · win rate {p.by_source[k].win_rate_pct ?? "–"}{p.by_source[k].win_rate_pct != null && "%"}
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section className="card">
            <h2>Open positions ({p.positions.length})</h2>
            <PositionList positions={p.positions} onChange={changed} />
          </section>

          <section className="card">
            <h2>🧠 AI model accuracy</h2>
            <ModelAccuracy onMessage={show} />
          </section>

          {(equity.data?.length ?? 0) > 1 && (
            <section className="card">
              <h2>Account value over time</h2>
              <EquityChart points={equity.data!} initial={p.initial_capital} />
            </section>
          )}

          {p.metrics.num_trades > 0 && (
            <section className="card">
              <h2>Performance</h2>
              <MetricsGrid m={p.metrics} />
            </section>
          )}

          <section className="card">
            <div className="row-between">
              <h2>Trade history</h2>
              <div className="segmented small-seg">
                {([["", "All"], ["auto", "Auto"], ["manual", "Manual"]] as [Filter, string][]).map(([k, label]) => (
                  <button key={label} className={filter === k ? "on" : ""} onClick={() => setFilter(k)}>{label}</button>
                ))}
              </div>
            </div>
            <TradeList trades={trades.data ?? []} />
          </section>
        </>
      )}
      {toast}
    </>
  );
}
