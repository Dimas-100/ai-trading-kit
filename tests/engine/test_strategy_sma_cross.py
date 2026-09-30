from datetime import date, timedelta

from aitk.engine.models import Bar, Side, Signal
from aitk.engine.strategies.sma_cross import SmaCross
from aitk.engine.strategy import Strategy, get_strategy, list_strategies


def bars_from_closes(closes):
    d0 = date(2024, 1, 1)
    return [Bar(ts=(d0 + timedelta(days=i)).isoformat(), open=c, high=c + 1, low=c - 1, close=c)
            for i, c in enumerate(closes)]


def test_registry_and_protocol():
    assert "sma_cross" in list_strategies()
    s = get_strategy("sma_cross", fast=2, slow=3)
    assert isinstance(s, Strategy) and s.name == "sma_cross" and s.slow == 3


def test_warmup_returns_neutral_signal():
    s = SmaCross(fast=2, slow=3, atr_period=2)
    assert s.on_bars(bars_from_closes([1, 2])) == Signal(None, None, "warmup")
    assert s.on_bars([]) == Signal(None, None, "warmup")


def test_cross_up_emits_buy_with_atr_stop_and_then_holds_stop():
    s = SmaCross(fast=2, slow=3, atr_period=2, atr_mult=2.0)
    closes = [10, 9, 8, 7, 9, 12]        # fast(2) crosses above slow(3) on the last bar
    sig = s.on_bars(bars_from_closes(closes))
    assert sig.action is Side.BUY and sig.stop_price is not None and sig.stop_price < 12
    sig2 = s.on_bars(bars_from_closes(closes + [13]))
    assert sig2.action is None and sig2.stop_price is not None and "long" in sig2.note


def test_cross_down_emits_sell_without_stop():
    s = SmaCross(fast=2, slow=3, atr_period=2)
    closes = [7, 8, 9, 10, 8, 5]
    sig = s.on_bars(bars_from_closes(closes))
    assert sig.action is Side.SELL and sig.stop_price is None
    sig2 = s.on_bars(bars_from_closes(closes + [4]))
    assert sig2.action is None and sig2.stop_price is None and "flat" in sig2.note


def test_warmup_value_covers_both_indicators():
    assert SmaCross(fast=20, slow=50, atr_period=14).warmup() >= 51
