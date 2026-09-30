"""SMA crossover, long only — the textbook stand-in, deliberately generic.

BUY on the bar where the fast SMA crosses above the slow; SELL on the bar where it crosses below.
Whenever fast > slow the signal also carries a protective stop at close - atr_mult x ATR so the
runner's PROTECT step can place one under a held position (placed once, not trailed)."""
from __future__ import annotations

from ..indicators import atr, sma
from ..models import Bar, Side, Signal
from ..strategy import register


@register
class SmaCross:
    name = "sma_cross"
    summary = "Buy when the short average crosses above the long one, sell when it crosses back."
    level = "beginner"

    def __init__(self, fast: int = 20, slow: int = 50, atr_period: int = 14, atr_mult: float = 2.0):
        if int(fast) >= int(slow):
            raise ValueError("fast must be shorter than slow")
        self.fast, self.slow = int(fast), int(slow)
        self.atr_period, self.atr_mult = int(atr_period), float(atr_mult)

    def warmup(self) -> int:
        return max(self.slow, self.atr_period + 1) + 1

    def on_bars(self, bars: list[Bar]) -> Signal:
        if len(bars) < self.warmup():
            return Signal(None, None, "warmup")
        closes = [b.close for b in bars]
        f = sma(closes, self.fast)
        s = sma(closes, self.slow)
        a = atr([b.high for b in bars], [b.low for b in bars], closes, self.atr_period)
        if None in (f[-1], s[-1], f[-2], s[-2]):
            return Signal(None, None, "warmup")
        long_regime = f[-1] > s[-1]
        stop = None
        if long_regime and a[-1] is not None:
            level = closes[-1] - self.atr_mult * a[-1]
            stop = round(level, 2) if level > 0 else None
        if f[-2] <= s[-2] and f[-1] > s[-1]:
            return Signal(Side.BUY, stop, f"fast SMA({self.fast}) crossed above slow SMA({self.slow})")
        if f[-2] >= s[-2] and f[-1] < s[-1]:
            return Signal(Side.SELL, None, f"fast SMA({self.fast}) crossed below slow SMA({self.slow})")
        return Signal(None, stop, "long regime" if long_regime else "flat regime")
