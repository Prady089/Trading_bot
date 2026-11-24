export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

function apiKey(): string {
  if (typeof window === "undefined") return "";
  try {
    return localStorage.getItem("apiKey") || "";
  } catch {
    return "";
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const key = apiKey();
  if (key) headers["X-API-Key"] = key;
  const res = await fetch(`${API_URL}${path}`, { ...init, headers: { ...headers, ...(init.headers as object) } });
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {}
    throw new Error(msg);
  }
  return res.json();
}

export type Metrics = {
  initial_capital: number;
  final_equity: number;
  net_pnl: number;
  total_return_pct: number;
  benchmark_return_pct: number | null;
  num_trades: number;
  win_rate_pct: number | null;
  profit_factor: number | null;
  expectancy: number | null;
  avg_win: number | null;
  avg_loss: number | null;
  max_drawdown_pct: number;
  sharpe: number | null;
  total_charges: number;
  gross_pnl: number;
  trading_days: number;
};

export type Trade = {
  id: number;
  symbol: string;
  direction: number;
  qty: number;
  entry_ts: string;
  entry_price: number;
  exit_ts: string;
  exit_price: number;
  gross_pnl: number;
  charges: number;
  net_pnl: number;
  entry_reason: string;
  exit_reason: string;
};

export type AccountTrade = Trade & {
  source: "auto" | "manual" | "";
  return_pct: number;
  predicted_return_pct: number | null; // model's 1h forecast at entry
  price_move_pct: number;              // what the price actually did while the trade was open
  model_correct: boolean | null;       // did it move the way the model said?
};

export type AccuracyScore = {
  forecasts: number;
  candles: number;
  direction_accuracy_pct: number | null;
  always_up_pct: number | null;          // the "dumb" baseline: % of moves that were up
  information_coefficient: number | null;
  top5_avg_return_pct: number | null;
  top5_hit_rate_pct: number | null;
  market_avg_return_pct: number | null;
};

export type LeaderRow = {
  model: string;
  description: string;
  champion: boolean;
  live: AccuracyScore;
  walk_forward: {
    direction_accuracy_pct: number | null; always_up_pct: number | null;
    information_coefficient: number | null; top5_avg_return_pct: number | null;
    market_avg_return_pct: number | null; fold_ic: (number | null)[]; trained_at: string | null;
  };
};

export type TradeAccuracy = {
  scored_trades: number;
  model_right: number;
  model_accuracy_pct: number | null;
  avg_predicted_pct: number | null;
  avg_actual_move_pct: number | null;
};

export type ModelAccuracy = {
  champion: string;
  leaderboard: LeaderRow[];
  promotion_rule: { min_candles: number; ic_margin: number };
  live: AccuracyScore & {
    model: string;
    index: Record<string, { forecasts: number; direction_accuracy_pct: number | null }>;
    counts: { total: number; resolved: number; scans: number };
    by_day: (AccuracyScore & { day: string })[];
    recent_top_picks: { bar_ts: string; symbol: string; rank: number; price: number;
      predicted_return_pct: number; actual_return_pct: number }[];
  };
  trades: Record<"all" | "auto" | "manual", TradeAccuracy>;
  backtest_history: { trained_at: string; data_as_of: string | null; direction_accuracy_pct: number | null;
    information_coefficient: number | null; top5_avg_return_pct: number; market_avg_return_pct: number }[];
  current_model: ModelStats | null;
};

export type Pick = {
  symbol: string;
  last_price: number;
  as_of: string;
  change_today_pct: number | null;
  predicted_return_pct: number;
  predicted_profit: number;
  signals: string[];
  held: boolean;
};

export type ModelStats = {
  model?: string;
  always_up_pct?: number | null;
  fold_ic?: (number | null)[];
  folds?: number;
  trained_at: string;
  horizon_minutes: number;
  train_rows: number;
  test_rows: number;
  direction_accuracy_pct: number | null;
  information_coefficient: number | null;
  top5_avg_return_pct: number;
  top5_hit_rate_pct: number;
  market_avg_return_pct: number;
};

