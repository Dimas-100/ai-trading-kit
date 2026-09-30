from aitk.engine.broker import OPEN_ORDER_KEYS, BarSource, Broker, BrokerError
from aitk.engine.models import Balance, PlaceResult


class Fake:
    name = "fake"
    def armed(self): return True
    def account_id(self): return "acct"
    def preview(self, order): return {}
    def place(self, order): return PlaceResult(placed=True, order_id="1")
    def cancel(self, client_order_id): return {}
    def open_orders(self): return []
    def positions(self): return []
    def balance(self): return Balance(0.0, 0.0, 0.0)


class FakeBars:
    def bars(self, symbol, n, as_of=None): return []
    def last_price(self, symbol, as_of=None): return 1.0


def test_protocols_are_runtime_checkable():
    assert isinstance(Fake(), Broker)
    assert isinstance(FakeBars(), BarSource)
    assert not isinstance(FakeBars(), Broker)
    assert issubclass(BrokerError, RuntimeError)
    assert {"client_order_id", "symbol", "side", "order_type", "quantity"} <= set(OPEN_ORDER_KEYS)
