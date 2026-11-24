import type { Metrics } from "@/lib/api";
import { money, num, pct, signedMoney, tone } from "@/lib/format";

export default function MetricsGrid({ m }: { m: Metrics }) {
  const beat = m.benchmark_return_pct != null ? m.total_return_pct - m.benchmark_return_pct : null;
  const items: [string, string, string, string?][] = [
    ["Net P&L", signedMoney(m.net_pnl), tone(m.net_pnl), `${pct(m.total_return_pct)} return`],
    ["Buy & hold", pct(m.benchmark_return_pct), tone(m.benchmark_return_pct),
      beat == null ? undefined : `strategy ${beat >= 0 ? "beat" : "lagged"} by ${Math.abs(beat).toFixed(2)}%`],
    ["Trades", String(m.num_trades), "", `${m.trading_days} trading days`],
    ["Win rate", m.win_rate_pct == null ? "–" : `${m.win_rate_pct.toFixed(1)}%`, "", "read with profit factor"],
    ["Profit factor", num(m.profit_factor), m.profit_factor == null ? "" : m.profit_factor >= 1 ? "up" : "down", "> 1.0 = profitable"],
    ["Expectancy", signedMoney(m.expectancy), tone(m.expectancy), "avg net P&L / trade"],
    ["Max drawdown", `${m.max_drawdown_pct.toFixed(2)}%`, m.max_drawdown_pct > 0 ? "down" : "", "worst peak-to-trough"],
    ["Sharpe", num(m.sharpe), tone(m.sharpe), "annualised, daily"],
    ["Charges paid", money(m.total_charges), "", `gross P&L ${signedMoney(m.gross_pnl)}`],
  ];
  return (
    <div className="metrics">
      {items.filter(([label]) => label !== "Buy & hold" || m.benchmark_return_pct != null).map(([label, value, t, sub]) => (
        <div className="metric" key={label}>
          <div className="metric-label">{label}</div>
          <div className={`metric-value ${t}`}>{value}</div>
          {sub && <div className="metric-sub">{sub}</div>}
        </div>
      ))}
    </div>
  );
}