export type ScannerResult = {
  ready: boolean;
  refreshing: boolean;
  error: string | null;
  generated_at?: string;
  data_as_of?: string;
  stocks_scored?: number;
  model?: ModelStats;
  stocks: Pick[];
};

export type Bot = {
  auto_enabled: boolean;
  amount_per_trade: number;
  stop_loss_pct: number;
  target_pct: number;
  max_positions: number;
  max_hold_minutes: number;
  min_predicted_return_pct: number;
  daily_loss_limit_pct: number;
  picks_to_consider: number;
  practice_when_closed: boolean;
  futures_auto_enabled: boolean;
  futures_lots: number;
  futures_min_predicted_return_pct: number;
  futures_stop_loss_pct: number;
  futures_target_pct: number;
};

export type AccountPosition = {
  symbol: string;
  qty: number;
  side: "LONG" | "SHORT";
  avg_price: number;
  last_price: number;
  invested: number;
  unrealized_pnl: number;
  unrealized_pct: number;
  stop_price: number | null;
  target_price: number | null;
  entry_ts: string;
  entry_reason: string;
  source: "auto" | "manual";
  instrument?: "EQ" | "FUT";
  lots?: number | null;
  notional?: number;
};

export type FuturesQuote = {
  symbol: string;
  name: string;
  underlying: string;
  lot_size: number;
  last_price: number | null;
  as_of: string | null;
  change_today_pct: number | null;
  predicted_return_pct: number | null;
  by_model: Record<string, number | null>;
  predicted_profit_per_lot: number | null;
  lot_value: number;
  margin_per_lot: number;
  margin_pct: number;
  affordable_lots: number;
  held: boolean;
};

export type Portfolio = {
  initial_capital: number;
  cash: number;
  equity: number;
  invested: number;
  unrealized_pnl: number;
  realized_pnl: number;
  today_realized_pnl: number;
  today_trades: number;
  total_return_pct: number;
  positions: AccountPosition[];
  by_source: Record<"auto" | "manual", { trades: number; net_pnl: number; win_rate_pct: number | null }>;
  metrics: Metrics;
};

export type Status = {
  server_time_ist: string;
  market_open: boolean;
  auto_enabled: boolean;
  futures_auto_enabled?: boolean;
  halted: boolean;
  last_loop: string | null;
  last_error: string | null;
};

export type EquityPoint = { ts: string; equity: number };
export type EventRow = { ts: string; level: string; message: string };

export type Run = {
  id: number;
  kind: "backtest" | "paper";
  strategy: string;
  symbols: string[];
  interval: string;
  period: string | null;
  initial_capital: number;
  status: string;
  created_at: string;
  updated_at: string;
  metrics: Metrics | null;
  params?: Record<string, unknown>;
};

export type StrategyMeta = { name: string; description: string; default_params: Record<string, number> };
export type Meta = {
  strategies: StrategyMeta[];
  intervals: string[];
  default_symbols: string[];
  settings: Record<string, number | boolean>;
  auth_required: boolean;
};

export type Position = {
  symbol: string;
  qty: number;
  avg_price: number;
  entry_ts: string;
  stop_price: number | null;
  target_price: number | null;
  last_price: number;
  unrealized_pnl: number;
  entry_reason: string;
};

export type PaperStatus = {
  running: boolean;
  run_id: number | null;
  strategy?: string;
  interval?: string;
  symbols?: string[];
  market_open?: boolean;
  server_time_ist?: string;
  last_cycle?: string | null;
  last_error?: string | null;
  halted?: boolean;
  halt_reason?: string;
  initial_capital?: number;
  cash?: number;
  equity?: number;
  today_realized_pnl?: number;
  today_trades?: number;
  positions?: Position[];
  metrics?: Metrics;
  last_run?: { strategy: string; interval: string; symbols: string[]; status: string; metrics: Metrics | null } | null;
};
