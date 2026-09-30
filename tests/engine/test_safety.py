import pytest

from aitk.engine.models import Order, OrderType, Side, TimeInForce
from aitk.engine.safety import OrderValidationError, should_submit, validate_order


def limit(**kw):
    base = dict(symbol="AAPL", side=Side.BUY, quantity=1, order_type=OrderType.LIMIT, limit_price=100.0)
    base.update(kw)
    return Order(**base)


def test_accepts_good_limit_order():
    o = limit()
    assert validate_order(o, last_price=101.0) is o


@pytest.mark.parametrize("kw", [
    dict(side="HODL"),
    dict(order_type="FUNKY"),
    dict(time_in_force="WHENEVER"),
    dict(symbol="  "),
    dict(quantity=0),
    dict(quantity=-3),
    dict(limit_price=None),                       # LIMIT needs a limit
    dict(limit_price=0.0),
    dict(stop_price=90.0),                        # LIMIT must not carry a stop
    dict(order_type=OrderType.MARKET),            # MARKET must not carry a limit
    dict(order_type=OrderType.STOP),              # STOP must not carry a limit / needs a stop
    dict(order_type=OrderType.STOP_LIMIT),        # STOP_LIMIT needs both
])
def test_rejects_malformed(kw):
    with pytest.raises(OrderValidationError):
        validate_order(limit(**kw))


def test_market_order_ok_without_prices():
    o = Order(symbol="SPY", side=Side.SELL, quantity=2, order_type=OrderType.MARKET)
    assert validate_order(o) is o


def test_fat_finger_guard_and_override():
    o = limit(limit_price=1000.0)
    with pytest.raises(OrderValidationError):
        validate_order(o, last_price=100.0)
    assert validate_order(o, last_price=100.0, max_price_deviation=20.0) is o


def test_stop_side_guard():
    buy_stop = Order(symbol="SPY", side=Side.BUY, quantity=1, order_type=OrderType.STOP, stop_price=90.0)
    with pytest.raises(OrderValidationError):
        validate_order(buy_stop, last_price=100.0)       # BUY stop below market fills at once
    sell_stop = Order(symbol="SPY", side=Side.SELL, quantity=1, order_type=OrderType.STOP, stop_price=110.0)
    with pytest.raises(OrderValidationError):
        validate_order(sell_stop, last_price=100.0)      # SELL stop above market fills at once
    good = Order(symbol="SPY", side=Side.SELL, quantity=1, order_type=OrderType.STOP, stop_price=95.0,
                 time_in_force=TimeInForce.GTC)
    assert validate_order(good, last_price=100.0) is good


def test_stop_limit_requires_both_and_checks_both():
    o = Order(symbol="SPY", side=Side.SELL, quantity=1, order_type=OrderType.STOP_LIMIT,
              stop_price=95.0, limit_price=94.0)
    assert validate_order(o, last_price=100.0) is o
    wild = Order(symbol="SPY", side=Side.SELL, quantity=1, order_type=OrderType.STOP_LIMIT,
                 stop_price=95.0, limit_price=10.0)
    with pytest.raises(OrderValidationError):
        validate_order(wild, last_price=100.0)


def test_notional_cap_uses_limit_then_stop_then_last():
    o = limit(quantity=10, limit_price=100.0)            # $1,000
    with pytest.raises(OrderValidationError):
        validate_order(o, max_notional=999.0)
    assert validate_order(o, max_notional=1000.0) is o
    stop = Order(symbol="SPY", side=Side.SELL, quantity=10, order_type=OrderType.STOP, stop_price=50.0)
    with pytest.raises(OrderValidationError):
        validate_order(stop, last_price=60.0, max_notional=499.0)
    mkt = Order(symbol="SPY", side=Side.BUY, quantity=10, order_type=OrderType.MARKET)
    with pytest.raises(OrderValidationError):
        validate_order(mkt, last_price=60.0, max_notional=599.0)
    assert validate_order(mkt, max_notional=1.0) is mkt   # no reference price => cannot check


def test_should_submit_is_true_only_for_literal_true():
    assert should_submit(True) is True
    assert should_submit(False) is False
    assert should_submit("yes") is False
    assert should_submit(1) is False
    assert should_submit(None) is False
