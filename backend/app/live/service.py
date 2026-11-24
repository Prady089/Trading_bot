"""The paper trading account: one simulated portfolio shared by Manual and Auto modes.

- Manual: you place simulated buy / sell-short orders at the latest price.
- Auto:   every 15 minutes the bot takes the scanner's top picks (if their predicted
          return clears your minimum), buys with your fixed amount per trade, and closes
          each trade at your stop-loss, target, max holding time or the 15:15 square-off.
          Auto futures (separate switch): buys 1+ lots of NIFTY / BANKNIFTY futures when the index
          forecast is >= +min, sells short when <= -min, same exits.
- Every minute during market hours, open positions are checked against 1-minute
  candles for stop-loss / target hits.
All state is saved to SQLite, so restarting the server keeps the account.
"""
from __future__ import annotations

import logging
import math
import threading
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timedelta

from app.broker.costs import IndianEquityCosts, IndianFuturesCosts
from app.broker.simulated import SimulatedBroker
from app.config import FUTURES, FUTURES_MARGIN_PCT, IST, Settings
from app.data.feed import DataFeed
from app.engine.metrics import compute_metrics
from app.models import Bar, Order, Side, Trade
from app.predict.scanner import Scanner
from app.storage.db import Store

log = logging.getLogger("account")


@dataclass
class BotSettings:
    auto_enabled: bool = False
    amount_per_trade: float = 20_000      # Rs invested per trade
    stop_loss_pct: float = 0.75
    target_pct: float = 1.5
    max_positions: int = 3                # auto positions open at once
    max_hold_minutes: int = 60            # auto exits after this (model predicts 1 hour ahead)
    min_predicted_return_pct: float = 0.05
    daily_loss_limit_pct: float = 2.0     # auto stops opening trades for the day after this loss
    picks_to_consider: int = 5
    practice_when_closed: bool = True     # allow manual orders outside market hours (filled at last price)
    # Auto futures: buy or sell NIFTY / BANKNIFTY futures when the index forecast is big enough.
    futures_auto_enabled: bool = False
    futures_lots: int = 1
    futures_min_predicted_return_pct: float = 0.06   # ~ round-trip charges on 1 lot
    futures_stop_loss_pct: float = 0.5
    futures_target_pct: float = 1.0

    @classmethod
    def from_dict(cls, d: dict) -> "BotSettings":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})


