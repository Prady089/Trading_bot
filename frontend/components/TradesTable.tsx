import type { Trade } from "@/lib/api";
import { istTime, num, signedMoney, tone } from "@/lib/format";

export default function TradesTable({ trades, limit = 200 }: { trades: Trade[]; limit?: number }) {
  if (!trades.length) return <div className="empty">No completed trades yet.</div>;
  const rows = [...trades].reverse().slice(0, limit);
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Side</th>
            <th className="r">Qty</th>
            <th>Entry</th>
            <th>Exit</th>
            <th className="r">Net P&L</th>
            <th>Exit reason</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((t) => (
            <tr key={t.id}>
              <td><strong>{t.symbol}</strong></td>
              <td><span className={`pill ${t.direction > 0 ? "long" : "short"}`}>{t.direction > 0 ? "LONG" : "SHORT"}</span></td>
              <td className="r">{t.qty}</td>
              <td>
                {num(t.entry_price)}
                <div className="muted small">{istTime(t.entry_ts)}</div>
              </td>
              <td>
                {num(t.exit_price)}
                <div className="muted small">{istTime(t.exit_ts)}</div>
              </td>
              <td className={`r ${tone(t.net_pnl)}`}>
                {signedMoney(t.net_pnl)}
                <div className="muted small">fees {num(t.charges)}</div>
              </td>
              <td className="small">{t.exit_reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {trades.length > limit && <div className="muted small pad">Showing latest {limit} of {trades.length}</div>}
    </div>
  );
}
