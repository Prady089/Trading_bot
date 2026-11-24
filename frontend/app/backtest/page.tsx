"use client";

import { useState } from "react";
import Link from "next/link";
import ConfigForm, { type RunConfig } from "@/components/ConfigForm";
import EquityChart from "@/components/EquityChart";
import MetricsGrid from "@/components/MetricsGrid";
import TradesTable from "@/components/TradesTable";
import { api, type EquityPoint, type Metrics, type Trade } from "@/lib/api";

type Result = { run_id: number; metrics: Metrics; symbols_without_data: string[] };

export default function BacktestPage() {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [res, setRes] = useState<Result | null>(null);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [equity, setEquity] = useState<EquityPoint[]>([]);

  const run = async (c: RunConfig) => {
    setBusy(true);
    setErr(null);
    try {
      const r = await api<Result>("/api/backtests", { method: "POST", body: JSON.stringify(c) });
      const [t, e] = await Promise.all([
        api<Trade[]>(`/api/runs/${r.run_id}/trades`),
        api<EquityPoint[]>(`/api/runs/${r.run_id}/equity`),
      ]);
      setRes(r);
      setTrades(t);
      setEquity(e);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <header className="page-head">
        <div>
          <Link href="/settings" className="small">← Settings</Link>
          <h1>Backtest</h1>
          <p className="muted">
            Replay history through the same engine the live bot uses: next-bar fills, slippage and full NSE charges.
          </p>
        </div>
      </header>

      <section className="card">
        <ConfigForm mode="backtest" busy={busy} submitLabel="Run backtest" onSubmit={run} />
      </section>

      {err && <div className="alert">{err}</div>}

      {res && (
        <>
          {res.symbols_without_data.length > 0 && (
            <div className="alert">No data for: {res.symbols_without_data.join(", ")}</div>
          )}
          <section className="card">
            <div className="row-between">
              <h2>Results</h2>
              <Link href={`/runs/${res.run_id}`} className="small">Saved as run #{res.run_id} →</Link>
            </div>
            <MetricsGrid m={res.metrics} />
          </section>
          <section className="card">
            <h2>Equity</h2>
            <EquityChart points={equity} initial={res.metrics.initial_capital} />
          </section>
          <section className="card">
            <h2>Trades</h2>
            <TradesTable trades={trades} limit={100} />
          </section>
        </>
      )}
    </>
  );
}
