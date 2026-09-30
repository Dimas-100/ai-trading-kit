"""Bar-by-bar replay of a Strategy through the same fill model and the same order of operations the
runner uses (signal on bar t -> MARKET at t+1 open; stop from the entry bar's signal, checked from t+2).
One position at a time; long only."""
from __future__ import annotations

from dataclasses import dataclass, field

from .fills import CostModel, fill_price
from .models import Bar, Order, OrderType, Side
from .strategy import Strategy


@dataclass(frozen=True)
class Trade:
    entry_ts: str
    exit_ts: str
    entry_price: float
    exit_price: float
    quantity: int
    pnl: float
    return_pct: float
    reason: str          # "signal" | "stop" | "end"


@dataclass(frozen=True)
class Result:
    trades: list[Trade]
    equity_curve: list[tuple[str, float]]
    starting_equity: float
    final_equity: float
    metrics: dict = field(default_factory=dict)


def _mkt(side: Side) -> Order:
    return Order(symbol="BT", side=side, quantity=1, order_type=OrderType.MARKET)


def run(strategy: Strategy, bars: list[Bar], *, starting_equity: float = 100_000.0,
        dollars_per_trade: float | None = None, cost: CostModel = CostModel(), lookback: int = 250) -> Result:
    cash = float(starting_equity)
    qty = 0
    entry_price = 0.0
    entry_ts = ""
    stop: float | None = None
    stop_set_at = -1
    pending_entry = pending_exit = False
    trades: list[Trade] = []
    curve: list[tuple[str, float]] = []
    bars_in_market = 0

    def close_position(i: int, price: float, reason: str) -> None:
        nonlocal cash, qty, stop, stop_set_at
        pnl = qty * (price - entry_price) - 2 * cost.commission
        cash += qty * price - cost.commission
        trades.append(Trade(entry_ts, bars[i].ts, entry_price, price, qty, pnl,
                            (price / entry_price - 1) * 100.0, reason))
        qty, stop, stop_set_at = 0, None, -1

    for i, bar in enumerate(bars):
        if qty and pending_exit:
            close_position(i, fill_price(_mkt(Side.SELL), bar, cost), "signal")
        elif qty and stop is not None and i > stop_set_at:
            hit = fill_price(Order(symbol="BT", side=Side.SELL, quantity=qty, order_type=OrderType.STOP,
                                   stop_price=stop), bar, cost)
            if hit is not None:
                close_position(i, hit, "stop")
        if not qty and pending_entry:
            price = fill_price(_mkt(Side.BUY), bar, cost)
            budget = min(cash, dollars_per_trade) if dollars_per_trade else cash
            n = int(budget // price) if price > 0 else 0
            if n >= 1:
                qty, entry_price, entry_ts = n, price, bar.ts
                cash -= n * price + cost.commission
        pending_entry = pending_exit = False

        window = bars[max(0, i + 1 - lookback):i + 1]
        sig = strategy.on_bars(window)
        if qty and stop is None and sig.stop_price is not None:
            stop, stop_set_at = float(sig.stop_price), i
        if qty and sig.action == Side.SELL:
            pending_exit = True
        elif not qty and sig.action == Side.BUY:
            pending_entry = True

        if qty:
            bars_in_market += 1
        curve.append((bar.ts, cash + qty * bar.close))

    if qty:
        last = len(bars) - 1
        close_position(last, bars[last].close, "end")
        curve[-1] = (bars[last].ts, cash)

    final = curve[-1][1] if curve else cash
    metrics = _metrics(trades, curve, bars, starting_equity, bars_in_market)
    return Result(trades, curve, float(starting_equity), final, metrics)


def _metrics(trades, curve, bars, start, bars_in_market) -> dict:
    final = curve[-1][1] if curve else start
    wins = [t for t in trades if t.pnl > 0]
    peak, mdd = float("-inf"), 0.0
    for _, eq in curve:
        peak = max(peak, eq)
        if peak > 0:
            mdd = min(mdd, (eq - peak) / peak * 100.0)
    years = max(len(bars), 1) / 252.0
    cagr = ((final / start) ** (1 / years) - 1) * 100.0 if start > 0 and final > 0 and years > 0 else 0.0
    bh = (bars[-1].close / bars[0].close - 1) * 100.0 if bars and bars[0].close else 0.0
    return {
        "trades": len(trades),
        "win_rate_pct": round(len(wins) / len(trades) * 100.0, 2) if trades else 0.0,
        "avg_return_pct": round(sum(t.return_pct for t in trades) / len(trades), 4) if trades else 0.0,
        "total_return_pct": round((final / start - 1) * 100.0, 4) if start else 0.0,
        "cagr_pct": round(cagr, 4),
        "max_drawdown_pct": round(mdd, 4),
        "exposure_pct": round(bars_in_market / len(bars) * 100.0, 2) if bars else 0.0,
        "buy_hold_return_pct": round(bh, 4),
        "bars": len(bars),
    }


def format_metrics(result: Result) -> str:
    width = max(len(k) for k in result.metrics)
    return "\n".join(f"{k:<{width}}  {v}" for k, v in result.metrics.items())
