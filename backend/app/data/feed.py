"""Market data. `DataFeed` is the interface; `YFinanceFeed` is the free starter implementation.

yfinance limits for NSE: 1m bars -> last 7 days, 5m/15m/30m -> last 60 days,
1h -> ~2 years, 1d -> decades. Intraday data can be a few minutes delayed.
Swap in an Upstox/Dhan feed later by implementing the same two methods.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from app.config import IST, Settings
from app.models import Bar

INTERVAL_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "1d": 1440}


# App symbol -> Yahoo ticker for indices. Index futures are simulated off the index price
# (real futures trade at a small premium, the "basis", which this ignores).
INDEX_TICKERS = {
    "NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK", "INDIAVIX": "^INDIAVIX",
    "NIFTY-FUT": "^NSEI", "BANKNIFTY-FUT": "^NSEBANK",
}


def nse_ticker(symbol: str) -> str:
    s = symbol.upper().strip()
    if s in INDEX_TICKERS:
        return INDEX_TICKERS[s]
    return s if s.endswith((".NS", ".BO")) or s.startswith("^") else f"{s}.NS"


def plain_symbol(ticker: str) -> str:
    return ticker.removesuffix(".NS").removesuffix(".BO")


class DataFeed(ABC):
    @abstractmethod
    def history(self, symbol: str, interval: str, period: str) -> list[Bar]: ...

    def history_many(self, symbols: list[str], interval: str, period: str) -> dict[str, list[Bar]]:
        return {s.upper(): self.history(s, interval, period) for s in symbols}

    @abstractmethod
    def latest_completed(self, symbol: str, interval: str, now: datetime) -> list[Bar]:
        """Recent bars, excluding the one still forming."""


class YFinanceFeed(DataFeed):
    def __init__(self, settings: Settings):
        self.s = settings

    def _download(self, symbol: str, interval: str, period: str) -> list[Bar]:
        import yfinance as yf

        df = yf.Ticker(nse_ticker(symbol)).history(period=period, interval=interval, auto_adjust=True)
        if df is None or df.empty:
            return []
        df = df.dropna(subset=["Open", "High", "Low", "Close"])
        idx = df.index.tz_convert(IST) if df.index.tz is not None else df.index.tz_localize(IST)
        sym = plain_symbol(symbol.upper())
        bars = []
        for ts, r in zip(idx, df.itertuples()):
            ts = ts.to_pydatetime()
            if interval != "1d" and not (self.s.market_open <= ts.time() < self.s.market_close):
                continue
            bars.append(Bar(sym, ts, float(r.Open), float(r.High), float(r.Low), float(r.Close), float(r.Volume)))
        return bars

    def history(self, symbol: str, interval: str, period: str) -> list[Bar]:
        return self._download(symbol, interval, period)

    def history_many(self, symbols: list[str], interval: str, period: str) -> dict[str, list[Bar]]:
        """One batched download for many symbols (much faster than one call each)."""
        import yfinance as yf

        if not symbols:
            return {}
        tickers = [nse_ticker(s) for s in symbols]
        df = yf.download(tickers, period=period, interval=interval, group_by="ticker",
                         auto_adjust=True, threads=True, progress=False)
        out: dict[str, list[Bar]] = {}
        for sym, tk in zip(symbols, tickers):
            sym = plain_symbol(sym.upper())
            try:
                sub = df[tk] if len(tickers) > 1 or tk in df.columns.get_level_values(0) else df
            except KeyError:
                out[sym] = []
                continue
            sub = sub.dropna(subset=["Open", "High", "Low", "Close"])
            if sub.empty:
                out[sym] = []
                continue
            idx = sub.index.tz_convert(IST) if sub.index.tz is not None else sub.index.tz_localize(IST)
            bars = []
            for ts, o, h, l, c, v in zip(idx, sub["Open"], sub["High"], sub["Low"], sub["Close"], sub["Volume"]):
                ts = ts.to_pydatetime()
                if interval != "1d" and not (self.s.market_open <= ts.time() < self.s.market_close):
                    continue
                bars.append(Bar(sym, ts, float(o), float(h), float(l), float(c), float(v or 0)))
            out[sym] = bars
        return out

    def latest_completed(self, symbol: str, interval: str, now: datetime) -> list[Bar]:
        period = "5d" if interval != "1d" else "1mo"
        minutes = INTERVAL_MINUTES[interval]
        from datetime import timedelta
        return [b for b in self._download(symbol, interval, period)
                if b.ts + timedelta(minutes=minutes) <= now]
