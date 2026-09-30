"""Donchian channel breakout, long only (the classic trend-following rule).

Buy when the close breaks above the highest high of the previous `entry` bars. Sell when the close breaks
below the lowest low of the previous `exit` bars. That exit level is also the protective stop."""
from __future__ import annotations

from ..models import Bar, Side, Signal
from ..strategy import register


@register
class Donchian:
    name = "donchian"
    summary = "Buy a new high, sell a new low. Few trades, long holds, large winners pay for small losers."
    level = "intermediate"

    def __init__(self, entry: int = 55, exit: int = 20):
        if int(exit) < 1 or int(entry) < 1:
            raise ValueError("entry and exit must be at least 1")
        self.entry, self.exit = int(entry), int(exit)

    def warmup(self) -> int:
        return max(self.entry, self.exit) + 1

    def on_bars(self, bars: list[Bar]) -> Signal:
        if len(bars) < self.warmup():
            return Signal(None, None, "warmup")
        close = bars[-1].close
        upper = max(b.high for b in bars[-self.entry - 1:-1])
        lower = min(b.low for b in bars[-self.exit - 1:-1])
        stop = round(lower, 2) if 0 < lower < close else None
        if close > upper:
            return Signal(Side.BUY, stop, f"close {close:.2f} above the {self.entry}-bar high {upper:.2f}")
        if close < lower:
            return Signal(Side.SELL, None, f"close {close:.2f} below the {self.exit}-bar low {lower:.2f}")
        return Signal(None, stop, "inside the channel")
