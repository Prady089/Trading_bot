"use client";

import Link from "next/link";
import ShadowAccounts from "@/components/ShadowAccounts";
import type { AccountTrade, Bot, Meta, Run } from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { pct, signedMoney, tone } from "@/lib/format";

/** Plain-language notes for the rule-based strategies (keyed by backend strategy name). */
const GUIDE: Record<string, { title: string; icon: string; how: string; good: string; bad: string }> = {
  ema_crossover: {
    title: "EMA crossover", icon: "📈",
    how: "Compares a fast average price (last 9 candles) with a slow one (last 21). Fast crossing above slow means an uptrend, so buy. Crossing below means a downtrend, so sell.",
    good: "Strong trending days.", bad: "Choppy, sideways markets: it keeps buying high and selling low.",
  },
  rsi_reversion: {
    title: "RSI reversion", icon: "🔄",
    how: "RSI measures how stretched a move is (0–100). Below 30 is “oversold”, so buy and expect a bounce. Above 70 is “overbought”, so sell. Exit when RSI returns to 50.",
    good: "Range-bound markets that snap back.", bad: "Strong trends: “oversold” can keep getting more oversold.",
  },
  opening_range: {
    title: "Opening range breakout", icon: "🚀",
    how: "Marks the high and low of the first 30 minutes after 09:15. A break above that range is a buy, a break below is a sell. At most one trade per stock per day.",
    good: "News days with a clear direction after the open.", bad: "Quiet days where breakouts fade back into the range.",
  },
  supertrend: {
    title: "Supertrend", icon: "🌊",
    how: "Draws a trailing line one volatility-band (3 × ATR) away from price. When price closes through it the trend has flipped: buy on a flip up, sell short on a flip down. Stop just beyond the line, target 2× the risk.",
    good: "Days with one sustained move.", bad: "Sideways chop, which causes repeated small losses on false flips.",
  },
  vwap_pullback: {
    title: "VWAP pullback", icon: "🎯",
    how: "VWAP is the day's average price weighted by volume, the level big traders benchmark against. In an uptrend (price above VWAP, short average above long), buy when price dips to VWAP and closes back above it. Mirror for shorts. Stop 1 ATR beyond VWAP, target 2× risk, one trade per stock per day.",
    good: "Trending days with orderly dips.", bad: "Days when price keeps crossing VWAP with no direction.",
  },
};

type Stats = { trades: number; net: number; winRate: number | null };
const stats = (ts: AccountTrade[]): Stats => {
  const wins = ts.filter((t) => t.net_pnl > 0).length;
  return {
    trades: ts.length,
    net: ts.reduce((s, t) => s + t.net_pnl, 0),
    winRate: ts.length ? Math.round((wins / ts.length) * 1000) / 10 : null,
  };
};

function LiveStats({ s }: { s: Stats }) {
  return (
    <div className="mini-stats">
      <div><span className="muted small">Trades</span><strong>{s.trades}</strong></div>
      <div><span className="muted small">Net P&L</span><strong className={tone(s.net)}>{signedMoney(s.net)}</strong></div>
      <div><span className="muted small">Win rate</span><strong>{s.winRate == null ? "–" : `${s.winRate}%`}</strong></div>
    </div>
  );
}

