"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useToast } from "@/components/Toast";
import { api, API_URL, type Bot } from "@/lib/api";
import { usePoll } from "@/lib/hooks";

type Field = { key: keyof Bot; label: string; help: string; step?: string; suffix?: string };

const FIELDS: Field[] = [
  { key: "amount_per_trade", label: "Amount per trade", help: "Rupees the bot invests in each stock it buys.", step: "1000", suffix: "₹" },
  { key: "target_pct", label: "Target (take profit)", help: "Sell when the price rises this much from entry.", step: "0.1", suffix: "%" },
  { key: "stop_loss_pct", label: "Stop-loss", help: "Sell when the price falls this much from entry, to cap the loss.", step: "0.1", suffix: "%" },
  { key: "max_positions", label: "Max open trades", help: "Most stocks the bot holds at the same time.", step: "1" },
  { key: "max_hold_minutes", label: "Max holding time", help: "Close a trade after this long even if no target or stop is hit. The model predicts 60 minutes ahead.", step: "15", suffix: "min" },
  { key: "min_predicted_return_pct", label: "Minimum predicted return", help: "Only buy picks predicted to rise at least this much in the next hour.", step: "0.01", suffix: "%" },
  { key: "picks_to_consider", label: "Picks to consider", help: "The bot only looks at this many top-ranked stocks.", step: "1" },
  { key: "daily_loss_limit_pct", label: "Daily loss limit", help: "If the account falls this much in a day, the bot stops opening trades until tomorrow.", step: "0.5", suffix: "%" },
];

const FUT_FIELDS: Field[] = [
  { key: "futures_lots", label: "Lots per trade", help: "1 NIFTY lot ties up about ₹2 lakh of margin; 1 BANKNIFTY lot about ₹2.3 lakh.", step: "1" },
  { key: "futures_min_predicted_return_pct", label: "Minimum forecast (up or down)", help: "Buy when the index is forecast to rise at least this much in the next hour, sell short when forecast to fall this much. About 0.06% just covers the charges on 1 lot.", step: "0.01", suffix: "%" },
  { key: "futures_target_pct", label: "Target", help: "Take profit when the index moves this much in your favour.", step: "0.1", suffix: "%" },
  { key: "futures_stop_loss_pct", label: "Stop-loss", help: "Exit when the index moves this much against you. 0.5% of NIFTY is about 125 points, roughly ₹8,000 per lot.", step: "0.1", suffix: "%" },
];
const INTS = ["max_positions", "max_hold_minutes", "picks_to_consider", "futures_lots"];

