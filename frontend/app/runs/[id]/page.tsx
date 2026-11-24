"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import EquityChart from "@/components/EquityChart";
import MetricsGrid from "@/components/MetricsGrid";
import TradesTable from "@/components/TradesTable";
import { api, type EquityPoint, type Run, type Trade } from "@/lib/api";
import { istTime } from "@/lib/format";

export default function RunDetail() {
  const { id } = useParams<{ id: string }>();
  const [run, setRun] = useState<Run | null>(null);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [equity, setEquity] = useState<EquityPoint[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      api<Run>(`/api/runs/${id}`),
      api<Trade[]>(`/api/runs/${id}/trades`),
      api<EquityPoint[]>(`/api/runs/${id}/equity`),
    ])
      .then(([r, t, e]) => {
        setRun(r);
        setTrades(t);
        setEquity(e);
      })
      .catch((e) => setErr(e.message));
  }, [id]);

  if (err) return <div className="alert">{err}</div>;
  if (!run) return <div className="empty">Loading…</div>;

  return (
    <>
      <header className="page-head">
        <div>
          <Link href="/runs" className="small">← History</Link>
          <h1>Run #{run.id}: {run.strategy}</h1>
          <p className="muted">
            {run.kind} · {run.interval}{run.period ? ` · ${run.period}` : ""} · {run.symbols.join(", ")} · {istTime(run.created_at)}
          </p>
        </div>
      </header>
      {run.metrics && (
        <section className="card">
          <MetricsGrid m={run.metrics} />
        </section>
      )}
      <section className="card">
        <h2>Equity</h2>
        <EquityChart points={equity} initial={run.initial_capital} />
      </section>
      <section className="card">
        <h2>Trades ({trades.length})</h2>
        <TradesTable trades={trades} limit={500} />
      </section>
    </>
  );
}
