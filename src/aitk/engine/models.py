"""Broker-neutral data model. Nothing here knows any broker's wire format."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"            # stop-market
    STOP_LIMIT = "STOP_LIMIT"


class TimeInForce(str, Enum):
    DAY = "DAY"
    GTC = "GTC"


def new_client_order_id() -> str:
    return uuid.uuid4().hex


@dataclass(frozen=True)
class Order:
    """One equity order in neutral terms. `quantity` is whole shares. Prices are floats; adapters
    format them for the wire. `side`/`order_type`/`time_in_force` are checked by safety.validate_order,
    not here, so a malformed order can be constructed and then rejected with a clear message."""
    symbol: str
    side: Side
    quantity: int
    order_type: OrderType = OrderType.LIMIT
    limit_price: float | None = None
    stop_price: float | None = None
    time_in_force: TimeInForce = TimeInForce.DAY
    client_order_id: str = field(default_factory=new_client_order_id)

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", str(self.symbol).strip().upper())


@dataclass(frozen=True)
class Bar:
    ts: str            # ISO-8601 date or datetime; sorted lexicographically, so keep one format per source
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass(frozen=True)
class Position:
    symbol: str
    quantity: int
    avg_cost: float
    last_price: float | None = None


@dataclass(frozen=True)
class Balance:
    cash: float
    buying_power: float
    net_liq: float


@dataclass(frozen=True)
class Fill:
    client_order_id: str
    symbol: str
    side: Side
    quantity: int
    price: float
    ts: str


@dataclass(frozen=True)
class Signal:
    """What a strategy says about the newest bar. `action` is BUY/SELL only on the bar that triggers;
    `stop_price` is the protective level the runner should keep under a held position (None = none)."""
    action: Side | None
    stop_price: float | None
    note: str = ""


@dataclass(frozen=True)
class PlaceResult:
    """The ONLY thing the runner branches on after a place: `placed`. A broker that returned a raw body
    instead once made a runner abandon accepted orders; every adapter must build one of these."""
    placed: bool
    order_id: str | None = None
    raw: dict = field(default_factory=dict)
