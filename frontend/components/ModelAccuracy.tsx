"use client";

import { useState } from "react";
import { api, type ModelAccuracy as Acc } from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { istTime, pct, tone } from "@/lib/format";

const fmt = (v: number | null | undefined, unit = "%") => (v == null ? "–" : `${v.toFixed(1)}${unit}`);
const ic = (v: number | null | undefined) => (v == null ? "–" : v.toFixed(3));

/** Live scorecard: every forecast is checked 1 hour later against what the stock really did. */
export default function ModelAccuracy({ onMessage }: { onMessage?: (msg: string, ok: boolean) => void }) {
  const { data, error, reload } = usePoll<Acc>("/api/model/accuracy", 60_000);
  const [busy, setBusy] = useState<string | null>(null);
  if (error) return <div className="alert">Model accuracy unavailable: {error}</div>;
  if (!data) return <div className="empty">Loading…</div>;
  const { live, trades, leaderboard, promotion_rule: rule } = data;
  const edge = live.top5_avg_return_pct != null && live.market_avg_return_pct != null
    ? live.top5_avg_return_pct - live.market_avg_return_pct : null;
  const pending = live.counts.total - live.counts.resolved;

  const promote = async (model: string) => {
    setBusy(model);
    try {
      await api("/api/model/champion", { method: "POST", body: JSON.stringify({ model }) });
      onMessage?.(`${model} is now the active model. Picks will re-rank in ~20 seconds.`, true);
      reload();
    } catch (e) {
      onMessage?.((e as Error).message, false);
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <p className="small muted">
        Every 15 min each model forecasts all NIFTY 50 stocks plus NIFTY and BANKNIFTY; each forecast is scored
        1 hour later. Active model: <strong>{data.champion}</strong>. To count as skill, a model has to beat
        &quot;always up&quot;, not just 50%.
      </p>
      <div className="mini-stats">
        <div><span className="muted small">Live direction right</span><strong>{fmt(live.direction_accuracy_pct)}</strong>
          <span className="muted small">always-up {fmt(live.always_up_pct)}</span></div>
        <div><span className="muted small">Top-5 edge vs market</span><strong className={tone(edge)}>{pct(edge)}</strong></div>
        <div><span className="muted small">Trades AI got right</span>
          <strong>{fmt(trades.all.model_accuracy_pct)}</strong>
          <span className="muted small">{trades.all.model_right}/{trades.all.scored_trades} trades</span></div>
        <div><span className="muted small">NIFTY direction</span><strong>{fmt(live.index?.NIFTY?.direction_accuracy_pct)}</strong>
          <span className="muted small">{live.index?.NIFTY?.forecasts ?? 0} forecasts</span></div>
      </div>
      <p className="small muted">
        {live.counts.resolved.toLocaleString("en-IN")} forecasts scored over {live.candles} candles
        {pending > 0 && ` · ${pending} waiting for their 1-hour result`}. Need a few hundred candles (≈2 weeks) before the number means much.
      </p>

      <h3 className="small">Model leaderboard</h3>
      <ul className="list">
        {leaderboard.map((r) => (
          <li key={r.model} className="list-row">
            <div className="list-main">
              <div><strong>{r.model}</strong> {r.champion && <span className="pill long">ACTIVE</span>}</div>
              <div className="muted small">{r.description}</div>
              <div className="small">
                <span className="muted">Walk-forward:</span> {fmt(r.walk_forward.direction_accuracy_pct)} right
                (always-up {fmt(r.walk_forward.always_up_pct)}) · IC {ic(r.walk_forward.information_coefficient)}
              </div>
              <div className="small">
                <span className="muted">Live:</span> {fmt(r.live.direction_accuracy_pct)} right · IC {ic(r.live.information_coefficient)}
                {" "}· top-5 {pct(r.live.top5_avg_return_pct)} · {r.live.candles} candles
              </div>
            </div>
            <div className="list-side">
              {!r.champion && (
                <button className="btn tiny" disabled={busy !== null} onClick={() => promote(r.model)}>
                  {busy === r.model ? "…" : "Use"}
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
      <p className="small muted">
        Auto-switch rule: a challenger becomes active only after {rule.min_candles}+ live candles with an IC at
        least {rule.ic_margin} higher than the active model&apos;s, and top picks at least as good. IC (information
        coefficient) is the correlation between predicted and actual moves: 0 = no skill, 0.03–0.05 = useful,
        above 0.1 on 1-hour moves is suspicious.
      </p>

      {live.by_day.length > 0 && (
        <>
          <h3 className="small">By day ({live.model})</h3>
          <ul className="list">
            {live.by_day.slice().reverse().map((d) => (
              <li key={d.day} className="list-row">
                <div className="list-main"><strong>{d.day}</strong>
                  <div className="muted small">{d.candles} candles · top-5 avg {pct(d.top5_avg_return_pct)} vs market {pct(d.market_avg_return_pct)}</div></div>
                <div className="list-side"><strong>{fmt(d.direction_accuracy_pct)}</strong>
                  <div className="muted small">up {fmt(d.always_up_pct)}</div></div>
              </li>
            ))}
          </ul>
        </>
      )}

      {live.recent_top_picks.length > 0 && (
        <details>
          <summary className="small">Recent top picks: forecast vs actual</summary>
          <ul className="list">
            {live.recent_top_picks.map((r) => {
              const right = r.actual_return_pct !== 0 && (r.predicted_return_pct > 0) === (r.actual_return_pct > 0);
              return (
                <li key={r.bar_ts + r.symbol} className="list-row">
                  <div className="list-main"><strong>#{r.rank} {r.symbol}</strong>
                    <div className="muted small">{istTime(r.bar_ts)} · said {pct(r.predicted_return_pct)}</div></div>
                  <div className="list-side">
                    <strong className={tone(r.actual_return_pct)}>{pct(r.actual_return_pct)}</strong>
                    <div className={`small ${right ? "up" : "down"}`}>{right ? "✓" : "✗"}</div>
                  </div>
                </li>
              );
            })}
          </ul>
        </details>
      )}
    </>
  );
}
