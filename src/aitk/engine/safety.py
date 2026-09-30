"""Order safety rails. Pure: no network, no broker, fully unit-tested.

`validate_order` rejects malformed or dangerous orders. `should_submit` is THE submit gate: it answers
True only for the literal `True`. Every other wall in this repo (broker arming, the CLI's typed CONFIRM)
sits in FRONT of this gate and may only add strictness — never remove the confirm requirement.
"""
from __future__ import annotations

from .models import Order, OrderType, Side, TimeInForce


class OrderValidationError(ValueError):
    """The order is malformed or would be dangerous to send."""


def _enum(value, enum_cls, name: str):
    try:
        return enum_cls(value)
    except ValueError as exc:
        raise OrderValidationError(
            f"{name} must be one of {[e.value for e in enum_cls]}, got {value!r}") from exc


def _positive(value, name: str) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError) as exc:
        raise OrderValidationError(f"{name} must be numeric, got {value!r}") from exc
    if f <= 0:
        raise OrderValidationError(f"{name} must be > 0, got {f}")
    return f


def validate_order(order: Order, *, last_price: float | None = None,
                   max_price_deviation: float = 0.20, max_notional: float | None = None) -> Order:
    """Raise OrderValidationError if the order is malformed or unsafe; return it unchanged otherwise.

    last_price enables the fat-finger guard (limit/stop farther than max_price_deviation from the
    market), the wrong-side stop guard, and the notional cap for MARKET orders. max_notional caps
    quantity x reference where reference = limit_price, else stop_price, else last_price; with no
    reference the cap cannot be checked (the runner always passes last_price).
    """
    side = _enum(order.side, Side, "side")
    otype = _enum(order.order_type, OrderType, "order_type")
    _enum(order.time_in_force, TimeInForce, "time_in_force")
    if not str(order.symbol or "").strip():
        raise OrderValidationError("symbol must be non-empty")
    try:
        qty = int(order.quantity)
    except (TypeError, ValueError) as exc:
        raise OrderValidationError(f"quantity must be an integer, got {order.quantity!r}") from exc
    if qty <= 0 or qty != order.quantity:
        raise OrderValidationError(f"quantity must be a whole number > 0, got {order.quantity!r}")

    lp, sp = order.limit_price, order.stop_price
    have_last = last_price is not None and last_price > 0

    def deviation_guard(price: float, name: str) -> None:
        if have_last:
            dev = abs(price - last_price) / last_price
            if dev > max_price_deviation:
                raise OrderValidationError(
                    f"{name} {price} is {dev:.0%} away from last {last_price} "
                    f"(> {max_price_deviation:.0%} guard); pass max_price_deviation to override")

    def side_guard(stop: float) -> None:
        # A stop on the wrong side of the market triggers immediately as a market order.
        if have_last:
            if side is Side.BUY and stop < last_price:
                raise OrderValidationError(
                    f"a BUY stop must trigger at/above the last price ({stop} < {last_price})")
            if side is Side.SELL and stop > last_price:
                raise OrderValidationError(
                    f"a SELL stop must trigger at/below the last price ({stop} > {last_price})")

    reference: float | None = None
    if otype is OrderType.LIMIT:
        if lp is None:
            raise OrderValidationError("limit_price is required for LIMIT orders")
        if sp is not None:
            raise OrderValidationError("LIMIT order must not carry a stop_price")
        reference = _positive(lp, "limit_price")
        deviation_guard(reference, "limit_price")
    elif otype is OrderType.MARKET:
        if lp is not None or sp is not None:
            raise OrderValidationError("MARKET order must not carry a limit_price or stop_price")
        reference = last_price if have_last else None
    elif otype is OrderType.STOP:
        if sp is None:
            raise OrderValidationError("stop_price is required for STOP orders")
        if lp is not None:
            raise OrderValidationError("STOP must not carry a limit_price (use STOP_LIMIT)")
        reference = _positive(sp, "stop_price")
        deviation_guard(reference, "stop_price")
        side_guard(reference)
    elif otype is OrderType.STOP_LIMIT:
        if sp is None or lp is None:
            raise OrderValidationError("STOP_LIMIT requires both stop_price and limit_price")
        spf = _positive(sp, "stop_price")
        lpf = _positive(lp, "limit_price")
        deviation_guard(spf, "stop_price")
        deviation_guard(lpf, "limit_price")
        side_guard(spf)
        reference = lpf

    if max_notional is not None and reference is not None:
        notional = qty * reference
        if notional > max_notional:
            raise OrderValidationError(
                f"order notional ${notional:,.2f} exceeds the per-order cap ${max_notional:,.2f}")
    return order


def should_submit(confirm) -> bool:
    """The submit gate. True ONLY for the literal `True`.

    Single-factor by design. The dry-run default (confirm=False) is what prevents an accidental live
    order; a truthy string or 1 does not count, so a config value can never arm a submit by mistake.
    If a second factor is ever wanted it must only ADD strictness in front of this function — never
    remove the confirm requirement.
    """
    return confirm is True
