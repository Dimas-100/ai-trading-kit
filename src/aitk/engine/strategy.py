"""The Strategy seam: a strategy sees only ascending bars and answers a Signal. It never sees a
broker, an account or an order. Built-in strategies register themselves by name."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import Bar, Signal

_REGISTRY: dict[str, type] = {}


@runtime_checkable
class Strategy(Protocol):
    name: str

    def warmup(self) -> int:
        """Bars needed before on_bars can answer anything but Signal(None, None, 'warmup')."""
        ...

    def on_bars(self, bars: list[Bar]) -> Signal:
        """`bars` ascending, newest last. Answer for the newest bar only."""
        ...


def register(cls):
    _REGISTRY[cls.name] = cls
    return cls


def _load_builtins() -> None:
    from . import strategies  # noqa: F401  (importing the package registers the built-ins)


def list_strategies() -> list[str]:
    _load_builtins()
    return sorted(_REGISTRY)


def get_strategy(name: str, **params) -> Strategy:
    _load_builtins()
    try:
        cls = _REGISTRY[name]
    except KeyError as exc:
        raise KeyError(f"unknown strategy {name!r}; available: {sorted(_REGISTRY)}") from exc
    return cls(**params)
