import pytest

from aitk.engine.indicators import atr, ema, rsi, sma


def test_sma_alignment_and_warmup():
    assert sma([1, 2, 3, 4, 5], 3) == [None, None, 2.0, 3.0, 4.0]
    assert sma([1, 2], 0) == [None, None]


def test_ema_seeds_with_sma_then_smooths():
    out = ema([1, 2, 3, 4, 5], 3)
    assert out[:2] == [None, None] and out[2] == 2.0
    assert out[3] == pytest.approx(3.0) and out[4] == pytest.approx(4.0)


def test_rsi_all_up_is_100_and_warmup():
    out = rsi([1, 2, 3, 4, 5, 6], 3)
    assert out[:3] == [None, None, None] and out[3] == 100.0 and out[-1] == 100.0


def test_atr_wilder():
    highs = [10, 11, 12, 13, 14]
    lows = [9, 10, 11, 12, 13]
    closes = [9.5, 10.5, 11.5, 12.5, 13.5]
    out = atr(highs, lows, closes, 2)
    assert out[:2] == [None, None]
    assert out[2] == pytest.approx(1.5)
    assert out[3] == pytest.approx(1.5)