export default function SettingsPage() {
  const bot = usePoll<Bot>("/api/bot", 0);
  const [form, setForm] = useState<Record<string, string>>({});
  const [practice, setPractice] = useState(true);
  const [futAuto, setFutAuto] = useState(false);
  const [capital, setCapital] = useState("100000");
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState(false);
  const { show, node: toast } = useToast();

  useEffect(() => {
    if (!bot.data) return;
    setForm(Object.fromEntries([...FIELDS, ...FUT_FIELDS].map((f) => [f.key, String(bot.data![f.key] ?? "")])));
    setPractice(bot.data.practice_when_closed);
    setFutAuto(!!bot.data.futures_auto_enabled);
  }, [bot.data]);

  useEffect(() => {
    try { setApiKey(localStorage.getItem("apiKey") || ""); } catch {}
  }, []);

  const save = async () => {
    setBusy(true);
    try {
      const patch: Record<string, number | boolean> = { practice_when_closed: practice, futures_auto_enabled: futAuto };
      for (const f of [...FIELDS, ...FUT_FIELDS]) {
        const v = Number(form[f.key]);
        if (!Number.isFinite(v) || v < 0) throw new Error(`${f.label}: enter a valid number`);
        patch[f.key] = INTS.includes(f.key) ? Math.round(v) : v;
      }
      await api<Bot>("/api/bot", { method: "PUT", body: JSON.stringify(patch) });
      await bot.reload();
      show("Strategy saved", true);
    } catch (e) {
      show((e as Error).message, false);
    } finally {
      setBusy(false);
    }
  };

  const reset = async () => {
    if (!window.confirm?.(`Reset the paper account to ₹${Number(capital).toLocaleString("en-IN")}? Open positions and history start fresh.`)) return;
    try {
      await api("/api/account/reset", { method: "POST", body: JSON.stringify({ capital: Number(capital) }) });
      show("Paper account reset", true);
    } catch (e) {
      show((e as Error).message, false);
    }
  };

  const saveKey = () => {
    try { localStorage.setItem("apiKey", apiKey); show("API key saved on this device", true); } catch { show("Couldn't save", false); }
  };

  return (
    <>
      <div className="page-head"><h1>Settings</h1></div>
      {bot.error && <div className="alert">Can&apos;t reach the backend: {bot.error}</div>}

      <section className="card">
        <h2>Auto-trading strategy</h2>
        <p className="muted small">These rules control the bot in Auto mode. Stop-loss and target are also the defaults for manual trades.</p>
        <div className="settings-list">
          {FIELDS.map((f) => (
            <label key={f.key} className="setting">
              <span className="setting-text">
                <span className="strong">{f.label}</span>
                <span className="muted small">{f.help}</span>
              </span>
              <span className="setting-input">
                {f.suffix === "₹" && <span className="muted">₹</span>}
                <input type="number" inputMode="decimal" step={f.step} min="0" value={form[f.key] ?? ""}
                  onChange={(e) => setForm({ ...form, [f.key]: e.target.value })} />
                {f.suffix && f.suffix !== "₹" && <span className="muted">{f.suffix}</span>}
              </span>
            </label>
          ))}
          <label className="setting">
            <span className="setting-text">
              <span className="strong">Practice when market is closed</span>
              <span className="muted small">Allow manual trades outside 09:15–15:30. They fill at the last traded price.</span>
            </span>
            <input type="checkbox" className="switch" checked={practice} onChange={(e) => setPractice(e.target.checked)} />
          </label>
        </div>
        <button className="btn primary wide" onClick={save} disabled={busy || !bot.data}>{busy ? "Saving…" : "Save strategy"}</button>
      </section>

      <section className="card">
        <h2>Auto futures</h2>
        <p className="muted small">
          Separate from the stock bot. Every 15 minutes, if the AI forecasts NIFTY or BANKNIFTY to move more than your minimum
          in the next hour, the bot buys (forecast up) or sells short (forecast down) that index future. At most one position
          per index. Each trade closes at the target, the stop-loss, after the max holding time above, or at 15:15. The daily
          loss limit above applies too.
        </p>
        <div className="settings-list">
          <label className="setting">
            <span className="setting-text">
              <span className="strong">Auto-trade index futures</span>
              <span className="muted small">Turn on and press Save. Works whether the stock bot is on or off.</span>
            </span>
            <input type="checkbox" className="switch" checked={futAuto} onChange={(e) => setFutAuto(e.target.checked)} />
          </label>
          {FUT_FIELDS.map((f) => (
            <label key={f.key} className="setting">
              <span className="setting-text">
                <span className="strong">{f.label}</span>
                <span className="muted small">{f.help}</span>
              </span>
              <span className="setting-input">
                <input type="number" inputMode="decimal" step={f.step} min="0" value={form[f.key] ?? ""}
                  onChange={(e) => setForm({ ...form, [f.key]: e.target.value })} />
                {f.suffix && <span className="muted">{f.suffix}</span>}
              </span>
            </label>
          ))}
        </div>
        <button className="btn primary wide" onClick={save} disabled={busy || !bot.data}>{busy ? "Saving…" : "Save futures rules"}</button>
      </section>

      <section className="card">
        <h2>Strategies &amp; backtests</h2>
        <p className="muted small">How each strategy works, its live results and the backtest lab are on the Strategies tab.</p>
        <Link href="/strategies" className="btn ghost wide center">Open Strategies</Link>
      </section>

      <section className="card">
        <h2>Paper account</h2>
        <label className="setting">
          <span className="setting-text">
            <span className="strong">Starting capital</span>
            <span className="muted small">Reset to begin a fresh test. Old history is kept in the database.</span>
          </span>
          <span className="setting-input"><span className="muted">₹</span>
            <input type="number" step="10000" min="10000" value={capital} onChange={(e) => setCapital(e.target.value)} />
          </span>
        </label>
        <button className="btn danger wide" onClick={reset}>Reset paper account</button>
      </section>

      <section className="card">
        <h2>Connection</h2>
        <p className="muted small">Server: {API_URL}</p>
        <label className="setting">
          <span className="setting-text">
            <span className="strong">API key</span>
            <span className="muted small">Only needed if the server has APP_API_KEY set (recommended once deployed).</span>
          </span>
          <input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} autoComplete="off" />
        </label>
        <button className="btn ghost wide" onClick={saveKey}>Save key on this device</button>
      </section>
      {toast}
    </>
  );
}
