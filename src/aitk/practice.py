"""The practice account: pretend money, real rules.

It has its own calendar. The account starts on a day in the past and the person moves time forward
themselves ('next day', 'next week'), so a month of decisions can be lived in ten minutes and an order
placed today fills at TOMORROW's prices, the way it would for real. There is no way to reach real
money from here: the broker underneath is a simulator that only writes one file."""
from __future__ import annotations

import json
from dataclasses import dataclass

from . import paths, prices
from .engine.fills import CostModel
from .engine.models import Fill, Order, OrderType, Side, TimeInForce
from .engine.paper import PaperBroker

CALENDAR_SYMBOL = "SPY"
DEFAULT_CASH = 10_000.0
COST = CostModel(slippage_pct=0.05, commission=0.0)


class PracticeError(ValueError):
    pass


# Starting points worth living through. Each is a date the practice calendar can begin on and one line
# about why. They need real prices covering the date (demo prices cover none of them by design).
SCENARIOS = {
    "2020-crash": ("2020-02-19", "The fastest 30% fall in history, then a recovery nobody believed. "
                                 "Five weeks decide everything."),
    "2022-bear": ("2022-01-03", "A slow grind down all year with sharp rallies that fooled people into buying "
                                "the dip. Patience is tested for months."),
    "2023-rally": ("2023-01-03", "After a bad year, a strong one. The test is whether fear kept you out."),
    "2025-tariffs": ("2025-03-03", "A sudden drop on policy news and a fast bounce. Whipsaw practice."),
}


def _clock_file():
    return paths.paper_file().with_name("clock.json")


@dataclass(frozen=True)
class Status:
    today: str
    cash: float
    buying_power: float
    value: float
    started_with: float
    positions: list[dict]
    open_orders: list[dict]
    prices_kind: dict          # symbol -> "files" | "demo"

    @property
    def change_pct(self) -> float:
        return (self.value / self.started_with - 1) * 100 if self.started_with else 0.0

    def as_dict(self) -> dict:
        return {"today": self.today, "cash": round(self.cash, 2), "buying_power": round(self.buying_power, 2),
                "account_value": round(self.value, 2), "started_with": self.started_with,
                "change_pct": round(self.change_pct, 2), "positions": self.positions,
                "open_orders": self.open_orders, "prices": self.prices_kind,
                "note": "Practice money only. Nothing here touches a real account."}


