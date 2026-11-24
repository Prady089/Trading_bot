"""SQLite storage for runs, trades, equity curve and events.
Swap for PostgreSQL when deploying multiple instances."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from app.config import IST
from app.models import Trade

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,              -- 'backtest' | 'paper'
    strategy TEXT NOT NULL,
    symbols TEXT NOT NULL,
    interval TEXT NOT NULL,
    period TEXT,
    params TEXT NOT NULL,
    initial_capital REAL NOT NULL,
    status TEXT NOT NULL,            -- 'running' | 'stopped' | 'done'
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metrics TEXT,
    state TEXT
);
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    symbol TEXT, direction INTEGER, qty INTEGER,
    entry_ts TEXT, entry_price REAL, exit_ts TEXT, exit_price REAL,
    gross_pnl REAL, charges REAL, net_pnl REAL, entry_reason TEXT, exit_reason TEXT
);
CREATE TABLE IF NOT EXISTS equity (
    run_id INTEGER NOT NULL REFERENCES runs(id),
    ts TEXT NOT NULL, equity REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    ts TEXT NOT NULL, level TEXT NOT NULL, message TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY, value TEXT NOT NULL
);
-- Every live forecast the model makes, scored 1 hour later against what really happened.
CREATE TABLE IF NOT EXISTS predictions (
    bar_ts TEXT NOT NULL,            -- 15m candle the forecast was made from (start time)
    symbol TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT 'ridge_base',
    rank INTEGER NOT NULL,           -- 1 = model's top pick for that candle; 0 = an index (NIFTY, BANKNIFTY)
    price REAL NOT NULL,             -- close of that candle
    predicted_return_pct REAL NOT NULL,
    model_trained_at TEXT,
    actual_return_pct REAL,          -- filled in once the candle 1h later has closed
    resolved_at TEXT,
    PRIMARY KEY (bar_ts, symbol, model)
);
-- One row per retrain: the backtest accuracy on held-out data at that moment.
CREATE TABLE IF NOT EXISTS model_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trained_at TEXT NOT NULL,
    data_as_of TEXT,
    train_rows INTEGER, test_rows INTEGER,
    direction_accuracy_pct REAL, information_coefficient REAL,
    top5_avg_return_pct REAL, top5_hit_rate_pct REAL, market_avg_return_pct REAL,
    model TEXT DEFAULT 'ridge_base', always_up_pct REAL, fold_ic TEXT
);
CREATE INDEX IF NOT EXISTS ix_pred_unresolved ON predictions(resolved_at, bar_ts);
CREATE INDEX IF NOT EXISTS ix_trades_run ON trades(run_id);
CREATE INDEX IF NOT EXISTS ix_equity_run ON equity(run_id, ts);
CREATE INDEX IF NOT EXISTS ix_events_run ON events(run_id, id);
"""

TRADE_COLS = ["symbol", "direction", "qty", "entry_ts", "entry_price", "exit_ts", "exit_price",
              "gross_pnl", "charges", "net_pnl", "entry_reason", "exit_reason", "source",
              "predicted_return_pct"]


