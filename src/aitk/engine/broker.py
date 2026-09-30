"""The two seams every adapter implements. `Broker` is execution + account; `BarSource` is data.
One class may implement both (the Webull adapter does). PaperBroker implements Broker and takes a
BarSource to fill against."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import Balance, Bar, Order, PlaceResult, Position


class BrokerError(RuntimeError):
    """A broker call failed (network, rejection, entitlement). The runner logs it and moves on."""


# Keys every adapter's open_orders() rows carry. Values: client_order_id str; symbol str; side "BUY"/"SELL";
# order_type "MARKET"/"LIMIT"/"STOP"/"STOP_LIMIT"; quantity int; limit_price/stop_price float|None; status str.
OPEN_ORDER_KEYS = ("client_order_id", "symbol", "side", "order_type", "quantity", "limit_price",
                   "stop_price", "status")


@runtime_checkable
class Broker(Protocol):
    name: str

    def armed(self) -> bool: ...
    def account_id(self) -> str: ...
    def preview(self, order: Order) -> dict: ...
    def place(self, order: Order) -> PlaceResult: ...
    def cancel(self, client_order_id: str) -> dict:
        """Returns the broker's response dict; a `cancelled: False` key or a raised `BrokerError`
        means the broker refused, and the runner then does not sell."""
        ...
    def open_orders(self) -> list[dict]: ...
    def positions(self) -> list[Position]: ...
    def balance(self) -> Balance: ...


@runtime_checkable
class BarSource(Protocol):
    def bars(self, symbol: str, n: int, as_of: str | None = None) -> list[Bar]:
        """The newest `n` bars, ascending by ts (oldest first). With `as_of`, only bars with ts <= as_of."""
        ...

    def last_price(self, symbol: str, as_of: str | None = None) -> float: ...
