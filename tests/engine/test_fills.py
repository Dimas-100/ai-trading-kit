import pytest

from aitk.engine.fills import CostModel, describe, fill_price
from aitk.engine.models import Bar, Order, OrderType, Side

BAR = Bar(ts="2024-01-02", open=100.0, high=105.0, low=95.0, close=102.0)


def o(side, otype, limit=None, stop=None):
    return Order(symbol="X", side=side, quantity=1, order_type=otype, limit_price=limit, stop_price=stop)


def test_market_fills_at_open():
    assert fill_price(o(Side.BUY, OrderType.MARKET), BAR) == 100.0
    assert fill_price(o(Side.SELL, OrderType.MARKET), BAR) == 100.0


def test_limit_buy_fills_at_better_of_limit_and_open_only_if_touched():
    assert fill_price(o(Side.BUY, OrderType.LIMIT, limit=98.0), BAR) == 98.0
    assert fill_price(o(Side.BUY, OrderType.LIMIT, limit=103.0), BAR) == 100.0   # opened below the limit
    assert fill_price(o(Side.BUY, OrderType.LIMIT, limit=94.0), BAR) is None


def test_limit_sell_mirror():
    assert fill_price(o(Side.SELL, OrderType.LIMIT, limit=104.0), BAR) == 104.0
    assert fill_price(o(Side.SELL, OrderType.LIMIT, limit=99.0), BAR) == 100.0
    assert fill_price(o(Side.SELL, OrderType.LIMIT, limit=106.0), BAR) is None


def test_stop_sell_gap_through_fills_at_open():
    assert fill_price(o(Side.SELL, OrderType.STOP, stop=97.0), BAR) == 97.0
    gap = Bar(ts="2024-01-03", open=90.0, high=92.0, low=88.0, close=91.0)
    assert fill_price(o(Side.SELL, OrderType.STOP, stop=97.0), gap) == 90.0
    assert fill_price(o(Side.SELL, OrderType.STOP, stop=94.0), BAR) is None


def test_stop_buy_mirror():
    assert fill_price(o(Side.BUY, OrderType.STOP, stop=103.0), BAR) == 103.0
    gap = Bar(ts="2024-01-03", open=110.0, high=112.0, low=108.0, close=111.0)
    assert fill_price(o(Side.BUY, OrderType.STOP, stop=103.0), gap) == 110.0
    assert fill_price(o(Side.BUY, OrderType.STOP, stop=106.0), BAR) is None


def test_stop_limit_sell():
    assert fill_price(o(Side.SELL, OrderType.STOP_LIMIT, stop=97.0, limit=96.0), BAR) == 97.0
    gap = Bar(ts="2024-01-03", open=90.0, high=97.5, low=88.0, close=91.0)
    # gapped below the limit; price later recovers to the limit -> fills at the limit
    assert fill_price(o(Side.SELL, OrderType.STOP_LIMIT, stop=97.0, limit=96.0), gap) == 96.0
    deep = Bar(ts="2024-01-04", open=90.0, high=93.0, low=88.0, close=91.0)
    assert fill_price(o(Side.SELL, OrderType.STOP_LIMIT, stop=97.0, limit=96.0), deep) is None


def test_slippage_is_against_the_trader():
    cost = CostModel(slippage_pct=1.0)
    assert fill_price(o(Side.BUY, OrderType.MARKET), BAR, cost) == pytest.approx(101.0)
    assert fill_price(o(Side.SELL, OrderType.MARKET), BAR, cost) == pytest.approx(99.0)


def test_describe_is_human_readable():
    s = describe(Order(symbol="SPY", side=Side.BUY, quantity=3, order_type=OrderType.MARKET))
    assert "BUY 3 SPY MARKET" in s
    s2 = describe(o(Side.SELL, OrderType.STOP, stop=95.0))
    assert "stop 95.00" in s2
