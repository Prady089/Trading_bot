"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, type Run } from "@/lib/api";
import { istTime, pct, tone } from "@/lib/format";

export default function RunsPage() {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api<Run[]>("/api/runs?limit=100").then(setRuns).catch((e) => setErr(e.message));
  }, []);

  return (
    <>
      <header className="page-head">
        <div>
          <h1>History</h1>
          <p className="muted">Every backtest and paper-trading session, so you can compare strategies.</p>
        </div>
      </header>
      {err && <div className="alert">{err}</div>}
      {runs && !runs.length && <div className="empty">No runs yet. Run a backtest to get started.</div>}
      {runs && runs.length > 0 && (
        <section className="card">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>#</th><th>Type</th><th>Strategy</th><th>Setup</th>
                  <th className="r">Return</th><th className="r">vs B&H</th><th className="r">Trades</th>
                  <th className="r">Win %</th><th className="r">PF</th><th>When</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => {
                  const m = r.metrics;
                  const beat = m?.benchmark_return_pct != null ? m.total_return_pct - m.benchmark_return_pct : null;
                  return (
                    <tr key={r.id}>
                      <td><Link href={`/runs/${r.id}`}>{r.id}</Link></td>
                      <td><span className={`pill ${r.kind === "paper" ? "long" : ""}`}>{r.kind}</span></td>
                      <td><Link href={`/runs/${r.id}`}><strong>{r.strategy}</strong></Link></td>
                      <td className="small">{r.interval}{r.period ? ` · ${r.period}` : ""} · {r.symbols.length} symbols</td>
                      <td className={`r ${tone(m?.total_return_pct)}`}>{pct(m?.total_return_pct)}</td>
                      <td className={`r ${tone(beat)}`}>{pct(beat)}</td>
                      <td className="r">{m?.num_trades ?? "–"}</td>
                      <td className="r">{m?.win_rate_pct?.toFixed(1) ?? "–"}</td>
                      <td className="r">{m?.profit_factor?.toFixed(2) ?? "–"}</td>
                      <td className="small muted">{istTime(r.created_at)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  );
}
