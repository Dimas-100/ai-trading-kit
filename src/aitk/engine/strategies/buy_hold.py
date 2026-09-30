"""Buy and hold: buy on the first bar it can, never sell. The benchmark every other idea has to beat."""
from __future__ import annotations

from ..models import Bar, Side, Signal
from ..strategy import register


@register
class BuyHold:
    name = "buy_hold"
    summary = "Buy once and hold. The benchmark: an idea that cannot beat this is not worth the effort."
    level = "beginner"

    def warmup(self) -> int:
        return 1

    def on_bars(self, bars: list[Bar]) -> Signal:
        if not bars:
            return Signal(None, None, "warmup")
        return Signal(Side.BUY, None, "buy and hold")
