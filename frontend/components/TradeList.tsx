import type { AccountTrade } from "@/lib/api";
import { istTime, num, pct, signedMoney, tone } from "@/lib/format";

export default function TradeList({ trades, empty = "No closed trades yet." }: { trades: AccountTrade[]; empty?: string }) {
  if (!trades.length) return <div className="empty">{empty}</div>;
  return (
    <ul className="list">
      {trades.map((t) => (
        <li key={t.id} className="list-row">
          <div className="list-main">
            <div>
              <strong>{t.symbol}</strong>{" "}
              <span className={`pill ${t.direction > 0 ? "long" : "short"}`}>{t.direction > 0 ? "BUY" : "SHORT"}</span>{" "}
              {t.source && <span className="pill">{t.source.toUpperCase()}</span>}
            </div>
            <div className="muted small">
              {t.qty} × {num(t.entry_price)} → {num(t.exit_price)} · {istTime(t.exit_ts)}
            </div>
            <div className="muted small">{t.exit_reason}</div>
            {t.predicted_return_pct != null && (
              <div className="small">
                <span className="muted">AI said {pct(t.predicted_return_pct)} · moved {pct(t.price_move_pct)}</span>{" "}
                {t.model_correct != null && (
                  <span className={t.model_correct ? "up" : "down"}>{t.model_correct ? "✓ right" : "✗ wrong"}</span>
                )}
              </div>
            )}
          </div>
          <div className="list-side">
            <div className={`strong ${tone(t.net_pnl)}`}>{signedMoney(t.net_pnl)}</div>
            <div className={`small ${tone(t.return_pct)}`}>{pct(t.return_pct)}</div>
          </div>
        </li>
      ))}
    </ul>
  );
}
