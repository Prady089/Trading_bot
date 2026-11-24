import type { ModelStats } from "@/lib/api";
import { pct } from "@/lib/format";

/** Honest summary of how the prediction model did on recent data it never saw. */
export default function ModelNote({ m }: { m: ModelStats }) {
  const edge = m.top5_avg_return_pct - m.market_avg_return_pct;
  return (
    <details className="model-note">
      <summary>
        <span>
          Model check: <strong>{m.direction_accuracy_pct?.toFixed(0) ?? "–"}%</strong> right on direction ·
          top 5 picks {edge >= 0 ? "beat" : <span className="down">trailed</span>} the market
        </span>
      </summary>
      <p className="small muted">
        The model predicts each stock&apos;s return over the next {m.horizon_minutes} minutes from recent price action
        (momentum, RSI, trend, volume, time of day{m.model && m.model !== "ridge_base" ? ", plus NIFTY/BANKNIFTY trend and India VIX" : ""}).
        Active model: <strong>{m.model ?? "ridge_base"}</strong>. Walk-forward tested on the latest {m.test_rows.toLocaleString("en-IN")} candles,
        each window predicted by a model trained only on earlier data:
      </p>
      <ul className="small">
        <li>
          Direction right: {m.direction_accuracy_pct?.toFixed(1)}% (50% = coin flip
          {m.always_up_pct != null && <>; always guessing &quot;up&quot; scored {m.always_up_pct.toFixed(1)}%</>})
        </li>
        {m.fold_ic && m.fold_ic.length > 0 && (
          <li>Skill (IC) in each of the last {m.fold_ic.length} test windows: {m.fold_ic.map((x) => x?.toFixed(2) ?? "–").join(", ")}. Consistently above 0 = real skill.</li>
        )}
        <li>Top-5 picks avg next-hour return: {pct(m.top5_avg_return_pct)} (hit rate {m.top5_hit_rate_pct.toFixed(0)}%)</li>
        <li>All NIFTY 50 avg: {pct(m.market_avg_return_pct)}</li>
      </ul>
      <p className="small muted">
        Treat predictions as weak hints, not guarantees. Each round trip costs about ₹40–60 in charges, so tiny
        predicted moves rarely pay. Paper trade for weeks before trusting it.
      </p>
    </details>
  );
}
