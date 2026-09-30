"""Bar sources that need no credentials: a CSV loader and a seeded synthetic random walk.
Both hand back ascending bars through `sort_bars` — a stable ascending sort, never a blind reverse
(a reverse applied to already-ascending input silently time-mirrors the series)."""
from __future__ import annotations

import csv
import random
import re
from datetime import date, timedelta
from pathlib import Path

from .models import Bar


class DataError(ValueError):
    """The data source could not serve the request (missing symbol/column, bad timestamp)."""


_ISO_TS = re.compile(r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2})?)?$")


def sort_bars(bars: list[Bar]) -> list[Bar]:
    return sorted(bars, key=lambda b: b.ts)


def _cut(bars: list[Bar], n: int, as_of: str | None) -> list[Bar]:
    if as_of is not None:
        bars = [b for b in bars if b.ts <= as_of]
    return bars[-n:] if n > 0 else []


_TS_KEYS = ("date", "time", "timestamp", "datetime", "ts")
_REQUIRED = ("open", "high", "low", "close")


def _get(row: dict, keys) -> object:
    for k in keys:
        if k in row and row[k] not in (None, ""):
            return row[k]
    return None


class CsvBars:
    """`path` is a directory of `<SYMBOL>.csv` files, or one CSV with a `symbol` column.
    Header names are case-insensitive; the timestamp column is any of date/time/timestamp/datetime/ts
    and must be ISO-8601 (YYYY-MM-DD[THH:MM[:SS]]) so lexicographic order is chronological order."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._cache: dict[str, list[Bar]] = {}

    def _rows(self, symbol: str) -> list[dict]:
        if self.path.is_dir():
            f = self.path / f"{symbol}.csv"
            if not f.exists():
                raise DataError(f"no CSV for {symbol}: expected {f}")
            with f.open(newline="") as fh:
                return list(csv.DictReader(fh))
        if not self.path.exists():
            raise DataError(f"CSV path does not exist: {self.path}")
        with self.path.open(newline="") as fh:
            rows = list(csv.DictReader(fh))
        rows = [
            r for r in rows
            if str(
                _get({str(k).lower(): v for k, v in r.items()}, ("symbol", "ticker")) or ""
            ).strip().upper() == symbol
        ]
        if not rows:
            raise DataError(f"no rows for {symbol} in {self.path} (needs a 'symbol' column)")
        return rows

    def _load(self, symbol: str) -> list[Bar]:
        symbol = symbol.strip().upper()
        if symbol in self._cache:
            return self._cache[symbol]
        bars: list[Bar] = []
        for raw in self._rows(symbol):
            r = {str(k).strip().lower(): v for k, v in raw.items() if k is not None}
            missing = [k for k in _REQUIRED if k not in r]
            if missing or not any(k in r for k in _TS_KEYS):
                raise DataError(f"{symbol}: CSV needs columns date,{','.join(_REQUIRED)} "
                                f"(missing {missing or 'timestamp'})")
            ts = str(_get(r, _TS_KEYS)).strip()
            if not _ISO_TS.match(ts):
                raise DataError(f"{symbol}: timestamp {ts!r} is not ISO-8601 (YYYY-MM-DD); "
                                "non-ISO dates would sort out of order")
            try:
                bars.append(Bar(ts=ts, open=float(r["open"]), high=float(r["high"]), low=float(r["low"]),
                                close=float(r["close"]), volume=float(r.get("volume") or 0.0)))
            except (TypeError, ValueError) as exc:
                raise DataError(f"{symbol}: bad numeric value on {ts}: {exc}") from exc
        self._cache[symbol] = sort_bars(bars)
        return self._cache[symbol]

    def bars(self, symbol: str, n: int, as_of: str | None = None) -> list[Bar]:
        return _cut(self._load(symbol), n, as_of)

    def last_price(self, symbol: str, as_of: str | None = None) -> float:
        bars = self.bars(symbol, 1, as_of)
        if not bars:
            raise DataError(f"{symbol}: no bars at or before {as_of}")
        return bars[-1].close


class SyntheticBars:
    """Seeded geometric random walk with alternating drift regimes (so a trend-following demo
    produces trades). Deterministic per (seed, symbol). Weekdays only, starting at `start`."""

    def __init__(self, seed: int = 7, n: int = 1500, start: str = "2018-01-01", start_price: float = 100.0,
                 regime_len: int = 120, up_drift: float = 0.0012, down_drift: float = -0.0008,
                 vol: float = 0.012):
        self.seed, self.n, self.start_price = int(seed), int(n), float(start_price)
        self.start = date.fromisoformat(start)
        self.regime_len, self.up_drift, self.down_drift, self.vol = regime_len, up_drift, down_drift, vol
        self._cache: dict[str, list[Bar]] = {}

    def _generate(self, symbol: str) -> list[Bar]:
        rng = random.Random(f"{self.seed}:{symbol}")
        bars: list[Bar] = []
        d = self.start
        close = self.start_price
        i = 0
        while len(bars) < self.n:
            if d.weekday() < 5:
                drift = self.up_drift if (i // self.regime_len) % 2 == 0 else self.down_drift
                prev = close
                close = max(0.5, prev * (1 + drift + rng.gauss(0.0, self.vol)))
                open_ = max(0.5, prev * (1 + rng.gauss(0.0, self.vol / 4)))
                hi = max(open_, close) * (1 + abs(rng.gauss(0.0, self.vol / 3)))
                lo = max(0.25, min(open_, close) * (1 - abs(rng.gauss(0.0, self.vol / 3))))
                vol_ = float(int(1_000_000 * (1 + abs(rng.gauss(0.0, 0.3)))))
                bars.append(Bar(ts=d.isoformat(), open=round(open_, 4), high=round(hi, 4),
                                low=round(lo, 4), close=round(close, 4), volume=vol_))
                i += 1
            d += timedelta(days=1)
        return bars

    def bars(self, symbol: str, n: int, as_of: str | None = None) -> list[Bar]:
        symbol = symbol.strip().upper()
        if symbol not in self._cache:
            self._cache[symbol] = self._generate(symbol)
        return _cut(self._cache[symbol], n, as_of)

    def last_price(self, symbol: str, as_of: str | None = None) -> float:
        bars = self.bars(symbol, 1, as_of)
        if not bars:
            raise DataError(f"{symbol}: no synthetic bars at or before {as_of}")
        return bars[-1].close