class TradingService:
    LOOP_SECONDS = 60

    def __init__(self, feed: DataFeed, store: Store, scanner: Scanner, s: Settings):
        self.feed, self.store, self.scanner, self.s = feed, store, scanner, s
        self.lock = threading.RLock()
        self.clock = lambda: datetime.now(IST)  # injectable for tests
        self.bot = BotSettings.from_dict(store.kv_get("bot_settings", {}))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_loop: datetime | None = None
        self.last_error: str | None = None
        self._last_scan_slot: datetime | None = None
        self._day: str | None = None
        self._day_start_equity = 0.0
        self.halted = False
        self._live_check: tuple[str, bool, datetime] | None = None   # (day, live?, checked_at)
        self._load_account()
        if hasattr(scanner, "on_event"):
            scanner.on_event = lambda msg, level="info": self._event(msg, level)

    # ---------- account persistence ----------
    def _new_broker(self, capital: float) -> SimulatedBroker:
        b = SimulatedBroker(capital, IndianEquityCosts("intraday"), self.s.slippage_bps, self.s.margin_rate)
        for sym in FUTURES:
            b.instruments[sym] = (FUTURES_MARGIN_PCT / 100, IndianFuturesCosts())
        return b

    def _load_account(self) -> None:
        run = self.store.latest_run("account")
        if run is None:
            self.run_id = self.store.create_run("account", "paper-account", [], "1m", None, {},
                                                self.s.initial_capital, "running")
            self.broker = self._new_broker(self.s.initial_capital)
            self.last_checked: dict[str, datetime] = {}
            self._save()
            return
        self.run_id = run["id"]
        self.broker = self._new_broker(run["initial_capital"])
        st = run.get("state") or {}
        if st.get("broker"):
            self.broker.restore(st["broker"])
        self.last_checked = {k: datetime.fromisoformat(v) for k, v in st.get("last_checked", {}).items()}

    def _save(self) -> None:
        new = self.broker.trades
        if new:
            self.store.add_trades(self.run_id, new)
            self.broker.trades = []
        self.store.update_run(self.run_id, state={
            "broker": self.broker.snapshot(),
            "last_checked": {k: v.isoformat() for k, v in self.last_checked.items()},
        })

    def _event(self, msg: str, level: str = "info", ts: datetime | None = None) -> None:
        self.store.add_events(self.run_id, [((ts or self.clock()).isoformat(timespec="seconds"), level, msg)])

    def _snapshot_equity(self, ts: datetime | None = None) -> None:
        self.store.add_equity(self.run_id, [((ts or self.clock()).isoformat(timespec="seconds"),
                                             round(self.broker.equity(), 2))])

    def reset(self, capital: float) -> None:
        with self.lock:
            self.store.update_run(self.run_id, status="stopped")
            self.run_id = self.store.create_run("account", "paper-account", [], "1m", None, {}, capital, "running")
            self.broker = self._new_broker(capital)
            self.last_checked = {}
            self._day = None
            self.halted = False
            self._save()
            self._snapshot_equity()
            self._event(f"Account reset with Rs {capital:,.0f}")

    # ---------- market clock ----------
    def market_open(self, now: datetime) -> bool:
        """Open by the clock AND actually trading today (catches NSE holidays and dead data feeds)."""
        return self._clock_open(now) and self.trading_today(now)

    def _clock_open(self, now: datetime) -> bool:
        return now.weekday() < 5 and self.s.market_open <= now.time() < self.s.market_close

    HOLIDAY_PROBE = "NIFTY"

    def trading_today(self, now: datetime) -> bool:
        """True once today's candles exist. NSE holidays have none, so the bot must not trade on
        yesterday's prices. Re-checked every 5 minutes until confirmed; cached for the day after."""
        if now.weekday() >= 5:
            return False
        day = now.date().isoformat()
        open_dt = datetime.combine(now.date(), self.s.market_open, IST)
        if now < open_dt + timedelta(minutes=5):
            return True   # first candles can take a few minutes to appear
        c = self._live_check
        if c and c[0] == day and (c[1] or now - c[2] < timedelta(minutes=5)):
            return c[1]
        try:
            bars = self.feed.history_many([self.HOLIDAY_PROBE], "1m", "1d").get(self.HOLIDAY_PROBE, [])
            live = bool(bars) and bars[-1].ts.date() == now.date()
        except Exception:  # noqa: BLE001
            log.exception("holiday check failed")
            live = c[1] if c and c[0] == day else False
        if not live and (not c or c[0] != day or c[1]):
            self._event("No market data today (NSE holiday or data outage): trading paused", "warn")
        self._live_check = (day, live, now)
        return live

    def _void_stale_entries(self, now: datetime) -> None:
        """Cancel today's entries that were filled while the market wasn't really trading."""
        with self.lock:
            stale = [s for s, p in self.broker.positions.items() if p.entry_ts.date() == now.date()]
            for sym in stale:
                p = self.broker.void_position(sym)
                self.last_checked.pop(sym, None)
                self._event(f"VOIDED {sym}: filled at a stale price on a non-trading day, cancelled at no cost "
                            f"(entry {p.avg_price:.2f})", "warn")
            if stale:
                self._save()
                self._snapshot_equity(now)

    def _scan_slot(self, now: datetime) -> datetime:
        """Start of the current 15-minute candle (aligned to 09:15)."""
        open_dt = datetime.combine(now.date(), self.s.market_open, IST)
        k = max(0, int((now - open_dt).total_seconds() // 900))
        return open_dt + timedelta(minutes=15 * k)

    # ---------- prices ----------
    def quote(self, symbol: str) -> tuple[float, datetime]:
        bars = self.feed.history_many([symbol], "1m", "5d").get(symbol.upper(), [])
        if not bars:
            raise ValueError(f"No price available for {symbol}")
        b = bars[-1]
        return b.close, b.ts

    # ---------- loop ----------
    def start(self) -> None:
        if not self.scanner.result:
            self.scanner.refresh_async()
        self._thread = threading.Thread(target=self._loop, name="account-loop", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=30)
        with self.lock:
            self._save()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick(self.clock())
                self.last_error = None
            except Exception as e:  # noqa: BLE001
                log.exception("tick failed")
                self.last_error = str(e)
            self._stop.wait(self.LOOP_SECONDS)

    def tick(self, now: datetime) -> None:
        self.last_loop = now
        in_session = now.weekday() < 5 and self.s.market_open <= now.time() < \
            (datetime.combine(now.date(), self.s.market_close) + timedelta(minutes=5)).time()
        if not in_session:
            return
        if self._clock_open(now) and not self.trading_today(now):
            self._void_stale_entries(now)
            return
        self.monitor(now)
        slot = self._scan_slot(now)
        # Rescan ~1 minute after each 15m candle closes.
        if slot != self._last_scan_slot and now >= slot + timedelta(seconds=60):
            self._last_scan_slot = slot
            self.scanner.refresh()
            self.auto_enter(now)

    # ---------- position monitoring ----------
    def monitor(self, now: datetime) -> None:
        with self.lock:
            held = list(self.broker.positions)
        if not held:
            self._daily_risk(now)
            return
        data = self.feed.history_many(held, "1m", "5d")
        with self.lock:
            for sym in held:
                p = self.broker.positions.get(sym)
                if not p:
                    continue
                since = self.last_checked.get(sym, p.entry_ts)
                for bar in data.get(sym, []):
                    if bar.ts < since or bar.ts + timedelta(minutes=1) > now:
                        continue  # already checked, or candle still forming
                    if sym not in self.broker.positions:
                        break
                    self._process_bar(bar, now)
                    self.last_checked[sym] = bar.ts + timedelta(minutes=1)
            for sym in list(self.last_checked):
                if sym not in self.broker.positions:
                    del self.last_checked[sym]
            closed = list(self.broker.trades)
            self._save()
            for t in closed:
                self._event(f"CLOSED {t.symbol} {t.exit_reason}: {t.net_pnl:+,.2f} "
                            f"({t.net_pnl / (t.entry_price * t.qty) * 100:+.2f}%)", ts=t.exit_ts)
            self._snapshot_equity(now)
            self._daily_risk(now)

    def _process_bar(self, bar: Bar, now: datetime) -> None:
        sym, p = bar.symbol, self.broker.positions[bar.symbol]
        if bar.ts.time() >= self.s.square_off_at:
            self.broker.close_position(sym, bar.open, bar.ts, "intraday square-off")
            return
        self.broker.check_stops(bar)
        if sym not in self.broker.positions:
            return
        self.broker.mark(bar)
        if p.source == "auto" and bar.ts + timedelta(minutes=1) >= p.entry_ts + timedelta(minutes=self.bot.max_hold_minutes):
            self.broker.close_position(sym, bar.close, bar.ts + timedelta(minutes=1),
                                       f"time exit ({self.bot.max_hold_minutes} min)")

    def _daily_risk(self, now: datetime) -> None:
        d = now.date().isoformat()
        eq = self.broker.equity()
        if d != self._day:
            self._day, self._day_start_equity, self.halted = d, eq, False
        elif not self.halted and eq <= self._day_start_equity * (1 - self.bot.daily_loss_limit_pct / 100):
            self.halted = True
            self._event(f"Auto trading paused for today: daily loss limit {self.bot.daily_loss_limit_pct}% hit", "warn")

    # ---------- auto mode ----------
    def auto_enter(self, now: datetime) -> list[str]:
        if self.halted or not self.market_open(now) or now.time() >= self.s.no_new_entries_after:
            return []
        entered = []
        if self.bot.auto_enabled:
            entered += self._auto_stocks(now)
        if self.bot.futures_auto_enabled:
            entered += self._auto_futures(now)
        return entered

    def _auto_futures(self, now: datetime) -> list[str]:
        """Go long when the index forecast is >= +min, short when <= -min. One position per index."""
        b = self.bot
        entered = []
        for sym, f in FUTURES.items():
            pred = self.predicted(sym)
            if pred is None or abs(pred) < b.futures_min_predicted_return_pct or b.futures_lots <= 0:
                continue
            with self.lock:
                if sym in self.broker.positions:
                    continue
            try:
                price, _ = self.quote(sym)
            except ValueError:
                continue
            qty = b.futures_lots * f["lot_size"]
            need = qty * price * FUTURES_MARGIN_PCT / 100
            with self.lock:
                free = self.broker.available_margin()
                if need > free:
                    self._event(f"AUTO skipped {sym}: {b.futures_lots} lot(s) need margin Rs {need:,.0f}, "
                                f"only Rs {free:,.0f} free", "warn")
                    continue
                side = Side.BUY if pred > 0 else Side.SELL
                label = "BUY" if side == Side.BUY else "SELL (short)"
                reason = f"AI index forecast {pred:+.3f}% in 1h"
                pos = self.broker.market_order(
                    Order(sym, side, qty, True, reason, now, b.futures_stop_loss_pct, b.futures_target_pct, "auto", pred),
                    price, now)
                if pos:
                    entered.append(sym)
                    self.last_checked[sym] = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
                    self._event(f"AUTO {label} {sym} {b.futures_lots} lot(s) @ {pos.avg_price:.2f} - {reason}")
                self._save()
                if pos:
                    self._snapshot_equity(now)
        return entered

    def _auto_stocks(self, now: datetime) -> list[str]:
        b = self.bot
        with self.lock:
            auto_open = [s for s, p in self.broker.positions.items() if p.source == "auto" and s not in FUTURES]
        slots = b.max_positions - len(auto_open)
        if slots <= 0:
            return []
        picks = [p for p in self.scanner.top(b.picks_to_consider)
                 if p["predicted_return_pct"] >= b.min_predicted_return_pct
                 and p["symbol"] not in self.broker.positions][:slots]
        if not picks:
            return []
        quotes = self.feed.history_many([p["symbol"] for p in picks], "1m", "1d")
        entered = []
        with self.lock:
            for p in picks:
                bars = quotes.get(p["symbol"]) or []
                price = bars[-1].close if bars else p["last_price"]
                qty = math.floor(b.amount_per_trade / price)
                if qty <= 0:
                    continue
                reason = f"AI pick: predicted {p['predicted_return_pct']:+.2f}% in 1h"
                pos = self.broker.market_order(
                    Order(p["symbol"], Side.BUY, qty, True, reason, now, b.stop_loss_pct, b.target_pct, "auto",
                          p["predicted_return_pct"]),
                    price, now)
                if pos:
                    entered.append(p["symbol"])
                    self.last_checked[p["symbol"]] = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
                    self._event(f"AUTO BUY {p['symbol']} x{qty} @ {pos.avg_price:.2f} - {reason}")
            self._save()
            if entered:
                self._snapshot_equity(now)
        return entered

    # ---------- manual mode ----------
    def manual_order(self, symbol: str, side: str, amount: float | None, qty: int | None,
                     stop_loss_pct: float | None, target_pct: float | None, lots: int | None = None) -> dict:
        symbol = symbol.upper()
        now = self.clock()
        is_open = self.market_open(now)
        if not is_open and not self.bot.practice_when_closed:
            raise ValueError("Market is closed. Enable practice mode in Settings to trade anyway.")
        price, price_ts = self.quote(symbol)
        fut = FUTURES.get(symbol)
        if fut:
            n = lots or 1
            if n <= 0:
                raise ValueError("Lots must be at least 1")
            q = n * fut["lot_size"]
            need = q * price * FUTURES_MARGIN_PCT / 100
            if need > self.broker.available_margin():
                raise ValueError(f"Not enough margin: {n} lot(s) of {symbol} need about Rs {need:,.0f}, "
                                 f"you have Rs {self.broker.available_margin():,.0f} free")
        else:
            q = qty or (math.floor(amount / price) if amount else 0)
        if q <= 0:
            raise ValueError(f"Amount too small: 1 share of {symbol} costs Rs {price:,.2f}")
        with self.lock:
            if symbol in self.broker.positions:
                raise ValueError(f"You already hold {symbol}. Close it first.")
            s = Side.BUY if side.upper() == "BUY" else Side.SELL
            label = "BUY" if s == Side.BUY else "SELL (short)"
            pos = self.broker.market_order(
                Order(symbol, s, q, True, f"manual {label}", now, stop_loss_pct or None, target_pct or None, "manual",
                      self.predicted(symbol)),
                price, now)
            if not pos:
                raise ValueError("Not enough cash for this order")
            self.last_checked[symbol] = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
            self._save()
            self._snapshot_equity(now)
            note = "" if is_open else " (practice: market closed, last traded price)"
            size = f"{abs(pos.qty) // fut['lot_size']} lot(s)" if fut else f"x{abs(pos.qty)}"
            self._event(f"MANUAL {label} {symbol} {size} @ {pos.avg_price:.2f}{note}")
        return {"position": pos.to_dict(), "price_as_of": price_ts.isoformat(), "market_open": is_open}

    def predicted(self, symbol: str) -> float | None:
        """The model's latest 1h forecast for a symbol, stored on the trade so it can be scored later."""
        r = self.scanner.result or {}
        if symbol in FUTURES:
            idx = (r.get("index") or {}).get(FUTURES[symbol]["underlying"])
            return idx["predicted_return_pct"] if idx else None
        for st in r.get("stocks", []):
            if st["symbol"] == symbol:
                return st["predicted_return_pct"]
        return None

    def futures(self) -> list[dict]:
        """Index futures quotes for the app, with the champion model's 1h forecast."""
        index = (self.scanner.result or {}).get("index") or {}
        free = self.broker.available_margin()
        out = []
        for sym, f in FUTURES.items():
            i = index.get(f["underlying"], {})
            price = self.broker.last_price.get(sym) if sym in self.broker.positions else None
            price = price or i.get("last_price")
            lot_value = (price or 0) * f["lot_size"]
            margin = lot_value * FUTURES_MARGIN_PCT / 100
            pred = i.get("predicted_return_pct")
            out.append({
                "symbol": sym, "name": f["name"], "underlying": f["underlying"], "lot_size": f["lot_size"],
                "last_price": price, "as_of": i.get("as_of"), "change_today_pct": i.get("change_today_pct"),
                "predicted_return_pct": pred, "by_model": i.get("by_model", {}),
                "predicted_profit_per_lot": round(lot_value * pred / 100, 2) if pred is not None else None,
                "lot_value": round(lot_value, 2), "margin_per_lot": round(margin, 2),
                "margin_pct": FUTURES_MARGIN_PCT,
                "affordable_lots": int(free // margin) if margin else 0,
                "held": sym in self.broker.positions, "signals": i.get("signals", []),
            })
        return out

    def close(self, symbol: str, reason: str = "manual close") -> dict:
        symbol = symbol.upper()
        with self.lock:
            if symbol not in self.broker.positions:
                raise ValueError(f"No open position in {symbol}")
        price, _ = self.quote(symbol)
        now = self.clock()
        with self.lock:
            t = self.broker.close_position(symbol, price, now, reason)
            self.last_checked.pop(symbol, None)
            self._save()
            self._snapshot_equity(now)
            assert t is not None
            self._event(f"CLOSED {symbol} {reason}: {t.net_pnl:+,.2f} "
                        f"({t.net_pnl / (t.entry_price * t.qty) * 100:+.2f}%)")
        return with_return(t.to_dict())

    # ---------- settings ----------
    def update_settings(self, patch: dict) -> BotSettings:
        with self.lock:
            was = self.bot.auto_enabled
            self.bot = BotSettings.from_dict({**asdict(self.bot), **patch})
            self.store.kv_set("bot_settings", asdict(self.bot))
            if was != self.bot.auto_enabled:
                self._event(f"Auto trading {'ON' if self.bot.auto_enabled else 'OFF'}")
        return self.bot

    # ---------- reporting ----------
    def trades(self, source: str | None = None) -> list[dict]:
        rows = [with_return(r) for r in self.store.trades(self.run_id)]
        return [r for r in rows if not source or r.get("source") == source]

    def portfolio(self) -> dict:
        now = self.clock()
        with self.lock:
            b = self.broker
            positions = []
            for sym, p in b.positions.items():
                ltp = b.last_price.get(sym, p.avg_price)
                cost = abs(p.qty) * p.avg_price
                pnl = (ltp - p.avg_price) * p.qty
                fut = FUTURES.get(sym)
                margin = abs(p.qty) * ltp * b.margin_rate_for(sym)
                positions.append({**p.to_dict(), "side": "LONG" if p.qty > 0 else "SHORT",
                                  "instrument": "FUT" if fut else "EQ",
                                  "lots": abs(p.qty) // fut["lot_size"] if fut else None,
                                  "last_price": round(ltp, 2), "notional": round(cost, 2),
                                  # money actually tied up: full cost for shares, margin for futures
                                  "invested": round(margin if fut else cost, 2),
                                  "unrealized_pnl": round(pnl, 2),
                                  "unrealized_pct": round(pnl / cost * 100, 2) if cost else 0})
            # "cash" = money free for new trades (equals plain cash when holding shares only)
            equity, cash, initial = b.equity(), b.available_margin(), b.initial_capital
        trades = self.store.trades(self.run_id)
        today = now.date().isoformat()
        today_tr = [t for t in trades if t["exit_ts"].startswith(today)]
        tr_objs = [_trade(t) for t in trades]
        eq = [(r["ts"], r["equity"]) for r in self.store.equity(self.run_id)]
        if not eq or eq[-1][1] != round(equity, 2):
            eq.append((now.isoformat(timespec="seconds"), round(equity, 2)))
        by_source = {}
        for src in ("auto", "manual"):
            ts = [t for t in trades if t["source"] == src]
            wins = [t for t in ts if t["net_pnl"] > 0]
            by_source[src] = {"trades": len(ts), "net_pnl": round(sum(t["net_pnl"] for t in ts), 2),
                              "win_rate_pct": round(len(wins) / len(ts) * 100, 1) if ts else None}
        return {
            "initial_capital": initial,
            "cash": round(cash, 2),
            "equity": round(equity, 2),
            "invested": round(sum(p["invested"] for p in positions), 2),
            "unrealized_pnl": round(sum(p["unrealized_pnl"] for p in positions), 2),
            "realized_pnl": round(sum(t["net_pnl"] for t in trades), 2),
            "today_realized_pnl": round(sum(t["net_pnl"] for t in today_tr), 2),
            "today_trades": len(today_tr),
            "total_return_pct": round((equity - initial) / initial * 100, 2),
            "positions": sorted(positions, key=lambda p: p["entry_ts"], reverse=True),
            "by_source": by_source,
            "metrics": compute_metrics(tr_objs, eq, initial),
        }

    def trade_accuracy(self) -> dict:
        """Did the stock move the way the model forecast, trade by trade?"""
        out = {}
        rows = [with_return(r) for r in self.store.trades(self.run_id)]
        for src in ("all", "auto", "manual"):
            ts = [r for r in rows if r["model_correct"] is not None and (src == "all" or r["source"] == src)]
            right = [r for r in ts if r["model_correct"]]
            out[src] = {"scored_trades": len(ts), "model_right": len(right),
                        "model_accuracy_pct": round(len(right) / len(ts) * 100, 1) if ts else None,
                        "avg_predicted_pct": round(sum(r["predicted_return_pct"] for r in ts) / len(ts), 3) if ts else None,
                        "avg_actual_move_pct": round(sum(r["price_move_pct"] for r in ts) / len(ts), 3) if ts else None}
        return out

    def status(self) -> dict:
        now = self.clock()
        return {
            "server_time_ist": now.isoformat(timespec="seconds"),
            "market_open": self.market_open(now),
            "auto_enabled": self.bot.auto_enabled,
            "futures_auto_enabled": self.bot.futures_auto_enabled,
            "halted": self.halted,
            "last_loop": self.last_loop.isoformat(timespec="seconds") if self.last_loop else None,
            "last_error": self.last_error,
        }


def with_return(t: dict) -> dict:
    cost = t["entry_price"] * t["qty"]
    move = (t["exit_price"] / t["entry_price"] - 1) * 100 if t["entry_price"] else 0.0
    pred = t.get("predicted_return_pct")
    # The model forecasts a price direction; it is "right" if the price moved that way while the trade was open.
    correct = None if pred is None or pred == 0 or move == 0 else (pred > 0) == (move > 0)
    return {**t, "return_pct": round(t["net_pnl"] / cost * 100, 2) if cost else 0.0,
            "price_move_pct": round(move, 3), "model_correct": correct}


def _trade(r: dict) -> Trade:
    keep = {f.name for f in fields(Trade)}
    d = {k: v for k, v in r.items() if k in keep}
    d["entry_ts"] = datetime.fromisoformat(d["entry_ts"])
    d["exit_ts"] = datetime.fromisoformat(d["exit_ts"])
    d["source"] = d.get("source") or ""
    return Trade(**d)
