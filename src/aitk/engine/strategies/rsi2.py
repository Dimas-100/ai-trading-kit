"""RSI(2) mean reversion, long only (after Larry Connors' published rule).

Buy a strong stock after a sharp short-term drop: the close is above its long moving average (the trend
filter) and the 2-day RSI is below `entry`. Sell when the 2-day RSI recovers above `exit`. The signal
carries a protective stop `stop_pct` percent under the close."""
from __future__ import annotations

from ..indicators import rsi, sma
from ..models import Bar, Side, Signal
from ..strategy import register


@register
class Rsi2:
    name = "rsi2"
    summary = "Buy a sharp dip in an uptrend, sell the bounce. Many small wins, short holds."
    level = "intermediate"

    def __init__(self, period: int = 2, entry: float = 10.0, exit: float = 70.0, trend: int = 200,
                 stop_pct: float = 8.0):
        if not 0 < float(entry) < float(exit) < 100:
            raise ValueError("need 0 < entry < exit < 100")
        self.period, self.trend = int(period), int(trend)
        self.entry, self.exit, self.stop_pct = float(entry), float(exit), float(stop_pct)

    def warmup(self) -> int:
        return max(self.trend, self.period + 1) + 1

    def on_bars(self, bars: list[Bar]) -> Signal:
        if len(bars) < self.warmup():
            return Signal(None, None, "warmup")
        closes = [b.close for b in bars]
        r = rsi(closes, self.period)[-1]
        trend = sma(closes, self.trend)[-1]
        if r is None or trend is None:
            return Signal(None, None, "warmup")
        stop = round(closes[-1] * (1 - self.stop_pct / 100.0), 2) if self.stop_pct > 0 else None
        if r > self.exit:
            return Signal(Side.SELL, None, f"RSI({self.period}) {r:.1f} above {self.exit:g}")
        if r < self.entry and closes[-1] > trend:
            return Signal(Side.BUY, stop, f"RSI({self.period}) {r:.1f} below {self.entry:g}, above SMA({self.trend})")
        return Signal(None, stop, f"RSI({self.period}) {r:.1f}")
