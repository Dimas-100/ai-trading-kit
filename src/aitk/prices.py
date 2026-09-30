"""Price history for testing ideas.

Three places prices can come from, in the order the kit looks:
1. a file you downloaded or imported (kept in the kit's home folder, one CSV per symbol);
2. nothing on disk: made-up DEMO prices, so every command works before any key exists.

Downloads use the provider's official API with the person's own free key, and the files stay on
their computer. The kit ships no market data and re-serves none."""
from __future__ import annotations

import csv
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from . import paths
from .engine.data import CsvBars, DataError, SyntheticBars, sort_bars
from .engine.models import Bar

DEMO, FILES = "demo", "files"
PROVIDERS = {
    "tiingo": {"name": "Tiingo", "store_as": "tiingo", "fields": (("TIINGO_API_TOKEN", "Tiingo API token"),),
               "signup": "https://www.tiingo.com (free account, then Account > API > Token)",
               "note": "30+ years of daily prices, adjusted for splits and dividends. Free: 50 requests an hour."},
    "alpaca": {"name": "Alpaca", "store_as": "alpaca",
               "fields": (("ALPACA_API_KEY", "Alpaca API key"), ("ALPACA_SECRET_KEY", "Alpaca API secret")),
               "signup": "https://app.alpaca.markets (the same keys as the Alpaca connection)",
               "note": "Daily prices since 2016, adjusted. Free, and uses the keys you may already have stored."},
}
_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


class PriceError(ValueError):
    pass


def clean_symbol(symbol: str) -> str:
    s = str(symbol or "").strip().upper()
    if not _SYMBOL.match(s):
        raise PriceError(f"'{symbol}' does not look like a ticker symbol (for example SPY or AAPL)")
    return s


def file_for(symbol: str) -> Path:
    return paths.prices_dir() / f"{clean_symbol(symbol)}.csv"


def downloaded() -> list[str]:
    folder = paths.prices_dir()
    if not folder.exists():
        return []
    return sorted(p.stem for p in folder.glob("*.csv"))


class PriceBook:
    """A bar source over the kit's price folder, falling back to demo prices per symbol."""

    def __init__(self, allow_demo: bool = True, seed: int = 7, demo_bars: int = 2520):
        self._files = CsvBars(paths.prices_dir())
        self._demo = SyntheticBars(seed=seed, n=demo_bars, start="2015-01-02")
        self.allow_demo = allow_demo

    def kind(self, symbol: str) -> str:
        return FILES if file_for(symbol).exists() else DEMO

    def _source(self, symbol: str):
        if file_for(symbol).exists():
            return self._files
        if not self.allow_demo:
            raise PriceError(f"no prices for {symbol} yet. Run: aitk prices get {symbol}")
        return self._demo

    def bars(self, symbol: str, n: int, as_of: str | None = None) -> list[Bar]:
        symbol = clean_symbol(symbol)
        try:
            return self._source(symbol).bars(symbol, n, as_of)
        except DataError as exc:
            raise PriceError(str(exc)) from exc

    def all_bars(self, symbol: str) -> list[Bar]:
        return self.bars(symbol, 10 ** 9)

    def last_price(self, symbol: str, as_of: str | None = None) -> float:
        symbol = clean_symbol(symbol)
        try:
            return self._source(symbol).last_price(symbol, as_of)
        except DataError as exc:
            raise PriceError(str(exc)) from exc


def write_csv(symbol: str, bars: list[Bar]) -> Path:
    if not bars:
        raise PriceError(f"no prices came back for {symbol}")
    target = file_for(symbol)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "open", "high", "low", "close", "volume"])
        for b in sort_bars(bars):
            w.writerow([b.ts, b.open, b.high, b.low, b.close, b.volume])
    tmp.replace(target)
    return target


