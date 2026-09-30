"""PaperBroker: an in-memory, JSON-persisted simulator that implements the Broker protocol.
It cannot reach money, so it is always armed. Fills come from fills.fill_price against each bar of its
BarSource after the order was placed, walked in order, so a paper run and a backtest agree on every fill."""
from __future__ import annotations

import json
from pathlib import Path

from .broker import OPEN_ORDER_KEYS, BarSource
from .fills import CostModel, fill_price
from .models import Balance, Bar, Fill, Order, OrderType, PlaceResult, Position, Side, TimeInForce
from .safety import OrderValidationError, validate_order

SYNC_BARS = 500   # bars fetched per symbol per sync: the window an open order is walked through


class PaperBroker:
    name = "paper"

    def __init__(self, source: BarSource, state_path: str | Path, starting_cash: float = 100_000.0,
                 cost: CostModel = CostModel()):
        self._source = source
        self._path = Path(state_path)
        self._cost = cost
        if self._path.exists():
            self._state = json.loads(self._path.read_text())
            self._state.setdefault("rejected", [])
        else:
            self._state = {
                "cash": float(starting_cash),
                "positions": {},
                "open_orders": {},
                "fills": [],
                "rejected": [],
            }
            self._save()
        # The replay date of the last sync (None = latest), so a fresh instance (`aitk paper status`) prices
        # at the day the account was replayed to, not at the source's last bar. Absent in older state files.
        self._as_of: str | None = self._state.get("as_of")

    # ── persistence ────────────────────────────────────────────────────────────
    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._state, indent=2))

    def state_view(self) -> dict:
        return json.loads(json.dumps(self._state))

    # ── Broker protocol ────────────────────────────────────────────────────────
    def armed(self) -> bool:
        return True

    def account_id(self) -> str:
        return "paper"

    def _last(self, symbol: str) -> float:
        return float(self._source.last_price(symbol, self._as_of))

    def _held(self, symbol: str) -> int:
        return int(self._state["positions"].get(symbol, {}).get("quantity", 0))

    def _committed_sell(self, symbol: str) -> int:
        return sum(int(o["quantity"]) for o in self._state["open_orders"].values()
                   if o["symbol"] == symbol and o["side"] == "SELL")

    def reserved_cash(self) -> float:
        return sum(float(o["reserved"]) for o in self._state["open_orders"].values() if o["side"] == "BUY")

    def _check(self, order: Order) -> tuple[bool, str, float]:
        try:
            last = self._last(order.symbol)
        except Exception as exc:
            return False, f"no price for {order.symbol}: {exc}", 0.0
        try:
            validate_order(order, last_price=last)
        except OrderValidationError as exc:
            return False, str(exc), 0.0
        if Side(order.side) is Side.BUY:
            ref = order.limit_price if order.limit_price is not None else last
            need = order.quantity * ref
            free = self._state["cash"] - self.reserved_cash()
            if need > free + 1e-9:
                return False, f"insufficient cash: need {need:.2f}, free {free:.2f}", need
            return True, "", need
        free_shares = self._held(order.symbol) - self._committed_sell(order.symbol)
        if order.quantity > free_shares:
            return False, f"insufficient shares: selling {order.quantity}, free {free_shares}", 0.0
        return True, "", 0.0

    def preview(self, order: Order) -> dict:
        ok, reason, reserved = self._check(order)
        try:
            last_price = self._last(order.symbol)
        except Exception:
            last_price = None
        return {"ok": ok, "reason": reason, "reserved_cash": reserved, "last_price": last_price,
                "cash_free": self._state["cash"] - self.reserved_cash()}

    def place(self, order: Order) -> PlaceResult:
        ok, reason, reserved = self._check(order)
        if not ok:
            return PlaceResult(placed=False, raw={"error": reason})
        newest = self._source.bars(order.symbol, 1, self._as_of)
        row = {"client_order_id": order.client_order_id, "symbol": order.symbol, "quantity": int(order.quantity),
               "limit_price": order.limit_price, "stop_price": order.stop_price,
               "side": Side(order.side).value, "order_type": OrderType(order.order_type).value,
               "time_in_force": TimeInForce(order.time_in_force).value, "status": "open",
               "reserved": reserved, "after_ts": newest[-1].ts if newest else ""}
        self._state["open_orders"][order.client_order_id] = row
        self._save()
        return PlaceResult(placed=True, order_id=f"P-{order.client_order_id[:8]}", raw=dict(row))

    def cancel(self, client_order_id: str) -> dict:
        row = self._state["open_orders"].pop(client_order_id, None)
        self._save()
        return {"cancelled": row is not None, "client_order_id": client_order_id}

    def open_orders(self) -> list[dict]:
        return [{k: o.get(k) for k in OPEN_ORDER_KEYS} for o in self._state["open_orders"].values()]

    def positions(self) -> list[Position]:
        out = []
        for sym, p in self._state["positions"].items():
            if int(p["quantity"]) > 0:
                out.append(Position(symbol=sym, quantity=int(p["quantity"]), avg_cost=float(p["avg_cost"]),
                                    last_price=self._last(sym)))
        return out

    def balance(self) -> Balance:
        cash = float(self._state["cash"])
        value = sum(p.quantity * (p.last_price or 0.0) for p in self.positions())
        return Balance(cash=cash, buying_power=cash - self.reserved_cash(), net_liq=cash + value)

    # ── simulation ─────────────────────────────────────────────────────────────
    def sync(self, as_of: str | None = None) -> list[Fill]:
        """Fill/expire open orders by walking, in order, every bar newer than each order's after_ts (up to
        as_of): the first bar that fills the order fills it there; a DAY order that meets its first newer bar
        without filling expires on it; a GTC order keeps walking. Skipping days therefore never misses a stop.
        Bars are fetched once per symbol per sync."""
        self._as_of = as_of
        self._state["as_of"] = as_of
        fills: list[Fill] = []
        window: dict[str, list[Bar]] = {}
        for cid, o in list(self._state["open_orders"].items()):
            if o["symbol"] not in window:
                window[o["symbol"]] = self._source.bars(o["symbol"], SYNC_BARS, as_of)
            newer = [b for b in window[o["symbol"]] if b.ts > o["after_ts"]]
            if not newer:
                continue
            order = Order(symbol=o["symbol"], side=Side(o["side"]), quantity=int(o["quantity"]),
                          order_type=OrderType(o["order_type"]), limit_price=o["limit_price"],
                          stop_price=o["stop_price"], time_in_force=TimeInForce(o["time_in_force"]),
                          client_order_id=cid)
            bar, price = None, None
            for candidate in newer:
                price = fill_price(order, candidate, self._cost)
                if price is not None:
                    bar = candidate
                    break
                if o["time_in_force"] == "DAY":
                    break
            if bar is None:
                if o["time_in_force"] == "DAY":
                    del self._state["open_orders"][cid]
                continue
            price = round(price, 4)
            # Check cash for BUY fills before applying
            if Side(order.side) is Side.BUY:
                debit = order.quantity * price + self._cost.commission
                if debit > self._state["cash"] + 1e-9:
                    del self._state["open_orders"][cid]
                    cash = self._state["cash"]
                    reason = f"insufficient cash at fill: need {debit:.2f}, have {cash:.2f}"
                    self._state["rejected"].append(
                        {"client_order_id": cid, "symbol": order.symbol, "ts": bar.ts, "reason": reason}
                    )
                    continue
            self._apply(order, price)
            del self._state["open_orders"][cid]
            fill = Fill(cid, order.symbol, Side(order.side), order.quantity, price, bar.ts)
            self._state["fills"].append({"client_order_id": cid, "symbol": fill.symbol, "side": fill.side.value,
                                         "quantity": fill.quantity, "price": fill.price, "ts": fill.ts})
            fills.append(fill)
        self._save()
        return fills

    def _apply(self, order: Order, price: float) -> None:
        pos = self._state["positions"].setdefault(order.symbol, {"quantity": 0, "avg_cost": 0.0})
        if Side(order.side) is Side.BUY:
            total = pos["quantity"] * pos["avg_cost"] + order.quantity * price
            pos["quantity"] += order.quantity
            pos["avg_cost"] = total / pos["quantity"]
            self._state["cash"] -= order.quantity * price + self._cost.commission
        else:
            pos["quantity"] -= order.quantity
            self._state["cash"] += order.quantity * price - self._cost.commission
            if pos["quantity"] <= 0:
                del self._state["positions"][order.symbol]
