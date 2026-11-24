"use client";

import Link from "next/link";
import type { Bot, EventRow, Portfolio, ScannerResult, Status } from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { istTime, money, pct, signedMoney, tone } from "@/lib/format";

export default function HomePage() {
  const status = usePoll<Status>("/api/status", 30_000);
  const pf = usePoll<Portfolio>("/api/portfolio", 15_000);
  const scan = usePoll<ScannerResult>("/api/scanner?limit=3", 60_000);
  const bot = usePoll<Bot>("/api/bot", 30_000);
  const activity = usePoll<EventRow[]>("/api/activity?limit=6", 20_000);
  const p = pf.data;
  const st = status.data;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Home</h1>
          <p className="muted small">
            {st ? `${istTime(st.server_time_ist)} IST · ${st.market_open ? "NSE is open until 15:30" : "NSE is closed (opens 09:15 on weekdays)"}` : "Connecting…"}
          </p>
        </div>
      </div>

      {status.error && (
        <div className="alert">
          Can&apos;t reach the trading server ({status.error}). Make sure the backend is running.
        </div>
      )}

      {p && (
        <Link href="/portfolio" className="card hero-card">
          <div className="metric-label">Paper account value</div>
          <div className="big">{money(p.equity)}</div>
          <div className={`small ${tone(p.equity - p.initial_capital)}`}>
            {signedMoney(p.equity - p.initial_capital)} ({pct(p.total_return_pct)}) all time
          </div>
          <div className="mini-stats">
            <div><span className="muted small">Today</span><strong className={tone(p.today_realized_pnl)}>{signedMoney(p.today_realized_pnl)}</strong></div>
            <div><span className="muted small">Open trades</span><strong>{p.positions.length}</strong></div>
            <div><span className="muted small">Open P&L</span><strong className={tone(p.unrealized_pnl)}>{signedMoney(p.unrealized_pnl)}</strong></div>
          </div>
        </Link>
      )}

      {bot.data && (
        <Link href="/trading" className={`card bot-card ${bot.data.auto_enabled ? "on" : ""}`}>
          <div>
            <div className="strong">{bot.data.auto_enabled ? "🤖 Auto bot is ON" : "Auto bot is OFF"}</div>
            <div className="muted small">
              {bot.data.auto_enabled
                ? `Trading ₹${bot.data.amount_per_trade.toLocaleString("en-IN")} per pick · target ${bot.data.target_pct}% · stop ${bot.data.stop_loss_pct}%`
                : "Turn it on in Trading to let the bot pick and trade stocks for you"}
            </div>
          </div>
          <span className="chev">›</span>
        </Link>
      )}

      <section className="card">
        <div className="row-between">
          <h2>Top picks right now</h2>
          <Link href="/trading" className="small">See top 5 →</Link>
        </div>
        {scan.data?.ready ? (
          <ul className="list">
            {scan.data.stocks.map((s, i) => (
              <li key={s.symbol} className="list-row">
                <div className="list-main">
                  <strong>{i + 1}. {s.symbol}</strong>
                  <div className="muted small">{money(s.last_price, true)} · {s.signals.slice(0, 2).join(" · ")}</div>
                </div>
                <div className="list-side">
                  <div className={`strong ${tone(s.predicted_return_pct)}`}>{pct(s.predicted_return_pct)}</div>
                  <div className="muted small">predicted 1h</div>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <div className="empty">{scan.data?.error ?? "Scanning NIFTY 50…"}</div>
        )}
      </section>

      {activity.data && activity.data.length > 0 && (
        <section className="card">
          <h2>Recent activity</h2>
          <ul className="log">
            {activity.data.map((e, i) => (
              <li key={i} className={e.level}><span className="muted small">{istTime(e.ts)}</span> {e.message}</li>
            ))}
          </ul>
        </section>
      )}

      <section className="card">
        <h2>How it works</h2>
        <ol className="steps small">
          <li><strong>Scan.</strong> Every 15 minutes the model scores all NIFTY 50 stocks and predicts their return over the next hour.</li>
          <li><strong>Trade.</strong> In <em>Manual</em> you pick a stock and buy or sell. In <em>Auto</em> the bot buys the top picks using the rules you set in Settings.</li>
          <li><strong>Exit.</strong> Every trade closes at its target, stop-loss or time limit, or at the 15:15 intraday square-off.</li>
          <li><strong>Measure.</strong> Portfolio tracks every rupee, including real NSE charges, so you can see whether the strategy actually works.</li>
        </ol>
        <p className="muted small">All money here is simulated. Prices come from Yahoo Finance and can lag by a few minutes.</p>
      </section>
    </>
  );
}
