import json

from aitk.engine.broker import Broker
from aitk.engine.models import Bar, Order, OrderType, PlaceResult, Side, TimeInForce
from aitk.engine.paper import PaperBroker


class Seq:
    """A bar source whose 'newest bar' advances with as_of."""
    def __init__(self, bars):
        self._bars = bars

    def bars(self, symbol, n, as_of=None):
        rows = [b for b in self._bars if as_of is None or b.ts <= as_of]
        return rows[-n:]

    def last_price(self, symbol, as_of=None):
        return self.bars(symbol, 1, as_of)[-1].close


BARS = [
    Bar("2024-01-02", 100, 101, 99, 100),
    Bar("2024-01-03", 102, 104, 101, 103),
    Bar("2024-01-04", 95, 96, 90, 92),
]


def broker(tmp_path, cash=10_000.0):
    return PaperBroker(Seq(BARS), tmp_path / "paper.json", starting_cash=cash)


def test_is_a_broker_and_always_armed(tmp_path):
    b = broker(tmp_path)
    assert isinstance(b, Broker) and b.armed() is True and b.account_id() == "paper"
    assert b.balance().cash == 10_000.0 and b.positions() == []


def test_market_buy_reserves_then_fills_on_next_bar(tmp_path):
    b = broker(tmp_path)
    b.sync(as_of="2024-01-02")
    res = b.place(Order(symbol="SPY", side=Side.BUY, quantity=10, order_type=OrderType.MARKET))
    assert isinstance(res, PlaceResult) and res.placed and res.order_id
    assert b.balance().buying_power == 10_000.0 - 10 * 100   # reserved at last price
    assert b.sync(as_of="2024-01-02") == []                    # same bar: nothing fills
    fills = b.sync(as_of="2024-01-03")
    assert len(fills) == 1 and fills[0].price == 102.0 and fills[0].quantity == 10
    pos = b.positions()
    assert pos[0].symbol == "SPY" and pos[0].quantity == 10 and pos[0].avg_cost == 102.0
    assert b.balance().cash == 10_000.0 - 1020.0 and b.open_orders() == []


def test_state_persists_across_instances(tmp_path):
    b = broker(tmp_path)
    b.sync(as_of="2024-01-02")
    b.place(Order(symbol="SPY", side=Side.BUY, quantity=1, order_type=OrderType.MARKET))
    again = PaperBroker(Seq(BARS), tmp_path / "paper.json")
    assert len(again.open_orders()) == 1
    assert json.loads((tmp_path / "paper.json").read_text())["cash"] == 10_000.0


def test_unaffordable_buy_is_rejected_in_preview_and_place(tmp_path):
    b = broker(tmp_path, cash=500.0)
    b.sync(as_of="2024-01-02")
    o = Order(symbol="SPY", side=Side.BUY, quantity=10, order_type=OrderType.MARKET)
    assert b.preview(o)["ok"] is False
    res = b.place(o)
    assert res.placed is False and "cash" in res.raw["error"]
    assert b.balance().cash == 500.0 and b.open_orders() == []


def test_sell_more_than_held_is_rejected(tmp_path):
    b = broker(tmp_path)
    b.sync(as_of="2024-01-02")
    res = b.place(Order(symbol="SPY", side=Side.SELL, quantity=1, order_type=OrderType.MARKET))
    assert res.placed is False and "shares" in res.raw["error"]


def test_stop_sell_gap_through_and_gtc_rests(tmp_path):
    b = broker(tmp_path)
    b.sync(as_of="2024-01-02")
    b.place(Order(symbol="SPY", side=Side.BUY, quantity=10, order_type=OrderType.MARKET))
    b.sync(as_of="2024-01-03")
    stop = Order(symbol="SPY", side=Side.SELL, quantity=10, order_type=OrderType.STOP, stop_price=98.0,
                 time_in_force=TimeInForce.GTC)
    assert b.place(stop).placed
    assert b.sync(as_of="2024-01-03") == []
    assert len(b.open_orders()) == 1 and b.open_orders()[0]["order_type"] == "STOP"
    fills = b.sync(as_of="2024-01-04")
    assert len(fills) == 1 and fills[0].price == 95.0             # gapped through the 98 stop
    assert b.positions() == [] and b.balance().cash == 10_000.0 - 1020.0 + 950.0


def test_day_limit_expires_when_it_does_not_fill(tmp_path):
    b = broker(tmp_path)
    b.sync(as_of="2024-01-02")
    b.place(Order(symbol="SPY", side=Side.BUY, quantity=1, order_type=OrderType.LIMIT, limit_price=95.0))
    assert b.sync(as_of="2024-01-03") == []                       # low 101 never touches 95
    assert b.open_orders() == [] and b.balance().buying_power == 10_000.0


def test_cancel_releases_reservation(tmp_path):
    b = broker(tmp_path)
    b.sync(as_of="2024-01-02")
    res = b.place(Order(symbol="SPY", side=Side.BUY, quantity=2, order_type=OrderType.MARKET))
    cid = b.open_orders()[0]["client_order_id"]
    assert b.cancel(cid)["cancelled"] is True and b.balance().buying_power == 10_000.0
    assert b.cancel("nope")["cancelled"] is False
    assert res.placed


