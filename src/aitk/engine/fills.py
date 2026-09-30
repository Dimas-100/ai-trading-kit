"""The one fill model, shared by PaperBroker and the backtest so the two never disagree.

Given an order and the FIRST bar after it was placed, answer the fill price or None (did not fill).
MARKET fills at the open. LIMIT fills at the better of limit and open once the bar touches the limit.
STOP triggers when the bar touches the stop and fills at the worse of stop and open (gap-through).
STOP_LIMIT triggers like STOP, then fills at the stop-fill price if that respects the limit, else at
the limit if the bar later reaches it, else not at all. Slippage is applied against the trader."""
from __future__ import annotations

from dataclasses import dataclass

from .models import Bar, Order, OrderType, Side


@dataclass(frozen=True)
class CostModel:
    slippage_pct: float = 0.0   # percent per fill, against the trader
    commission: float = 0.0     # flat per filled order


def _slip(price: float, side: Side, cost: CostModel) -> float:
    factor = 1 + cost.slippage_pct / 100.0 if side is Side.BUY else 1 - cost.slippage_pct / 100.0
    return price * factor


def fill_price(order: Order, bar: Bar, cost: CostModel = CostModel()) -> float | None:
    side = Side(order.side)
    otype = OrderType(order.order_type)
    lp, sp = order.limit_price, order.stop_price
    base: float | None = None

    if otype is OrderType.MARKET:
        base = bar.open
    elif otype is OrderType.LIMIT:
        if side is Side.BUY and bar.low <= lp:
            base = min(lp, bar.open)
        elif side is Side.SELL and bar.high >= lp:
            base = max(lp, bar.open)
    elif otype is OrderType.STOP:
        if side is Side.SELL and bar.low <= sp:
            base = min(sp, bar.open)
        elif side is Side.BUY and bar.high >= sp:
            base = max(sp, bar.open)
    elif otype is OrderType.STOP_LIMIT:
        if side is Side.SELL and bar.low <= sp:
            trig = min(sp, bar.open)
            if trig >= lp:
                base = trig
            elif bar.high >= lp:
                base = lp
        elif side is Side.BUY and bar.high >= sp:
            trig = max(sp, bar.open)
            if trig <= lp:
                base = trig
            elif bar.low <= lp:
                base = lp
    return None if base is None else _slip(base, side, cost)


def describe(order: Order) -> str:
    """Human line for previews and the typed-CONFIRM prompt, e.g. 'BUY 3 SPY MARKET DAY'."""
    parts = [str(Side(order.side).value), str(order.quantity), order.symbol, str(OrderType(order.order_type).value)]
    if order.limit_price is not None:
        parts.append(f"limit {order.limit_price:.2f}")
    if order.stop_price is not None:
        parts.append(f"stop {order.stop_price:.2f}")
    parts.append(str(order.time_in_force.value if hasattr(order.time_in_force, "value") else order.time_in_force))
    return " ".join(parts)
