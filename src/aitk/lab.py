"""The lab: run an idea over history and say honestly how it did.

Three things live here, all on top of the engine's one backtest:
- `evaluate`: one strategy, one symbol, with the numbers that matter and a plain-words verdict.
- `compare`: several strategies side by side against buy and hold.
- `sweep`: try many settings on the FIRST part of history, then check the winner on the LAST part it
  never saw. A setting that only wins on the part it was picked from is a coincidence, not an edge.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import asdict, dataclass, field

from .engine import backtest
from .engine.fills import CostModel
from .engine.models import Bar
from .engine.strategy import get_strategy

MIN_TRADES = 30          # fewer closed trades than this and the averages are mostly luck
DEFAULT_COST = CostModel(slippage_pct=0.05, commission=0.0)


class LabError(ValueError):
    pass


@dataclass(frozen=True)
class Report:
    strategy: str
    params: dict
    symbol: str
    first: str
    last: str
    metrics: dict
    verdict: list[str] = field(default_factory=list)
    trades: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def _extra_metrics(result: backtest.Result) -> dict:
    trades = result.trades
    gains = sum(t.pnl for t in trades if t.pnl > 0)
    losses = -sum(t.pnl for t in trades if t.pnl < 0)
    rets = []
    curve = result.equity_curve
    for (_, a), (_, b) in zip(curve, curve[1:]):
        if a > 0:
            rets.append(b / a - 1)
    sharpe = 0.0
    if len(rets) > 1:
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        if var > 0:
            sharpe = mean / math.sqrt(var) * math.sqrt(252)
    return {
        "profit_factor": round(gains / losses, 2) if losses > 0 else (None if not gains else float("inf")),
        "best_trade_pct": round(max((t.return_pct for t in trades), default=0.0), 2),
        "worst_trade_pct": round(min((t.return_pct for t in trades), default=0.0), 2),
        "sharpe": round(sharpe, 2),
        "stopped_out": sum(1 for t in trades if t.reason == "stop"),
    }


def verdict(metrics: dict) -> list[str]:
    """Plain-words reading of the numbers. Deliberately cautious: it names what the test cannot show."""
    out = []
    n = metrics["trades"]
    total, bh = metrics["total_return_pct"], metrics["buy_hold_return_pct"]
    if n == 0:
        return ["No trades at all: the rule never triggered on this history. Try a longer history or "
                "looser settings."]
    if n < MIN_TRADES:
        out.append(f"Only {n} trades. Fewer than {MIN_TRADES} is too few to trust an average; treat every "
                   "number here as a rough sketch.")
    if total > bh:
        out.append(f"It made {total:.1f}% against {bh:.1f}% for simply buying and holding.")
    else:
        out.append(f"It made {total:.1f}%, which is less than the {bh:.1f}% from simply buying and holding.")
    mdd = abs(metrics["max_drawdown_pct"])
    out.append(f"At its worst it was down {mdd:.1f}% from a peak. Ask whether you would have kept going.")
    if metrics["exposure_pct"] < 100:
        out.append(f"Money was in the market {metrics['exposure_pct']:.0f}% of the time; the rest sat in cash.")
    out.append("A backtest shows what would have happened, not what will. It ignores taxes and assumes "
               "every order fills.")
    return out


def make_strategy(name: str, params: dict | None = None):
    """A strategy by name, including the person's own files; errors are worded for a person."""
    from .strategies import load_errors, load_user_strategies, names
    load_user_strategies()
    try:
        return get_strategy(name, **(params or {}))
    except KeyError as exc:
        hint = f" ({name}.py could not be loaded: {load_errors[name + '.py']})" if name + ".py" in load_errors else ""
        raise LabError(f"no strategy called '{name}'{hint}. Available: {', '.join(names())}") from exc
    except TypeError as exc:
        raise LabError(f"{name} does not accept those settings: {exc}") from exc
    except ValueError as exc:
        raise LabError(f"{name}: {exc}") from exc


def _check(bars: list[Bar], strategy) -> None:
    need = strategy.warmup()
    if len(bars) <= need:
        raise LabError(f"{len(bars)} days of history is not enough: this strategy needs more than {need} "
                       "before it can make its first decision")


