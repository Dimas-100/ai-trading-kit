from aitk.engine.models import Balance, Bar, Order, OrderType, PlaceResult, Position, Side, Signal, TimeInForce


def test_order_normalises_symbol_and_defaults():
    o = Order(symbol=" aapl ", side=Side.BUY, quantity=2, limit_price=100.0)
    assert o.symbol == "AAPL"
    assert o.order_type is OrderType.LIMIT
    assert o.time_in_force is TimeInForce.DAY
    assert o.stop_price is None
    assert len(o.client_order_id) == 32


def test_order_is_frozen_and_ids_are_unique():
    a = Order(symbol="A", side=Side.SELL, quantity=1, order_type=OrderType.MARKET)
    b = Order(symbol="A", side=Side.SELL, quantity=1, order_type=OrderType.MARKET)
    assert a.client_order_id != b.client_order_id
    try:
        a.quantity = 5  # type: ignore[misc]
    except Exception as exc:
        assert "frozen" in type(exc).__name__.lower() or "FrozenInstanceError" in repr(exc)
    else:
        raise AssertionError("Order must be frozen")


def test_enums_compare_to_their_strings():
    assert Side.BUY == "BUY" and OrderType.STOP == "STOP" and TimeInForce.GTC == "GTC"
    assert "BUY" in {Side.BUY, Side.SELL}


def test_other_models_construct():
    bar = Bar(ts="2024-01-02", open=1.0, high=2.0, low=0.5, close=1.5)
    assert bar.volume == 0.0
    assert Position("SPY", 3, 400.0).last_price is None
    assert Balance(cash=1.0, buying_power=1.0, net_liq=1.0).net_liq == 1.0
    assert Signal(None, None).note == ""
    pr = PlaceResult(placed=False)
    assert pr.order_id is None and pr.raw == {}
