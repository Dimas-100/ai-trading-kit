"""Finding strategies: the built-in ones plus any the person wrote.

A person's own strategy is one Python file in the kit's home folder (strategies/). It is loaded by
name, so a mistake in one file is reported for that file and does not stop the others."""
from __future__ import annotations

import ast
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


# ── strategies written by an AI (or pasted by a person) ──────────────────────
# A strategy file is code the kit will run, so what an assistant may write is fenced: only the engine's
# own pieces and a little arithmetic may be imported, and nothing that touches files, the network or the
# system may appear. The check is on the source, before anything is written or run.
ALLOWED_IMPORTS = ("aitk.engine.indicators", "aitk.engine.models", "aitk.engine.strategy", "math", "statistics")
FORBIDDEN_NAMES = frozenset("""open exec eval compile __import__ globals locals vars getattr setattr delattr
    input breakpoint exit quit""".split())
FORBIDDEN_ATTRS = frozenset({"__subclasses__", "__globals__", "__builtins__", "__code__", "__class__", "__dict__",
                             "__bases__", "__mro__", "__loader__", "__spec__"})
MAX_SOURCE_BYTES = 40_000


def validate_source(code: str) -> list[str]:
    """Reasons the source may not be saved. Empty means it may."""
    problems = []
    if len(code.encode("utf-8")) > MAX_SOURCE_BYTES:
        return [f"the file is too large (over {MAX_SOURCE_BYTES // 1000} KB); a strategy should be short"]
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"it is not valid Python: line {exc.lineno}: {exc.msg}"]
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for name in names:
                if not any(name == ok or name.startswith(ok + ".") for ok in ALLOWED_IMPORTS):
                    problems.append(f"it imports '{name}'; a strategy may import only "
                                    f"{', '.join(ALLOWED_IMPORTS)}")
            if isinstance(node, ast.ImportFrom) and node.level:
                problems.append("relative imports are not allowed")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            problems.append(f"it uses '{node.id}', which is not allowed in a strategy")
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_ATTRS:
            problems.append(f"it uses '{node.attr}', which is not allowed in a strategy")
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            problems.append("global/nonlocal are not needed in a strategy")
    registered = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)
                  and any((isinstance(d, ast.Name) and d.id == "register") for d in n.decorator_list)]
    if not registered:
        problems.append("no class is marked with @register (from aitk.engine.strategy import register)")
    return sorted(set(problems))


def _registered_name(code: str) -> str | None:
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for stmt in node.body:
                if (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name)
                        and stmt.targets[0].id == "name" and isinstance(stmt.value, ast.Constant)):
                    return str(stmt.value.value)
    return None


def save(name: str, code: str, overwrite: bool = False) -> dict:
    """Check, test-run and write a strategy file. Returns what happened, or raises StrategyError."""
    name = str(name).strip().lower().replace("-", "_")
    if not _NAME.match(name):
        raise StrategyError("use a short name in lower case, letters, digits and _ only (for example my_idea)")
    if name in ("buy_hold", "sma_cross", "rsi2", "donchian"):
        raise StrategyError(f"'{name}' is a built-in strategy; choose another name")
    problems = validate_source(code)
    if problems:
        raise StrategyError("the strategy was not saved: " + "; ".join(problems))
    declared = _registered_name(code)
    if declared != name:
        raise StrategyError(f"the class's name attribute is {declared!r} but the file is for '{name}'; make them match")
    folder = paths.ensure(paths.strategies_dir())
    target = folder / f"{name}.py"
    if target.exists() and not overwrite:
        raise StrategyError(f"{target} already exists. Say overwrite=true to replace it")
    # test-run in a scratch copy first, so a broken file never lands next to the working ones
    from .engine import backtest
    from .engine import strategy as registry
    from .engine.data import SyntheticBars
    scratch = folder / f"_checking_{name}.py"
    scratch.write_text(code, encoding="utf-8")
    module_name = f"aitk_user_strategy_check_{name}"
    before = dict(registry._REGISTRY)
    try:
        spec = importlib.util.spec_from_file_location(module_name, scratch)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        cls = registry._REGISTRY.get(name)
        if cls is None:
            raise StrategyError(f"the file ran but registered no strategy called '{name}'")
        strategy = cls()
        bars = SyntheticBars(seed=11, n=600, start="2021-01-04").bars("TEST", 600)
        result = backtest.run(strategy, bars, starting_equity=10_000.0)
    except StrategyError:
        raise
    except Exception as exc:
        raise StrategyError(f"the strategy failed when run: {type(exc).__name__}: {exc}") from exc
    finally:
        sys.modules.pop(module_name, None)
        registry._REGISTRY.clear()
        registry._REGISTRY.update(before)
        try:
            scratch.unlink()
        except OSError:
            pass
    target.write_text(code, encoding="utf-8")
    _loaded.pop(str(target), None)
    load_user_strategies()
    return {"saved": str(target), "name": name,
            "smoke_test": {"on": "made-up prices, 600 days", "trades": result.metrics["trades"],
                           "total_return_pct": result.metrics["total_return_pct"]},
            "next": f"aitk backtest {name} SPY   (or the backtest tool)"}


def read(name: str) -> str:
    name = str(name).strip().lower()
    target = paths.strategies_dir() / f"{name}.py"
    if not target.exists():
        raise StrategyError(f"no file called {name}.py in {paths.strategies_dir()}")
    return target.read_text(encoding="utf-8")


def template(name: str = "my_idea") -> str:
    name = str(name).strip().lower().replace("-", "_") or "my_idea"
    cls = "".join(part.capitalize() for part in name.split("_")) or "MyIdea"
    return TEMPLATE.format(title=name.replace("_", " ").capitalize(), cls=cls, name=name)