class Practice:
    def __init__(self, book: prices.PriceBook | None = None):
        self.book = book or prices.PriceBook()

    # ── clock ─────────────────────────────────────────────────────────────────
    def exists(self) -> bool:
        return paths.paper_file().exists() and _clock_file().exists()

    def _clock(self) -> dict:
        if not self.exists():
            raise PracticeError("there is no practice account yet. Start one with: aitk practice start")
        return json.loads(_clock_file().read_text(encoding="utf-8"))

    def _save_clock(self, clock: dict) -> None:
        f = _clock_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(clock, indent=2), encoding="utf-8")

    def _calendar(self) -> list[str]:
        return [b.ts for b in self.book.all_bars(self._clock_symbol())]

    def _clock_symbol(self) -> str:
        if _clock_file().exists():
            return json.loads(_clock_file().read_text(encoding="utf-8")).get("calendar", CALENDAR_SYMBOL)
        return CALENDAR_SYMBOL

    def _broker(self, starting_cash: float = DEFAULT_CASH) -> PaperBroker:
        return PaperBroker(self.book, paths.paper_file(), starting_cash=starting_cash, cost=COST)

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def start(self, cash: float = DEFAULT_CASH, start: str | None = None, calendar: str = CALENDAR_SYMBOL,
              replace: bool = False, scenario: str | None = None) -> Status:
        if self.exists() and not replace:
            raise PracticeError("a practice account already exists. To start over: aitk practice start --reset")
        if cash <= 0:
            raise PracticeError("the starting cash must be more than zero")
        calendar = prices.clean_symbol(calendar)
        if scenario:
            if scenario not in SCENARIOS:
                raise PracticeError(f"no scenario called '{scenario}'. Choose from: {', '.join(SCENARIOS)}")
            if self.book.kind(calendar) == prices.DEMO:
                raise PracticeError(f"scenarios need real prices for {calendar}. Run: aitk prices get {calendar}")
            start = SCENARIOS[scenario][0]
        days = [b.ts for b in self.book.all_bars(calendar)]
        if scenario and start < days[0]:
            raise PracticeError(f"the {calendar} prices on this computer start on {days[0]}, after the "
                                f"'{scenario}' scenario begins. Download a longer history (Tiingo goes back "
                                "decades): aitk prices key tiingo, then aitk prices get " + calendar)
        if len(days) < 300:
            raise PracticeError(f"{calendar} has too little history to practice on")
        if start is None:
            today = days[-252] if len(days) > 252 else days[0]      # about a year of future to live through
        else:
            earlier = [d for d in days if d <= start]
            if not earlier:
                raise PracticeError(f"{start} is before the first price the kit has ({days[0]})")
            today = earlier[-1]
        for f in (paths.paper_file(), _clock_file()):
            if f.exists():
                f.unlink()
        self._save_clock({"today": today, "started_with": float(cash), "calendar": calendar, "started_on": today,
                          "scenario": scenario or ""})
        broker = self._broker(cash)
        broker.sync(as_of=today)
        return self.status()

    def status(self) -> Status:
        clock = self._clock()
        broker = self._broker()
        broker.sync(as_of=clock["today"])
        bal = broker.balance()
        positions = [{"symbol": p.symbol, "shares": p.quantity, "avg_cost": round(p.avg_cost, 2),
                      "price": round(p.last_price or 0.0, 2),
                      "value": round(p.quantity * (p.last_price or 0.0), 2),
                      "gain_pct": round(((p.last_price or 0.0) / p.avg_cost - 1) * 100, 2) if p.avg_cost else 0.0}
                     for p in broker.positions()]
        orders = broker.open_orders()
        symbols = {p["symbol"] for p in positions} | {o["symbol"] for o in orders}
        return Status(clock["today"], bal.cash, bal.buying_power, bal.net_liq, clock["started_with"], positions,
                      orders, {s: self.book.kind(s) for s in sorted(symbols)})

    # ── orders ────────────────────────────────────────────────────────────────
    def order(self, side: str, symbol: str, shares: int, *, limit: float | None = None,
              stop: float | None = None, good_til_cancelled: bool = False) -> dict:
        clock = self._clock()
        symbol = prices.clean_symbol(symbol)
        try:
            the_side = Side(str(side).strip().upper())
        except ValueError as exc:
            raise PracticeError("side must be buy or sell") from exc
        try:
            shares = int(shares)
        except (TypeError, ValueError) as exc:
            raise PracticeError("shares must be a whole number") from exc
        if limit is not None and stop is not None:
            kind = OrderType.STOP_LIMIT
        elif limit is not None:
            kind = OrderType.LIMIT
        elif stop is not None:
            kind = OrderType.STOP
        else:
            kind = OrderType.MARKET
        order = Order(symbol=symbol, side=the_side, quantity=shares, order_type=kind, limit_price=limit,
                      stop_price=stop, time_in_force=TimeInForce.GTC if good_til_cancelled else TimeInForce.DAY)
        broker = self._broker()
        broker.sync(as_of=clock["today"])
        try:
            preview = broker.preview(order)
        except prices.PriceError as exc:
            raise PracticeError(str(exc)) from exc
        if not preview["ok"]:
            raise PracticeError("the order was not accepted: " + str(preview["reason"]).split("; pass")[0])
        result = broker.place(order)
        if not result.placed:
            raise PracticeError(f"the order was not accepted: {result.raw.get('error', 'unknown reason')}")
        return {"accepted": True, "order_id": order.client_order_id, "side": the_side.value, "symbol": symbol,
                "shares": shares, "type": kind.value, "limit": limit, "stop": stop,
                "placed_on": clock["today"], "last_price": round(preview["last_price"], 2),
                "prices": self.book.kind(symbol),
                "note": "It will fill, or not, at the NEXT day's prices. Move time forward to find out."}

    def cancel(self, order_id: str) -> bool:
        self._clock()
        broker = self._broker()
        match = [o["client_order_id"] for o in broker.open_orders()
                 if o["client_order_id"] == order_id or o["client_order_id"].startswith(order_id)]
        if len(match) != 1:
            raise PracticeError("no single open order matches that id. See them with: aitk practice status")
        return bool(broker.cancel(match[0])["cancelled"])

    # ── time ──────────────────────────────────────────────────────────────────
    def advance(self, days: int = 1) -> tuple[Status, list[Fill]]:
        if days < 1:
            raise PracticeError("move forward by at least one day")
        clock = self._clock()
        calendar = self._calendar()
        later = [d for d in calendar if d > clock["today"]]
        if not later:
            raise PracticeError("the practice account has reached the last day of its price history. "
                                "Download newer prices, or start over from an earlier date")
        target = later[min(days, len(later)) - 1]
        broker = self._broker()
        fills = broker.sync(as_of=target)
        clock["today"] = target
        self._save_clock(clock)
        return self.status(), fills

    def history(self) -> list[dict]:
        self._clock()
        return list(self._broker().state_view().get("fills", []))

    # ── the report card ───────────────────────────────────────────────────────
    def report(self) -> dict:
        """How the account did since it started, against simply holding the calendar symbol for the same days."""
        clock = self._clock()
        status = self.status()
        calendar = clock.get("calendar", CALENDAR_SYMBOL)
        bars = self.book.all_bars(calendar)
        by_ts = {b.ts: b.close for b in bars}
        start_close, today_close = by_ts.get(clock["started_on"]), by_ts.get(clock["today"])
        hold_pct = ((today_close / start_close - 1) * 100) if start_close and today_close else 0.0
        fills = self.history()
        days_lived = sum(1 for b in bars if clock["started_on"] < b.ts <= clock["today"])
        realized, lots = 0.0, {}
        for f in fills:
            lot = lots.setdefault(f["symbol"], [0, 0.0])
            if f["side"] == "BUY":
                lot[1] = (lot[0] * lot[1] + f["quantity"] * f["price"]) / (lot[0] + f["quantity"])
                lot[0] += f["quantity"]
            else:
                realized += f["quantity"] * (f["price"] - lot[1])
                lot[0] -= f["quantity"]
        verdict = []
        you = status.change_pct
        if days_lived == 0:
            verdict.append("Time has not moved yet. Place an order, then move a day forward.")
        elif not fills:
            verdict.append(f"You placed no orders that filled, so you sat in cash while holding {calendar} would have "
                           f"made {hold_pct:+.1f}%.")
        elif you > hold_pct:
            verdict.append(f"You made {you:+.1f}% against {hold_pct:+.1f}% for simply holding {calendar}. Ask whether "
                           "it was the rule or the luck; do it again from another date before believing it.")
        else:
            verdict.append(f"You made {you:+.1f}% while simply holding {calendar} made {hold_pct:+.1f}%. Most active "
                           "traders land here. The honest question is what the trades bought you: less worry, or more?")
        if fills:
            verdict.append(f"{len(fills)} fills over {days_lived} trading days, {realized:+,.0f} dollars realized on "
                           f"closed lots, {len(status.positions)} position(s) still open.")
        scenario = clock.get("scenario") or ""
        return {"scenario": scenario, "scenario_note": SCENARIOS.get(scenario, ("", ""))[1],
                "started_on": clock["started_on"], "today": clock["today"], "trading_days": days_lived,
                "started_with": clock["started_with"], "account_value": round(status.value, 2),
                "you_pct": round(you, 2), "hold_pct": round(hold_pct, 2), "hold_symbol": calendar,
                "fills": len(fills), "realized": round(realized, 2), "open_positions": len(status.positions),
                "verdict": verdict, "note": "Practice money only."}