def evaluate(name: str, bars: list[Bar], *, symbol: str = "", params: dict | None = None,
             starting_cash: float = 10_000.0, cost: CostModel = DEFAULT_COST, keep_trades: bool = True) -> Report:
    params = dict(params or {})
    strategy = make_strategy(name, params)
    _check(bars, strategy)
    lookback = max(250, strategy.warmup() + 5)
    result = backtest.run(strategy, bars, starting_equity=starting_cash, cost=cost, lookback=lookback)
    metrics = {**result.metrics, **_extra_metrics(result), "starting_cash": starting_cash,
               "final_value": round(result.final_equity, 2)}
    trades = [asdict(t) for t in result.trades] if keep_trades else []
    return Report(name, params, symbol.upper(), bars[0].ts, bars[-1].ts, metrics, verdict(metrics), trades)


def compare(names: list[str], bars: list[Bar], *, symbol: str = "", starting_cash: float = 10_000.0,
            cost: CostModel = DEFAULT_COST) -> list[Report]:
    out = []
    for name in names:
        try:
            out.append(evaluate(name, bars, symbol=symbol, starting_cash=starting_cash, cost=cost,
                                keep_trades=False))
        except LabError:
            continue
    return sorted(out, key=lambda r: r.metrics["total_return_pct"], reverse=True)


@dataclass(frozen=True)
class SweepResult:
    strategy: str
    symbol: str
    split_at: str
    tried: int
    rows: list[dict]           # every setting: params + first-part and last-part numbers
    best: dict | None
    verdict: list[str]

    def as_dict(self) -> dict:
        return asdict(self)


def _grid(grid: dict) -> list[dict]:
    keys = list(grid)
    return [dict(zip(keys, combo)) for combo in itertools.product(*(grid[k] for k in keys))]


MAX_COMBINATIONS = 500


def sweep(name: str, bars: list[Bar], grid: dict, *, symbol: str = "", train_fraction: float = 0.7,
          starting_cash: float = 10_000.0, cost: CostModel = DEFAULT_COST) -> SweepResult:
    if not 0.3 <= train_fraction <= 0.9:
        raise LabError("the first part must be between 30% and 90% of the history")
    combos = _grid(grid) if grid and all(grid.values()) else []
    if not combos:
        raise LabError("nothing to try: give at least one setting with at least one value")
    if len(combos) > MAX_COMBINATIONS:
        raise LabError(f"{len(combos)} combinations is too many (limit {MAX_COMBINATIONS}). The more you try, "
                       "the more likely the best one is a coincidence")
    cut = int(len(bars) * train_fraction)
    first, last = bars[:cut], bars
    rows = []
    for params in combos:
        try:
            a = evaluate(name, first, symbol=symbol, params=params, starting_cash=starting_cash, cost=cost,
                         keep_trades=False)
            # The last part is scored on its own window, but the strategy is given the earlier bars to warm up on.
            warm = make_strategy(name, params).warmup()
            tail = last[max(0, cut - warm):]
            b = evaluate(name, tail, symbol=symbol, params=params, starting_cash=starting_cash, cost=cost,
                         keep_trades=False)
        except LabError:
            continue
        rows.append({"params": params,
                     "first_return_pct": a.metrics["total_return_pct"], "first_trades": a.metrics["trades"],
                     "first_drawdown_pct": a.metrics["max_drawdown_pct"],
                     "last_return_pct": b.metrics["total_return_pct"], "last_trades": b.metrics["trades"],
                     "last_drawdown_pct": b.metrics["max_drawdown_pct"],
                     "last_buy_hold_pct": b.metrics["buy_hold_return_pct"]})
    if not rows:
        raise LabError("none of those settings could run on this history (not enough days, or invalid values)")
    rows.sort(key=lambda r: r["first_return_pct"], reverse=True)
    best = rows[0]
    notes = [f"Tried {len(rows)} settings on the first {train_fraction:.0%} of the history, then checked each "
             "on the rest, which played no part in the choice."]
    if best["last_return_pct"] <= 0:
        notes.append("The winner LOST money on the part it had not seen. That is what a coincidence looks like.")
    elif best["last_return_pct"] < best["last_buy_hold_pct"]:
        notes.append("The winner made money on the unseen part, but less than buying and holding did.")
    else:
        notes.append("The winner also beat buying and holding on the unseen part. Encouraging, not proof.")
    held = sum(1 for r in rows if r["last_return_pct"] > 0)
    notes.append(f"{held} of {len(rows)} settings made money on the unseen part. When most do, the idea is "
                 "sturdy; when only the winner does, it is fragile.")
    if len(rows) > 20:
        notes.append(f"With {len(rows)} tries, the best result is flattered by luck. Expect less in practice.")
    return SweepResult(name, symbol.upper(), bars[cut].ts if cut < len(bars) else bars[-1].ts, len(rows),
                       rows, best, notes)
