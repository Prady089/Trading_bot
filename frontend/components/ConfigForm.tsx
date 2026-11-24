"use client";

import { useEffect, useState } from "react";
import { api, type Meta } from "@/lib/api";

export type RunConfig = {
  strategy: string;
  symbols: string[];
  interval: string;
  period?: string;
  stop_loss_pct?: number;
  take_profit_pct?: number;
};

const PERIODS: Record<string, string[]> = {
  "1m": ["1d", "5d", "7d"],
  "5m": ["5d", "30d", "60d"],
  "15m": ["5d", "30d", "60d"],
  "30m": ["5d", "30d", "60d"],
  "1h": ["60d", "6mo", "1y", "2y"],
  "1d": ["6mo", "1y", "2y", "5y", "10y"],
};

export default function ConfigForm({
  mode, busy, submitLabel, onSubmit,
}: {
  mode: "backtest" | "live";
  busy: boolean;
  submitLabel: string;
  onSubmit: (c: RunConfig) => void;
}) {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [strategy, setStrategy] = useState("opening_range");
  const [symbols, setSymbols] = useState("");
  const [interval, setInterval_] = useState("15m");
  const [period, setPeriod] = useState("60d");
  const [sl, setSl] = useState("");
  const [tp, setTp] = useState("");

  useEffect(() => {
    api<Meta>("/api/meta")
      .then((m) => {
        setMeta(m);
        const want = new URLSearchParams(window.location.search).get("strategy");
        if (want && m.strategies.some((s) => s.name === want)) setStrategy(want);
        setSymbols(m.default_symbols.slice(0, 5).join(", "));
        setSl(String(m.settings.default_stop_loss_pct));
        setTp(String(m.settings.default_take_profit_pct));
      })
      .catch((e) => setErr(`Can't reach the backend: ${e.message}`));
  }, []);

  const intervals = (meta?.intervals ?? ["15m"]).filter((i) => mode === "backtest" || i !== "1d");
  const periods = PERIODS[interval] ?? ["60d"];
  const desc = meta?.strategies.find((s) => s.name === strategy)?.description;

  if (err) return <div className="alert">{err}</div>;

  return (
    <form
      className="form"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit({
          strategy,
          symbols: symbols.split(/[\s,]+/).map((s) => s.trim().toUpperCase()).filter(Boolean),
          interval,
          ...(mode === "backtest" ? {
            period,
            stop_loss_pct: sl ? Number(sl) : undefined,
            take_profit_pct: tp ? Number(tp) : undefined,
          } : {}),
        });
      }}
    >
      <label>
        Strategy
        <select value={strategy} onChange={(e) => setStrategy(e.target.value)}>
          {meta?.strategies.map((s) => <option key={s.name} value={s.name}>{s.name}</option>)}
        </select>
      </label>
      {desc && <p className="muted small hint">{desc}</p>}
      <label className="wide">
        NSE symbols
        <input value={symbols} onChange={(e) => setSymbols(e.target.value)} placeholder="RELIANCE, TCS, INFY" />
      </label>
      <label>
        Candle
        <select
          value={interval}
          onChange={(e) => {
            setInterval_(e.target.value);
            setPeriod((PERIODS[e.target.value] ?? ["60d"]).slice(-1)[0]);
          }}
        >
          {intervals.map((i) => <option key={i}>{i}</option>)}
        </select>
      </label>
      {mode === "backtest" && (
        <>
          <label>
            History
            <select value={period} onChange={(e) => setPeriod(e.target.value)}>
              {periods.map((p) => <option key={p}>{p}</option>)}
            </select>
          </label>
          <label>
            Stop-loss %
            <input type="number" step="0.1" min="0.1" value={sl} onChange={(e) => setSl(e.target.value)} />
          </label>
          <label>
            Target %
            <input type="number" step="0.1" min="0.1" value={tp} onChange={(e) => setTp(e.target.value)} />
          </label>
        </>
      )}
      <button className="btn primary wide" disabled={busy || !meta}>{busy ? "Working…" : submitLabel}</button>
    </form>
  );
}
