"""Finding strategies: the built-in ones plus any the person wrote.

A person's own strategy is one Python file in the kit's home folder (strategies/). It is loaded by
name, so a mistake in one file is reported for that file and does not stop the others."""
from __future__ import annotations

import importlib.util
import inspect
import re
import sys

from . import paths
from .engine import strategy as registry

_NAME = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
_loaded: dict[str, float] = {}
load_errors: dict[str, str] = {}

TEMPLATE = '''"""{title}: describe the idea in one sentence here.

A strategy looks at price bars (oldest first, newest last) and answers for the NEWEST bar only:
buy, sell, or nothing. It never sees an account and cannot place an order. The backtest and the
practice account do that, always at the NEXT day's prices.
"""
from aitk.engine.indicators import sma
from aitk.engine.models import Bar, Side, Signal
from aitk.engine.strategy import register


@register
class {cls}:
    name = "{name}"
    summary = "Buy when the price closes above its average, sell when it closes below."
    level = "yours"

    def __init__(self, period: int = 50, stop_pct: float = 8.0):
        self.period = int(period)
        self.stop_pct = float(stop_pct)

    def warmup(self) -> int:
        """How many bars are needed before the first decision."""
        return self.period + 1

    def on_bars(self, bars: list[Bar]) -> Signal:
        if len(bars) < self.warmup():
            return Signal(None, None, "warmup")
        closes = [b.close for b in bars]
        average = sma(closes, self.period)[-1]
        price = closes[-1]
        stop = round(price * (1 - self.stop_pct / 100), 2)
        if price > average and closes[-2] <= sma(closes, self.period)[-2]:
            return Signal(Side.BUY, stop, f"close {{price:.2f}} crossed above the {{self.period}}-day average")
        if price < average:
            return Signal(Side.SELL, None, f"close {{price:.2f}} is below the {{self.period}}-day average")
        return Signal(None, stop, "holding")
'''


class StrategyError(ValueError):
    pass


def load_user_strategies() -> None:
    folder = paths.strategies_dir()
    if not folder.exists():
        return
    for path in sorted(folder.glob("*.py")):
        if path.name.startswith("_"):
            continue
        mtime = path.stat().st_mtime
        if _loaded.get(str(path)) == mtime:
            continue
        module_name = f"aitk_user_strategy_{path.stem}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            load_errors.pop(path.name, None)
        except Exception as exc:                      # the person's own file: report, do not crash
            load_errors[path.name] = f"{type(exc).__name__}: {exc}"
            sys.modules.pop(module_name, None)
        _loaded[str(path)] = mtime


def names() -> list[str]:
    load_user_strategies()
    return registry.list_strategies()


def describe() -> list[dict]:
    load_user_strategies()
    out = []
    for name in registry.list_strategies():
        cls = registry._REGISTRY[name]
        settings = {}
        for pname, p in inspect.signature(cls.__init__).parameters.items():
            if pname == "self" or p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
                continue
            settings[pname] = None if p.default is inspect.Parameter.empty else p.default
        out.append({"name": name, "summary": getattr(cls, "summary", (cls.__doc__ or "").strip().split("\n")[0]),
                    "level": getattr(cls, "level", "yours"), "settings": settings})
    order = {"beginner": 0, "intermediate": 1, "advanced": 2, "yours": 3}
    return sorted(out, key=lambda d: (order.get(d["level"], 9), d["name"]))


def create(name: str) -> str:
    name = str(name).strip().lower().replace("-", "_")
    if not _NAME.match(name):
        raise StrategyError("use a short name in lower case, letters, digits and _ only (for example my_idea)")
    if name in names():
        raise StrategyError(f"a strategy called '{name}' already exists")
    folder = paths.ensure(paths.strategies_dir())
    target = folder / f"{name}.py"
    if target.exists():
        raise StrategyError(f"{target} already exists")
    cls = "".join(part.capitalize() for part in name.split("_"))
    target.write_text(TEMPLATE.format(title=name.replace("_", " ").capitalize(), cls=cls, name=name),
                      encoding="utf-8")
    return str(target)


def parse_settings(pairs) -> dict:
    """['fast=10', 'slow=30'] -> {'fast': 10, 'slow': 30}. Numbers become numbers."""
    out = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise StrategyError(f"'{pair}' is not a setting. Write it as name=value, for example fast=10")
        key, value = pair.split("=", 1)
        out[key.strip()] = _number(value.strip())
    return out


def parse_grid(pairs) -> dict:
    """['fast=10,20,30', 'slow=50,100'] -> {'fast': [10, 20, 30], 'slow': [50, 100]}."""
    out = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise StrategyError(f"'{pair}' is not a setting. Write it as name=v1,v2,v3")
        key, values = pair.split("=", 1)
        out[key.strip()] = [_number(v.strip()) for v in values.split(",") if v.strip()]
    return out


def _number(text: str):
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text
