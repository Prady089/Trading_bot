"use client";

import type { AccountTrade, ShadowAccount, ShadowSummary } from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { istTime, money, num, pct, signedMoney, tone } from "@/lib/format";

type Row = { key: string; title: string; net: number; open: number; trades: number; win: number | null; charges: number };

const winRate = (ts: { net_pnl: number }[]) =>
  ts.length ? Math.round((ts.filter((t) => t.net_pnl > 0).length / ts.length) * 1000) / 10 : null;

/** Side-by-side live paper test: each rule-based strategy in its own Rs 5 lakh account, plus the AI bot. */
export default function ShadowAccounts({ aiTrades }: { aiTrades: AccountTrade[] }) {
  const { data, error } = usePoll<ShadowSummary>("/api/shadow", 60_000);
  if (error) return <div className="alert">Live test unavailable: {error}</div>;
  if (!data) return <div className="empty">Loading…</div>;
  if (!data.accounts.length) return <div className="empty">Starting up: the first replay takes about a minute.</div>;

  const start = data.accounts.map((a) => a.start_date).sort()[0];
  const ai = aiTrades.filter((t) => t.exit_ts.slice(0, 10) >= start);
  const rows: Row[] = [
    ...data.accounts.map((a) => ({
      key: a.id, title: a.title, net: a.realized_pnl + a.unrealized_pnl, open: a.positions.length,
      trades: a.metrics.num_trades, win: a.metrics.win_rate_pct, charges: a.metrics.total_charges,
    })),
    {
      key: "ai", title: "🤖 AI bot (Auto)", net: ai.reduce((s, t) => s + t.net_pnl, 0), open: 0,
      trades: ai.length, win: winRate(ai), charges: ai.reduce((s, t) => s + t.charges, 0),
    },
  ].sort((x, y) => y.net - x.net);

  return (
    <>
      <p className="muted small">
        Since {start}, each strategy trades live NIFTY 50 prices in its own separate ₹5 lakh paper account, with full charges.
        Same days, same stocks, so the comparison is fair. Updated {data.updated_at ? istTime(data.updated_at) : "–"}.
        Give it a few weeks before reading much into it.
      </p>
      <ul className="list">
        {rows.map((r, i) => (
          <li key={r.key} className="list-row">
            <div className="list-main">
              <strong>#{i + 1} {r.title}</strong>
              <div className="muted small">
                {r.trades} closed trades · win {r.win == null ? "–" : `${r.win}%`} · charges {money(r.charges)}
                {r.open > 0 && ` · ${r.open} open`}
              </div>
            </div>
            <div className="list-side"><strong className={tone(r.net)}>{signedMoney(r.net)}</strong>
              <span className="muted small">incl. open</span></div>
          </li>
        ))}
      </ul>
      {data.accounts.map((a) => <AccountDetail key={a.id} a={a} />)}
      {data.error && <p className="small warn-text">Last update failed: {data.error}</p>}
    </>
  );
}

function AccountDetail({ a }: { a: ShadowAccount }) {
  const m = a.metrics;
  return (
    <details className="model-note">
      <summary><strong>{a.title}</strong> · {money(a.equity)} <span className={tone(a.equity - a.initial_capital)}>({pct((a.equity / a.initial_capital - 1) * 100)})</span></summary>
      <p className="small muted">{a.note} Prices up to {a.data_as_of ? istTime(a.data_as_of) : "–"}.</p>
      <div className="mini-stats">
        <div><span className="muted small">Realized</span><strong className={tone(a.realized_pnl)}>{signedMoney(a.realized_pnl)}</strong></div>
        <div><span className="muted small">Open P&L</span><strong className={tone(a.unrealized_pnl)}>{signedMoney(a.unrealized_pnl)}</strong></div>
        <div><span className="muted small">Profit factor</span><strong>{m.profit_factor == null ? "–" : num(m.profit_factor)}</strong></div>
        <div><span className="muted small">Max drawdown</span><strong>{pct(-m.max_drawdown_pct)}</strong></div>
      </div>
      {a.positions.length > 0 && (
        <>
          <h3 className="small">Open positions</h3>
          <ul className="list">
            {a.positions.map((p) => (
              <li key={p.symbol} className="list-row">
                <div className="list-main"><strong>{p.symbol}</strong> <span className={`pill ${p.side === "LONG" ? "long" : "short"}`}>{p.side}</span>
                  <div className="muted small">{p.qty} × {num(p.entry_price)} → {num(p.last_price)}</div></div>
                <div className="list-side"><strong className={tone(p.unrealized_pnl)}>{signedMoney(p.unrealized_pnl)}</strong></div>
              </li>
            ))}
          </ul>
        </>
      )}
      {a.trades.length > 0 && (
        <>
          <h3 className="small">Recent closed trades</h3>
          <ul className="list">
            {a.trades.slice(0, 10).map((t) => (
              <li key={`${t.symbol}${t.entry_ts}`} className="list-row">
                <div className="list-main"><strong>{t.symbol}</strong> <span className="muted small">{t.direction > 0 ? "LONG" : "SHORT"}</span>
                  <div className="muted small">{istTime(t.entry_ts)} → {istTime(t.exit_ts)} · {t.exit_reason}</div></div>
                <div className="list-side"><strong className={tone(t.net_pnl)}>{signedMoney(t.net_pnl)}</strong></div>
              </li>
            ))}
          </ul>
        </>
      )}
    </details>
  );
}