def test_symbol_without_bars_is_rejected_not_raised(tmp_path):
    b = PaperBroker(Seq([]), tmp_path / "paper.json", starting_cash=10_000.0)      # a source with no bars at all
    o = Order(symbol="SPY", side=Side.BUY, quantity=1, order_type=OrderType.MARKET)
    pv = b.preview(o)
    assert pv["ok"] is False and pv["last_price"] is None and "no price" in pv["reason"]
    res = b.place(o)
    assert res.placed is False and "no price" in res.raw["error"]
    assert b.open_orders() == [] and b.balance().cash == 10_000.0


def test_buy_gap_up_beyond_cash_is_rejected_at_fill_not_filled_negative(tmp_path):
    b = PaperBroker(Seq(BARS), tmp_path / "paper.json", starting_cash=1000.0)
    b.sync(as_of="2024-01-02")
    assert b.place(Order(symbol="SPY", side=Side.BUY, quantity=10, order_type=OrderType.MARKET)).placed
    fills = b.sync(as_of="2024-01-03")           # opens at 102 -> needs 1020 > 1000 cash
    assert fills == [] and b.positions() == [] and b.open_orders() == []
    assert b.balance().cash == 1000.0
    assert b.state_view()["rejected"][0]["reason"].startswith("insufficient cash at fill")


def test_a_skipped_day_fills_on_the_first_newer_bar_not_the_newest(tmp_path):
    b = broker(tmp_path)
    b.sync(as_of="2024-01-02")
    assert b.place(Order(symbol="SPY", side=Side.BUY, quantity=10, order_type=OrderType.MARKET)).placed
    fills = b.sync(as_of="2024-01-04")                     # 01-03 was never synced
    assert len(fills) == 1 and fills[0].price == 102.0 and fills[0].ts == "2024-01-03"   # not 01-04's 95
    assert b.state_view()["fills"][0]["ts"] == "2024-01-03"


def test_a_gtc_stop_is_not_missed_when_the_triggering_day_is_skipped(tmp_path):
    src = Seq(BARS + [Bar("2024-01-05", 100, 100, 100, 100)])
    b = PaperBroker(src, tmp_path / "paper.json", starting_cash=10_000.0)
    b.sync(as_of="2024-01-02")
    b.place(Order(symbol="SPY", side=Side.BUY, quantity=10, order_type=OrderType.MARKET))
    b.sync(as_of="2024-01-03")
    stop = Order(symbol="SPY", side=Side.SELL, quantity=10, order_type=OrderType.STOP, stop_price=98.0,
                 time_in_force=TimeInForce.GTC)
    assert b.place(stop).placed
    fills = b.sync(as_of="2024-01-05")                     # 01-04 (low 90) was skipped; 01-05 never trades <= 98
    assert len(fills) == 1 and fills[0].price == 95.0 and fills[0].ts == "2024-01-04"
    assert b.positions() == [] and b.open_orders() == []


def test_a_day_order_expires_on_its_first_newer_bar_even_if_a_later_one_would_fill(tmp_path):
    b = broker(tmp_path)
    b.sync(as_of="2024-01-02")
    b.place(Order(symbol="SPY", side=Side.BUY, quantity=1, order_type=OrderType.LIMIT, limit_price=95.0))
    assert b.sync(as_of="2024-01-04") == []                # 01-03 misses 95 -> expired; 01-04's low 90 is too late
    assert b.open_orders() == [] and b.positions() == []


def test_sync_fetches_bars_once_per_symbol(tmp_path):
    class Counting(Seq):
        calls = 0
        def bars(self, symbol, n, as_of=None):
            if n > 1:
                Counting.calls += 1
            return super().bars(symbol, n, as_of)
    b = PaperBroker(Counting(BARS), tmp_path / "paper.json", starting_cash=10_000.0)
    b.sync(as_of="2024-01-02")
    for _ in range(3):
        b.place(Order(symbol="SPY", side=Side.BUY, quantity=1, order_type=OrderType.MARKET))
    Counting.calls = 0
    assert len(b.sync(as_of="2024-01-03")) == 3 and Counting.calls == 1


def test_a_fresh_instance_prices_at_the_last_synced_date(tmp_path):
    b = broker(tmp_path)
    b.sync(as_of="2024-01-02")
    b.place(Order(symbol="SPY", side=Side.BUY, quantity=10, order_type=OrderType.MARKET))
    b.sync(as_of="2024-01-03")
    again = PaperBroker(Seq(BARS), tmp_path / "paper.json")
    assert again.positions()[0].last_price == 103.0            # 01-03's close, not the series' last bar (92)
    assert again.balance().net_liq == 10_000.0 - 1020.0 + 10 * 103.0
    older = json.loads((tmp_path / "paper.json").read_text())
    older.pop("as_of")                                        # a state file written before as_of was stored
    (tmp_path / "paper.json").write_text(json.dumps(older))
    assert PaperBroker(Seq(BARS), tmp_path / "paper.json").positions()[0].last_price == 92.0