def _now() -> str:
    return datetime.now(IST).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(SCHEMA)
            cols = {r[1] for r in c.execute("PRAGMA table_info(trades)")}
            if "source" not in cols:  # migrate databases created by v0.1
                c.execute("ALTER TABLE trades ADD COLUMN source TEXT DEFAULT ''")
            if "predicted_return_pct" not in cols:
                c.execute("ALTER TABLE trades ADD COLUMN predicted_return_pct REAL")
            self._migrate_models(c)

    @staticmethod
    def _migrate_models(c: sqlite3.Connection) -> None:
        """v0.3 -> v0.4: forecasts and retrain history are kept per model."""
        pcols = {r[1] for r in c.execute("PRAGMA table_info(predictions)")}
        if "model" not in pcols:
            c.executescript("""
                ALTER TABLE predictions RENAME TO predictions_v3;
                CREATE TABLE predictions (
                    bar_ts TEXT NOT NULL, symbol TEXT NOT NULL, model TEXT NOT NULL DEFAULT 'ridge_base',
                    rank INTEGER NOT NULL, price REAL NOT NULL, predicted_return_pct REAL NOT NULL,
                    model_trained_at TEXT, actual_return_pct REAL, resolved_at TEXT,
                    PRIMARY KEY (bar_ts, symbol, model));
                INSERT INTO predictions(bar_ts,symbol,model,rank,price,predicted_return_pct,model_trained_at,
                                        actual_return_pct,resolved_at)
                    SELECT bar_ts,symbol,'ridge_base',rank,price,predicted_return_pct,model_trained_at,
                           actual_return_pct,resolved_at FROM predictions_v3;
                DROP TABLE predictions_v3;
                CREATE INDEX IF NOT EXISTS ix_pred_unresolved ON predictions(resolved_at, bar_ts);
            """)
        mcols = {r[1] for r in c.execute("PRAGMA table_info(model_runs)")}
        for col, typ in (("model", "TEXT DEFAULT 'ridge_base'"), ("always_up_pct", "REAL"), ("fold_ic", "TEXT")):
            if col not in mcols:
                c.execute(f"ALTER TABLE model_runs ADD COLUMN {col} {typ}")
        c.execute("CREATE INDEX IF NOT EXISTS ix_pred_model ON predictions(model, bar_ts)")

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    def _exec(self, sql: str, args: tuple | list = ()) -> int:
        with self._lock, self._conn() as c:
            return c.execute(sql, args).lastrowid

    def _many(self, sql: str, rows: list) -> None:
        if rows:
            with self._lock, self._conn() as c:
                c.executemany(sql, rows)

    def _rows(self, sql: str, args: tuple = ()) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute(sql, args).fetchall()]

    # ---------- runs ----------
    def create_run(self, kind: str, strategy: str, symbols: list[str], interval: str,
                   period: str | None, params: dict, initial_capital: float, status: str) -> int:
        now = _now()
        return self._exec(
            "INSERT INTO runs(kind,strategy,symbols,interval,period,params,initial_capital,status,created_at,updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (kind, strategy, json.dumps(symbols), interval, period, json.dumps(params), initial_capital, status, now, now))

    def update_run(self, run_id: int, **fields) -> None:
        fields["updated_at"] = _now()
        for k in ("metrics", "state"):
            if k in fields and not isinstance(fields[k], str):
                fields[k] = json.dumps(fields[k])
        sets = ", ".join(f"{k}=?" for k in fields)
        self._exec(f"UPDATE runs SET {sets} WHERE id=?", (*fields.values(), run_id))

    @staticmethod
    def _decode(r: dict) -> dict:
        for k in ("symbols", "params", "metrics", "state"):
            if r.get(k):
                r[k] = json.loads(r[k])
        return r

    def get_run(self, run_id: int) -> dict | None:
        rows = self._rows("SELECT * FROM runs WHERE id=?", (run_id,))
        return self._decode(rows[0]) if rows else None

    def list_runs(self, kind: str | None = None, limit: int = 50) -> list[dict]:
        sql = "SELECT id,kind,strategy,symbols,interval,period,initial_capital,status,created_at,updated_at,metrics FROM runs"
        args: tuple = ()
        if kind:
            sql += " WHERE kind=?"
            args = (kind,)
        return [self._decode(r) for r in self._rows(sql + " ORDER BY id DESC LIMIT ?", (*args, limit))]

    def latest_run(self, kind: str) -> dict | None:
        rows = self._rows("SELECT * FROM runs WHERE kind=? ORDER BY id DESC LIMIT 1", (kind,))
        return self._decode(rows[0]) if rows else None

    # ---------- key/value settings ----------
    def kv_get(self, key: str, default=None):
        rows = self._rows("SELECT value FROM kv WHERE key=?", (key,))
        return json.loads(rows[0]["value"]) if rows else default

    def kv_set(self, key: str, value) -> None:
        self._exec("INSERT INTO kv(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                   (key, json.dumps(value)))

    # ---------- children ----------
    def add_trades(self, run_id: int, trades: list[Trade]) -> None:
        self._many(f"INSERT INTO trades(run_id,{','.join(TRADE_COLS)}) VALUES ({','.join('?' * (len(TRADE_COLS) + 1))})",
                   [(run_id, *[t.to_dict()[c] for c in TRADE_COLS]) for t in trades])

    def add_equity(self, run_id: int, points: list[tuple[str, float]]) -> None:
        self._many("INSERT INTO equity(run_id,ts,equity) VALUES (?,?,?)", [(run_id, ts, e) for ts, e in points])

    def add_events(self, run_id: int, events: list[tuple[str, str, str]]) -> None:
        self._many("INSERT INTO events(run_id,ts,level,message) VALUES (?,?,?,?)",
                   [(run_id, *e) for e in events])

    def trades(self, run_id: int) -> list[dict]:
        return self._rows("SELECT * FROM trades WHERE run_id=? ORDER BY exit_ts", (run_id,))

    def equity(self, run_id: int) -> list[dict]:
        return self._rows("SELECT ts, equity FROM equity WHERE run_id=? ORDER BY ts", (run_id,))

    def events(self, run_id: int, limit: int = 50) -> list[dict]:
        return self._rows("SELECT ts, level, message FROM events WHERE run_id=? ORDER BY id DESC LIMIT ?",
                          (run_id, limit))

    # ---------- model accuracy tracking ----------
    def add_predictions(self, rows: list[tuple]) -> None:
        """rows: (bar_ts, symbol, model, rank, price, predicted_return_pct, model_trained_at).
        The first forecast for a candle is kept; later rescans of the same candle are ignored."""
        self._many("INSERT OR IGNORE INTO predictions(bar_ts,symbol,model,rank,price,predicted_return_pct,"
                   "model_trained_at) VALUES (?,?,?,?,?,?,?)", rows)

    def unresolved_predictions(self) -> list[dict]:
        return self._rows("SELECT DISTINCT bar_ts, symbol, price FROM predictions WHERE resolved_at IS NULL")

    def resolve_predictions(self, rows: list[tuple]) -> None:
        """rows: (actual_return_pct, bar_ts, symbol)."""
        now = _now()
        self._many("UPDATE predictions SET actual_return_pct=?, resolved_at=? WHERE bar_ts=? AND symbol=?",
                   [(a, now, ts, sym) for a, ts, sym in rows])

    def resolved_predictions(self, since: str | None = None, model: str | None = None) -> list[dict]:
        sql = "SELECT * FROM predictions WHERE actual_return_pct IS NOT NULL"
        args: list = []
        if since:
            sql += " AND bar_ts >= ?"
            args.append(since)
        if model:
            sql += " AND model = ?"
            args.append(model)
        return self._rows(sql + " ORDER BY bar_ts, rank", tuple(args))

    def prediction_counts(self, model: str | None = None) -> dict:
        where, args = ("WHERE model = ?", (model,)) if model else ("", ())
        r = self._rows("SELECT COUNT(*) n, SUM(actual_return_pct IS NOT NULL) resolved, "
                       f"COUNT(DISTINCT bar_ts) scans FROM predictions {where}", args)[0]
        return {"total": r["n"] or 0, "resolved": r["resolved"] or 0, "scans": r["scans"] or 0}

    def add_model_run(self, stats: dict, data_as_of: str | None) -> None:
        self._exec("INSERT INTO model_runs(trained_at,data_as_of,train_rows,test_rows,direction_accuracy_pct,"
                   "information_coefficient,top5_avg_return_pct,top5_hit_rate_pct,market_avg_return_pct,"
                   "model,always_up_pct,fold_ic) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                   (stats["trained_at"], data_as_of, stats["train_rows"], stats["test_rows"],
                    stats["direction_accuracy_pct"], stats["information_coefficient"],
                    stats["top5_avg_return_pct"], stats["top5_hit_rate_pct"], stats["market_avg_return_pct"],
                    stats.get("model", "ridge_base"), stats.get("always_up_pct"),
                    json.dumps(stats.get("fold_ic", []))))

    def model_runs(self, limit: int = 100, model: str | None = None) -> list[dict]:
        where, args = ("WHERE model = ?", (model, limit)) if model else ("", (limit,))
        rows = self._rows(f"SELECT * FROM model_runs {where} ORDER BY id DESC LIMIT ?", args)
        for r in rows:
            r["fold_ic"] = json.loads(r["fold_ic"]) if r.get("fold_ic") else []
        return list(reversed(rows))