def import_csv(source: str | Path, symbol: str) -> tuple[Path, int]:
    symbol = clean_symbol(symbol)
    src = Path(source).expanduser()
    if not src.is_file():
        raise PriceError(f"no file at {src}")
    try:
        with src.open(newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise PriceError(f"could not read {src}: {exc}") from exc
    bars = []
    for raw in rows:
        r = {str(k).strip().lower(): (v or "").strip() for k, v in raw.items() if k}
        ts = next((r[k] for k in ("date", "timestamp", "datetime", "time", "ts") if r.get(k)), "")
        ts = ts[:10]
        close = r.get("adj close") or r.get("adj_close") or r.get("adjclose") or r.get("close")
        try:
            date.fromisoformat(ts)
            c = float(close)
            factor = c / float(r["close"]) if r.get("close") and float(r["close"]) else 1.0
            bars.append(Bar(ts, float(r["open"]) * factor, float(r["high"]) * factor, float(r["low"]) * factor,
                            c, float(r.get("volume") or 0)))
        except (KeyError, TypeError, ValueError) as exc:
            raise PriceError(f"{src.name} needs columns date, open, high, low, close with dates written as "
                             f"YYYY-MM-DD (problem near '{ts or raw}')") from exc
    return write_csv(symbol, bars), len(bars)


# ── downloads ─────────────────────────────────────────────────────────────────
def _get_json(url: str, headers: dict, timeout: float = 30.0, opener=None):
    request = urllib.request.Request(url, headers={"User-Agent": "ai-trading-kit", "Accept": "application/json",
                                                   **headers})
    do = opener or urllib.request.urlopen
    try:
        with do(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise PriceError("the provider refused the key. Enter it again with: aitk prices key") from exc
        if exc.code == 404:
            raise PriceError("the provider does not know that symbol") from exc
        if exc.code == 429:
            raise PriceError("the free limit was reached. Wait an hour and try again") from exc
        raise PriceError(f"the provider answered with HTTP {exc.code}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise PriceError(f"could not reach the provider ({getattr(exc, 'reason', exc)})") from exc
    except ValueError as exc:
        raise PriceError("the provider sent something that is not JSON") from exc


def fetch_tiingo(symbol: str, start: str, end: str, keys: dict, opener=None) -> list[Bar]:
    q = urllib.parse.urlencode({"startDate": start, "endDate": end, "format": "json"})
    url = f"https://api.tiingo.com/tiingo/daily/{urllib.parse.quote(symbol.lower())}/prices?{q}"
    rows = _get_json(url, {"Authorization": f"Token {keys['TIINGO_API_TOKEN']}"}, opener=opener)
    if not isinstance(rows, list):
        raise PriceError(str(rows.get("detail", "unexpected answer from Tiingo")) if isinstance(rows, dict)
                         else "unexpected answer from Tiingo")
    out = []
    for r in rows:
        try:
            out.append(Bar(str(r["date"])[:10], float(r["adjOpen"]), float(r["adjHigh"]), float(r["adjLow"]),
                           float(r["adjClose"]), float(r.get("adjVolume") or 0)))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def fetch_alpaca(symbol: str, start: str, end: str, keys: dict, opener=None) -> list[Bar]:
    headers = {"APCA-API-KEY-ID": keys["ALPACA_API_KEY"], "APCA-API-SECRET-KEY": keys["ALPACA_SECRET_KEY"]}
    out, token = [], None
    for _ in range(50):
        params = {"symbols": symbol, "timeframe": "1Day", "start": start, "end": end, "adjustment": "all",
                  "feed": "iex", "limit": "10000"}
        if token:
            params["page_token"] = token
        doc = _get_json("https://data.alpaca.markets/v2/stocks/bars?" + urllib.parse.urlencode(params), headers,
                        opener=opener)
        for r in (doc.get("bars") or {}).get(symbol, []):
            try:
                out.append(Bar(str(r["t"])[:10], float(r["o"]), float(r["h"]), float(r["l"]), float(r["c"]),
                               float(r.get("v") or 0)))
            except (KeyError, TypeError, ValueError):
                continue
        token = doc.get("next_page_token")
        if not token:
            break
    return out


FETCHERS = {"tiingo": fetch_tiingo, "alpaca": fetch_alpaca}


def provider_keys(provider: str, store) -> dict | None:
    info = PROVIDERS[provider]
    keys = {k: store.get(info["store_as"], k) for k, _ in info["fields"]}
    return keys if all(keys.values()) else None


def available_provider(store) -> str | None:
    return next((p for p in PROVIDERS if provider_keys(p, store)), None)


def download(symbol: str, store, provider: str | None = None, years: int = 20, today: date | None = None,
             opener=None) -> tuple[Path, int, str]:
    symbol = clean_symbol(symbol)
    provider = provider or available_provider(store)
    if provider is None:
        raise PriceError("no price provider is set up yet. Run: aitk prices key")
    if provider not in PROVIDERS:
        raise PriceError(f"unknown provider '{provider}'. Choose from: {', '.join(PROVIDERS)}")
    keys = provider_keys(provider, store)
    if keys is None:
        raise PriceError(f"no {PROVIDERS[provider]['name']} key is stored. Run: aitk prices key {provider}")
    end = today or date.today()
    start = end - timedelta(days=int(365.25 * max(1, years)))
    bars = FETCHERS[provider](symbol, start.isoformat(), end.isoformat(), keys, opener=opener)
    seen, unique = set(), []
    for b in sort_bars(bars):
        if b.ts not in seen and min(b.open, b.high, b.low, b.close) > 0:
            seen.add(b.ts)
            unique.append(b)
    if not unique:
        raise PriceError(f"{PROVIDERS[provider]['name']} returned no prices for {symbol}")
    unique = contiguous_tail(unique)
    return write_csv(symbol, unique), len(unique), provider


MAX_GAP_DAYS = 45


def contiguous_tail(bars: list[Bar]) -> list[Bar]:
    """Drop stray early bars that sit before a long hole in the history (a provider's free feed
    sometimes returns one odd bar years before its real coverage begins). A backtest that starts on such
    a bar would compare against a buy-and-hold figure nobody could have earned."""
    cut = 0
    for i in range(1, len(bars)):
        try:
            gap = (date.fromisoformat(bars[i].ts[:10]) - date.fromisoformat(bars[i - 1].ts[:10])).days
        except ValueError:
            continue
        if gap > MAX_GAP_DAYS:
            cut = i
    return bars[cut:]
