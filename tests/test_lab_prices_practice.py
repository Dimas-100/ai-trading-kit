import json
import urllib.error

import pytest

from aitk import lab, paths, practice, prices, strategies
from aitk.engine.data import SyntheticBars

from .conftest import MemoryStore

BARS = SyntheticBars(seed=3, n=1500, start="2016-01-04").bars("SPY", 1500)


# ── lab ───────────────────────────────────────────────────────────────────────
def test_evaluate_reports_and_verdict():
    r = lab.evaluate("sma_cross", BARS, symbol="spy")
    assert r.symbol == "SPY" and r.first == BARS[0].ts and r.last == BARS[-1].ts
    for key in ("total_return_pct", "buy_hold_return_pct", "max_drawdown_pct", "trades", "profit_factor", "sharpe",
                "final_value"):
        assert key in r.metrics
    assert any("buying and holding" in v for v in r.verdict)
    assert any("ignores taxes" in v for v in r.verdict)
    assert isinstance(r.as_dict()["trades"], list)


def test_evaluate_errors_are_worded_for_people():
    with pytest.raises(lab.LabError) as exc:
        lab.evaluate("nope", BARS)
    assert "no strategy called 'nope'" in str(exc.value)
    with pytest.raises(lab.LabError) as exc:
        lab.evaluate("sma_cross", BARS[:30])
    assert "not enough" in str(exc.value)
    with pytest.raises(lab.LabError) as exc:
        lab.evaluate("sma_cross", BARS, params={"bogus": 1})
    assert "does not accept" in str(exc.value)
    with pytest.raises(lab.LabError):
        lab.evaluate("sma_cross", BARS, params={"fast": 100, "slow": 10})


def test_verdict_for_no_trades_and_few_trades():
    base = {"trades": 0, "total_return_pct": 0, "buy_hold_return_pct": 1, "max_drawdown_pct": 0, "exposure_pct": 0}
    assert "never triggered" in lab.verdict(base)[0]
    few = {**base, "trades": 5}
    assert "Only 5 trades" in lab.verdict(few)[0]


def test_compare_ranks_and_skips_failures():
    rows = lab.compare(["buy_hold", "sma_cross", "nope"], BARS, symbol="SPY")
    assert [r.strategy for r in rows][0] in ("buy_hold", "sma_cross") and len(rows) == 2
    assert rows[0].metrics["total_return_pct"] >= rows[1].metrics["total_return_pct"]


def test_sweep_splits_history_and_judges_on_unseen_part():
    res = lab.sweep("sma_cross", BARS, {"fast": [10, 20], "slow": [50, 100]}, symbol="SPY")
    assert res.tried == 4 and res.best in res.rows and res.split_at > BARS[0].ts
    assert res.rows[0]["first_return_pct"] >= res.rows[-1]["first_return_pct"]
    assert any("unseen" in v or "had not seen" in v for v in res.verdict)
    with pytest.raises(lab.LabError):
        lab.sweep("sma_cross", BARS, {}, symbol="SPY")
    with pytest.raises(lab.LabError):
        lab.sweep("sma_cross", BARS, {"fast": list(range(600))}, symbol="SPY")
    with pytest.raises(lab.LabError):
        lab.sweep("sma_cross", BARS, {"fast": [10]}, train_fraction=0.1)


# ── prices ────────────────────────────────────────────────────────────────────
def test_pricebook_demo_then_files(home):
    book = prices.PriceBook()
    assert book.kind("SPY") == prices.DEMO and len(book.all_bars("SPY")) > 2000
    prices.write_csv("SPY", BARS[:100])
    book = prices.PriceBook()
    assert book.kind("SPY") == prices.FILES and len(book.all_bars("SPY")) == 100
    assert prices.downloaded() == ["SPY"]
    with pytest.raises(prices.PriceError):
        prices.clean_symbol("not a symbol!")
    with pytest.raises(prices.PriceError):
        prices.PriceBook(allow_demo=False).all_bars("QQQ")


def test_import_csv_accepts_yahoo_style_and_rejects_bad(home, tmp_path):
    f = tmp_path / "x.csv"
    f.write_text("Date,Open,High,Low,Close,Adj Close,Volume\n2024-01-02,10,11,9,10,5,100\n2024-01-03,10,12,9,11,5.5,100\n",
                 encoding="utf-8")
    path, n = prices.import_csv(f, "xyz")
    assert n == 2 and path.name == "XYZ.csv"
    bars = prices.PriceBook().all_bars("XYZ")
    assert bars[0].close == 5 and bars[0].open == 5           # scaled to the adjusted close
    bad = tmp_path / "bad.csv"
    bad.write_text("date,close\n01/02/2024,1\n", encoding="utf-8")
    with pytest.raises(prices.PriceError):
        prices.import_csv(bad, "BAD")
    with pytest.raises(prices.PriceError):
        prices.import_csv(tmp_path / "missing.csv", "M")


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def read(self):
        return json.dumps(self.payload).encode()