export default function StrategiesPage() {
  const bot = usePoll<Bot>("/api/bot", 30_000);
  const meta = usePoll<Meta>("/api/meta", 0);
  const runs = usePoll<Run[]>("/api/runs?kind=backtest&limit=200", 0);
  const auto = usePoll<AccountTrade[]>("/api/trades?source=auto&limit=1000", 60_000);
  const b = bot.data;

  const autoTrades = auto.data ?? [];
  const stockStats = stats(autoTrades.filter((t) => !t.symbol.endsWith("-FUT")));
  const futStats = stats(autoTrades.filter((t) => t.symbol.endsWith("-FUT")));
  // runs come newest first, so the first match is the latest backtest
  const latest = (name: string) => runs.data?.find((r) => r.strategy === name && r.metrics);

  return (
    <>
      <div className="page-head"><h1>Strategies</h1></div>
      {(bot.error || meta.error) && <div className="alert">Can&apos;t reach the backend: {bot.error || meta.error}</div>}

      <h2 className="section-title">Live paper test</h2>
      <section className="card">
        <h2>🏁 Strategy race</h2>
        <ShadowAccounts aiTrades={autoTrades} />
      </section>

      <h2 className="section-title">Live in Auto mode</h2>
      <section className="card">
        <div className="row-between">
          <h2>🤖 AI stock picks</h2>
          {b && <span className={`pill ${b.auto_enabled ? "long" : ""}`}>{b.auto_enabled ? "ON" : "OFF"}</span>}
        </div>
        <p className="small">
          Every 15 minutes the AI model looks at each NIFTY 50 stock&apos;s recent candles (momentum, RSI, trend, volume,
          time of day, plus the NIFTY / BANKNIFTY trend and India VIX) and predicts its return over the next hour. The bot
          buys the strongest predictions.
        </p>
        {b && (
          <div className="kv-chips">
            <span>₹{b.amount_per_trade.toLocaleString("en-IN")} / trade</span>
            <span>Min forecast +{b.min_predicted_return_pct}%</span>
            <span className="up">Target {b.target_pct}%</span>
            <span className="down">Stop {b.stop_loss_pct}%</span>
            <span>Max {b.max_positions} open</span>
            <span>Hold ≤ {b.max_hold_minutes}m</span>
          </div>
        )}
        <LiveStats s={stockStats} />
        <div className="link-row">
          <Link href="/trading" className="btn ghost">{b?.auto_enabled ? "See trades" : "Turn on"}</Link>
          <Link href="/settings" className="btn ghost">Edit rules</Link>
        </div>
      </section>

      <section className="card">
        <div className="row-between">
          <h2>📊 AI index futures</h2>
          {b && <span className={`pill ${b.futures_auto_enabled ? "long" : ""}`}>{b.futures_auto_enabled ? "ON" : "OFF"}</span>}
        </div>
        <p className="small">
          Uses the same model&apos;s 1-hour forecast for NIFTY and BANKNIFTY. If the forecast is big enough it buys a
          futures lot (forecast up) or sells one short (forecast down). One position per index, squared off by 15:15.
        </p>
        {b && (
          <div className="kv-chips">
            <span>{b.futures_lots} lot / trade</span>
            <span>Min forecast ±{b.futures_min_predicted_return_pct}%</span>
            <span className="up">Target {b.futures_target_pct}%</span>
            <span className="down">Stop {b.futures_stop_loss_pct}%</span>
            <span>Hold ≤ {b.max_hold_minutes}m</span>
          </div>
        )}
        <LiveStats s={futStats} />
        <div className="link-row">
          <Link href="/trading" className="btn ghost">{b?.futures_auto_enabled ? "See trades" : "Turn on"}</Link>
          <Link href="/settings" className="btn ghost">Edit rules</Link>
        </div>
      </section>

      <h2 className="section-title">Rule-based strategies</h2>
      <p className="muted small">
        Classic strategies you can replay on past NSE data with full charges. Supertrend, opening range and EMA (as a
        daily swing) also run in the live paper test above.
      </p>
      {(meta.data?.strategies ?? []).map((s) => {
        const g = GUIDE[s.name];
        const r = latest(s.name);
        const m = r?.metrics;
        const beat = m && m.benchmark_return_pct != null ? m.total_return_pct - m.benchmark_return_pct : null;
        return (
          <section key={s.name} className="card">
            <h2>{g ? `${g.icon} ${g.title}` : s.name}</h2>
            <p className="small">{g?.how ?? s.description}</p>
            {g && (
              <ul className="small strat-fit">
                <li><span className="up">Works on:</span> {g.good}</li>
                <li><span className="down">Struggles on:</span> {g.bad}</li>
              </ul>
            )}
            {Object.keys(s.default_params).length > 0 && (
              <div className="kv-chips">
                {Object.entries(s.default_params).map(([k, v]) => <span key={k}>{k.replace(/_/g, " ")} {v}</span>)}
              </div>
            )}
            {m ? (
              <>
                <p className="muted small">
                  Last backtest: {r.symbols.length} stocks · {r.interval} · {r.period} ·{" "}
                  <Link href={`/runs/${r.id}`}>details</Link>
                </p>
                <div className="mini-stats">
                  <div><span className="muted small">Return</span><strong className={tone(m.total_return_pct)}>{pct(m.total_return_pct)}</strong></div>
                  <div><span className="muted small">vs buy & hold</span><strong className={tone(beat)}>{pct(beat)}</strong></div>
                  <div><span className="muted small">Win rate</span><strong>{m.win_rate_pct == null ? "–" : `${m.win_rate_pct}%`}</strong></div>
                  <div><span className="muted small">Trades</span><strong>{m.num_trades}</strong></div>
                </div>
              </>
            ) : (
              <p className="muted small">Not backtested yet.</p>
            )}
            <Link href={`/backtest?strategy=${s.name}`} className="btn ghost wide center">Backtest {g?.title ?? s.name}</Link>
          </section>
        );
      })}
      {meta.data && <Link href="/runs" className="btn ghost wide center">All backtest history</Link>}

      <section className="card">
        <h2>📚 What the numbers mean</h2>
        <ul className="small">
          <li><strong>Win rate</strong>: the share of trades that made money. You can win 70% and still lose money if the losses are bigger than the wins.</li>
          <li><strong>vs buy &amp; hold</strong>: the strategy&apos;s return minus what you&apos;d have made just buying the same stocks and holding. Below 0 means doing nothing was better.</li>
          <li><strong>Profit factor</strong>: total profits ÷ total losses. Above 1.0 means profitable overall.</li>
          <li><strong>Max drawdown</strong>: the biggest fall from a high point, i.e. the worst stretch you&apos;d have to sit through.</li>
          <li><strong>Charges</strong>: brokerage, STT, exchange fee, SEBI fee, stamp duty and GST, all included in every result.</li>
        </ul>
      </section>
    </>
  );
}
