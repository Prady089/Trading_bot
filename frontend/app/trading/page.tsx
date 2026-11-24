"use client";

import { useState } from "react";
import Link from "next/link";
import ModelNote from "@/components/ModelNote";
import PickCard from "@/components/PickCard";
import PositionList from "@/components/PositionList";
import TradeList from "@/components/TradeList";
import { useToast } from "@/components/Toast";
import FuturesCard from "@/components/FuturesCard";
import { api, type AccountTrade, type Bot, type FuturesQuote, type Portfolio, type ScannerResult, type Status } from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { istTime, money, signedMoney, tone } from "@/lib/format";

export default function TradingPage() {
  const [showAll, setShowAll] = useState(false);
  const scan = usePoll<ScannerResult>(`/api/scanner?limit=${showAll ? 50 : 5}`, 30_000);
  const bot = usePoll<Bot>("/api/bot", 0);
  const status = usePoll<Status>("/api/status", 30_000);
  const pf = usePoll<Portfolio>("/api/portfolio", 15_000);
  const autoTrades = usePoll<AccountTrade[]>("/api/trades?source=auto&limit=10", 15_000);
  const fut = usePoll<FuturesQuote[]>("/api/futures", 30_000);
  const { show, node: toast } = useToast();
  const [switching, setSwitching] = useState(false);

  const b = bot.data;
  const auto = !!b?.auto_enabled;
  const marketOpen = !!status.data?.market_open;

  const futAuto = !!b?.futures_auto_enabled;
  const setFutAuto = async (on: boolean) => {
    setSwitching(true);
    try {
      await api<Bot>("/api/bot", { method: "PUT", body: JSON.stringify({ futures_auto_enabled: on }) });
      await bot.reload();
      show(on ? "Auto futures ON: the bot will trade NIFTY / BANKNIFTY when the forecast is strong enough"
        : "Auto futures OFF", true);
      setTimeout(() => { pf.reload(); fut.reload(); }, 3000);
    } catch (e) {
      show((e as Error).message, false);
    } finally {
      setSwitching(false);
    }
  };

  const setMode = async (on: boolean) => {
    if (!b || on === auto) return;
    setSwitching(true);
    try {
      await api<Bot>("/api/bot", { method: "PUT", body: JSON.stringify({ auto_enabled: on }) });
      await bot.reload();
      show(on ? "Auto mode ON: the bot will trade the top picks for you" : "Auto mode OFF: you're in control", true);
      setTimeout(() => { pf.reload(); autoTrades.reload(); }, 3000);
    } catch (e) {
      show((e as Error).message, false);
    } finally {
      setSwitching(false);
    }
  };

  const afterTrade = (msg: string, ok: boolean) => {
    show(msg, ok);
    pf.reload();
    scan.reload();
    autoTrades.reload();
    fut.reload();
  };

  const refresh = async () => {
    try {
      await api("/api/scanner/refresh", { method: "POST" });
      show("Re-scanning NIFTY 50…", true);
      setTimeout(scan.reload, 15_000);
    } catch (e) {
      show((e as Error).message, false);
    }
  };

  const autoPositions = pf.data?.positions.filter((p) => p.source === "auto") ?? [];
  const s = scan.data;

  return (
    <>
      <div className="page-head">
        <h1>Trading</h1>
        <div className="segmented" role="tablist" aria-label="Trading mode">
          <button role="tab" aria-selected={!auto} className={!auto ? "on" : ""} disabled={!b || switching} onClick={() => setMode(false)}>Manual</button>
          <button role="tab" aria-selected={auto} className={auto ? "on" : ""} disabled={!b || switching} onClick={() => setMode(true)}>Auto</button>
        </div>
      </div>

      {(scan.error || bot.error) && <div className="alert">Can&apos;t reach the backend: {scan.error || bot.error}</div>}

      {auto && b && (
        <section className="card auto-card">
          <div className="row-between">
            <h2>🤖 Auto mode is ON</h2>
            <Link href="/settings" className="small">Edit strategy →</Link>
          </div>
          <p className="small muted">
            Every 15 minutes during market hours the bot buys up to {b.max_positions} of the top {b.picks_to_consider} picks
            whose predicted return is at least {b.min_predicted_return_pct}%, then closes each trade at the target, the
            stop-loss, after {b.max_hold_minutes} minutes, or at 15:15, whichever comes first.
          </p>
          <div className="kv-chips">
            <span>₹{b.amount_per_trade.toLocaleString("en-IN")} / trade</span>
            <span className="up">Target {b.target_pct}%</span>
            <span className="down">Stop {b.stop_loss_pct}%</span>
            <span>Max {b.max_positions} open</span>
            <span>Hold ≤ {b.max_hold_minutes}m</span>
            <span>Daily loss stop {b.daily_loss_limit_pct}%</span>
          </div>
          {!marketOpen && <p className="small warn-text">Market is closed. The bot will start trading at 09:15 IST on the next trading day.</p>}
          {status.data?.halted && <p className="small warn-text">Paused for today: daily loss limit reached.</p>}
          {pf.data && (
            <div className="mini-stats">
              <div><span className="muted small">Auto trades</span><strong>{pf.data.by_source.auto.trades}</strong></div>
              <div><span className="muted small">Auto P&L</span><strong className={tone(pf.data.by_source.auto.net_pnl)}>{signedMoney(pf.data.by_source.auto.net_pnl)}</strong></div>
              <div><span className="muted small">Win rate</span><strong>{pf.data.by_source.auto.win_rate_pct ?? "–"}{pf.data.by_source.auto.win_rate_pct != null && "%"}</strong></div>
            </div>
          )}
        </section>
      )}

      {auto && (
        <section className="card">
          <h2>Bot&apos;s open trades</h2>
          <PositionList positions={autoPositions} onChange={afterTrade} empty="No open auto trades right now." />
        </section>
      )}

      <section className="card">
        <div className="row-between">
          <h2>{showAll ? "NIFTY 50 ranked" : "Top 5 predicted"} <span className="muted small">next 1 hour</span></h2>
          <button className="btn tiny" onClick={refresh} disabled={s?.refreshing}>{s?.refreshing ? "Scanning…" : "Refresh"}</button>
        </div>
        {s?.ready ? (
          <>
            <p className="muted small">
              Prices as of {s.data_as_of ? istTime(s.data_as_of) : "–"} · model retrained {s.generated_at ? istTime(s.generated_at) : "–"}
              {!auto && " · tap a stock to trade"}
            </p>
            {b && s.stocks.map((p, i) => (
              <PickCard key={p.symbol} rank={i + 1} pick={p} bot={b} manual={!auto} marketOpen={marketOpen} onTraded={afterTrade} />
            ))}
            <button className="btn ghost wide" onClick={() => setShowAll(!showAll)}>
              {showAll ? "Show top 5 only" : `Show all ${s.stocks_scored ?? 50} stocks`}
            </button>
            {s.model && <ModelNote m={s.model} />}
          </>
        ) : (
          <div className="empty">
            {s?.error ? `Scanner error: ${s.error}` : "Scanning NIFTY 50 and training the model… (about 15 seconds)"}
          </div>
        )}
      </section>

      <section className="card">
        <div className="row-between">
          <h2>Index futures <span className="muted small">NIFTY · BANKNIFTY</span></h2>
          <label className="small row-inline">
            Auto <input type="checkbox" className="switch" checked={futAuto} disabled={!b || switching}
              onChange={(e) => setFutAuto(e.target.checked)} />
          </label>
        </div>
        <p className="muted small">
          Intraday only (squared off at 15:15), priced off the live index.
          {futAuto && b
            ? ` Auto is ON: buys ${b.futures_lots} lot when the 1h forecast is ≥ +${b.futures_min_predicted_return_pct}%, sells short when ≤ −${b.futures_min_predicted_return_pct}% (target ${b.futures_target_pct}%, stop ${b.futures_stop_loss_pct}%).`
            : " Turn on Auto to let the bot trade them, or tap to trade manually."}
        </p>
        {fut.data?.length ? fut.data.map((f) => (
          <FuturesCard key={f.symbol} f={f} manual={!futAuto} marketOpen={marketOpen} onTraded={afterTrade} />
        )) : <div className="empty">{fut.error ? `Futures unavailable: ${fut.error}` : "Loading index prices…"}</div>}
      </section>

      {!auto && pf.data && pf.data.positions.length > 0 && (
        <section className="card">
          <div className="row-between">
            <h2>Your open positions</h2>
            <span className={`small ${tone(pf.data.unrealized_pnl)}`}>{signedMoney(pf.data.unrealized_pnl)}</span>
          </div>
          <PositionList positions={pf.data.positions} onChange={afterTrade} />
        </section>
      )}

      {auto && (
        <section className="card">
          <div className="row-between">
            <h2>Bot&apos;s closed trades</h2>
            <Link href="/portfolio" className="small">All trades →</Link>
          </div>
          <TradeList trades={autoTrades.data ?? []} empty="The bot hasn't closed any trades yet." />
        </section>
      )}

      {pf.data && (
        <p className="muted small center">Cash available {money(pf.data.cash)} · simulated money only</p>
      )}
      {toast}
    </>
  );
}