def test_download_tiingo_and_alpaca_with_fake_openers(home):
    store = MemoryStore({"tiingo:TIINGO_API_TOKEN": "tok"})
    seen = {}

    def tiingo(request, timeout=0):
        seen["auth"] = request.get_header("Authorization")
        seen["url"] = request.full_url
        return FakeResponse([{"date": "2024-01-02T00:00:00.000Z", "adjOpen": 1, "adjHigh": 2, "adjLow": 0.5,
                              "adjClose": 1.5, "adjVolume": 10},
                             {"date": "2024-01-03T00:00:00.000Z", "adjOpen": 1, "adjHigh": 2, "adjLow": 0.5,
                              "adjClose": 1.6, "adjVolume": 10}])
    path, n, provider = prices.download("spy", store, years=1, opener=tiingo)
    assert n == 2 and provider == "tiingo" and seen["auth"] == "Token tok" and "/tiingo/daily/spy/prices" in seen["url"]

    store = MemoryStore({"alpaca:ALPACA_API_KEY": "k", "alpaca:ALPACA_SECRET_KEY": "s"})
    pages = iter([{"bars": {"QQQ": [{"t": "2024-01-02T05:00:00Z", "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 1}]},
                   "next_page_token": "p2"},
                  {"bars": {"QQQ": [{"t": "2024-01-03T05:00:00Z", "o": 1, "h": 2, "l": 0.5, "c": 1.6, "v": 1}]},
                   "next_page_token": None}])

    def alpaca(request, timeout=0):
        assert request.get_header("Apca-api-key-id") == "k"
        return FakeResponse(next(pages))
    path, n, provider = prices.download("QQQ", store, opener=alpaca)
    assert n == 2 and provider == "alpaca" and prices.downloaded() == ["QQQ", "SPY"]


def test_download_errors(home):
    with pytest.raises(prices.PriceError) as exc:
        prices.download("SPY", MemoryStore())
    assert "aitk prices key" in str(exc.value)

    def refused(request, timeout=0):
        raise urllib.error.HTTPError(request.full_url, 401, "x", {}, None)
    with pytest.raises(prices.PriceError) as exc:
        prices.download("SPY", MemoryStore({"tiingo:TIINGO_API_TOKEN": "t"}), opener=refused)
    assert "refused the key" in str(exc.value)


# ── practice ──────────────────────────────────────────────────────────────────
def test_practice_lifecycle(home):
    acct = practice.Practice()
    with pytest.raises(practice.PracticeError):
        acct.status()
    st = acct.start(cash=5000)
    assert st.cash == 5000 and st.today < acct.book.all_bars("SPY")[-1].ts
    with pytest.raises(practice.PracticeError):
        acct.start()
    out = acct.order("buy", "spy", 3)
    assert out["accepted"] and out["symbol"] == "SPY" and out["placed_on"] == st.today
    st2, fills = acct.advance(1)
    assert len(fills) == 1 and fills[0].symbol == "SPY" and st2.positions[0]["shares"] == 3 and st2.today > st.today
    price = st2.positions[0]["price"]
    acct.order("sell", "SPY", 3, stop=round(price * 0.9, 2), good_til_cancelled=True)
    assert len(acct.status().open_orders) == 1
    order_id = acct.status().open_orders[0]["client_order_id"]
    assert acct.cancel(order_id[:8]) is True
    assert acct.status().open_orders == []
    with pytest.raises(practice.PracticeError):
        acct.order("sell", "SPY", 99)
    with pytest.raises(practice.PracticeError):
        acct.order("hold", "SPY", 1)
    st3, _ = acct.advance(300)
    assert st3.today == acct.book.all_bars("SPY")[-1].ts
    with pytest.raises(practice.PracticeError):
        acct.advance(1)
    assert len(acct.history()) == 1
    st4 = acct.start(cash=100, replace=True)
    assert st4.cash == 100 and st4.positions == []


def test_practice_start_on_a_date_and_stop_fills(home):
    acct = practice.Practice()
    days = [b.ts for b in acct.book.all_bars("SPY")]
    st = acct.start(start=days[500])
    assert st.today == days[500]
    acct.order("buy", "SPY", 1)
    acct.advance(1)
    pos = acct.status().positions[0]
    acct.order("sell", "SPY", 1, stop=round(pos["price"] * 0.9, 2), good_til_cancelled=True)
    st, fills = acct.advance(400)
    assert st.positions == [] and any(f.side.value == "SELL" for f in fills)
    with pytest.raises(practice.PracticeError):
        acct.start(start="1990-01-01", replace=True)


# ── strategies ────────────────────────────────────────────────────────────────
def test_user_strategy_create_load_and_errors(home):
    path = strategies.create("my_idea")
    assert path.endswith("my_idea.py") and "my_idea" in strategies.names()
    with pytest.raises(strategies.StrategyError):
        strategies.create("my_idea")
    with pytest.raises(strategies.StrategyError):
        strategies.create("Bad Name!")
    broken = paths.strategies_dir() / "broken.py"
    broken.write_text("this is not python", encoding="utf-8")
    strategies.load_user_strategies()
    assert "broken.py" in strategies.load_errors and "broken" not in strategies.names()
    with pytest.raises(lab.LabError) as exc:
        lab.evaluate("broken", BARS)
    assert "could not be loaded" in str(exc.value)
    described = {d["name"]: d for d in strategies.describe()}
    assert described["my_idea"]["level"] == "yours" and described["my_idea"]["settings"]["period"] == 50
    report = lab.evaluate("my_idea", BARS, params={"period": 30})
    assert report.metrics["bars"] == len(BARS)


def test_parse_settings_and_grid():
    assert strategies.parse_settings(["fast=10", "x=1.5", "name=abc"]) == {"fast": 10, "x": 1.5, "name": "abc"}
    assert strategies.parse_grid(["fast=10,20", "slow=50"]) == {"fast": [10, 20], "slow": [50]}
    with pytest.raises(strategies.StrategyError):
        strategies.parse_settings(["fast"])
