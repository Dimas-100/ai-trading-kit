from datetime import date, timedelta

import pytest

from aitk.engine.backtest import Result, Trade, format_metrics, run
from aitk.engine.models import Bar, Side, Signal


def bars_from(ohlc):
    d0 = date(2024, 1, 1)
    return [Bar(ts=(d0 + timedelta(days=i)).isoformat(), open=o, high=h, low=lo, close=c)
            for i, (o, h, lo, c) in enumerate(ohlc)]


class Scripted:
    """Signals keyed by bar index (of the newest bar the strategy sees)."""
    name = "scripted"

    def __init__(self, script, warm=1):
        self.script, self.warm = script, warm

    def warmup(self):
        return self.warm

    def on_bars(self, bars):
        return self.script.get(len(bars) - 1, Signal(None, None, ""))


def test_entry_next_open_exit_next_open_and_metrics():
    bars = bars_from([(10, 10, 10, 10), (10, 10, 10, 10), (12, 12, 12, 12), (13, 13, 13, 13), (15, 15, 15, 15)])
    strat = Scripted({1: Signal(Side.BUY, None, "go"), 3: Signal(Side.SELL, None, "out")})
    r = run(strat, bars, starting_equity=1000.0)
    assert isinstance(r, Result) and len(r.trades) == 1
    t = r.trades[0]
    assert isinstance(t, Trade)
    assert t.entry_ts == bars[2].ts and t.entry_price == 12.0        # bar 1 signal -> bar 2 open
    assert t.exit_ts == bars[4].ts and t.exit_price == 15.0          # bar 3 signal -> bar 4 open
    assert t.quantity == 83 and t.pnl == pytest.approx(83 * 3.0) and t.reason == "signal"
    assert r.metrics["trades"] == 1 and r.metrics["win_rate_pct"] == 100.0
    assert r.final_equity == pytest.approx(1000.0 + 249.0)
    assert r.metrics["total_return_pct"] == pytest.approx(24.9)
    assert r.equity_curve[0][1] == 1000.0 and r.equity_curve[-1][1] == pytest.approx(1249.0)


def test_stop_from_entry_bar_signal_is_checked_from_the_next_bar():
    bars = bars_from([(10, 10, 10, 10), (10, 10, 10, 10), (12, 13, 11, 12), (11, 12, 9, 10), (10, 10, 10, 10)])
    # entry at bar 2 open (12); bar 2's signal sets the stop at 11; bar 3 low 9 <= 11, open 11 -> fill 11
    strat = Scripted({1: Signal(Side.BUY, 9.0, "go"), 2: Signal(None, 11.0, "long")})
    r = run(strat, bars, starting_equity=1200.0)
    t = r.trades[0]
    assert t.reason == "stop" and t.exit_ts == bars[3].ts and t.exit_price == 11.0
    assert t.quantity == 100 and t.pnl == pytest.approx(-100.0)


def test_stop_is_not_checked_on_the_entry_bar_itself():
    bars = bars_from([(10, 10, 10, 10), (10, 10, 10, 10), (12, 13, 5, 12), (12, 12, 12, 12)])
    strat = Scripted({1: Signal(Side.BUY, 11.0, "go"), 2: Signal(None, 11.0, "long")})
    r = run(strat, bars, starting_equity=1200.0)
    assert r.trades[0].reason == "end" and r.trades[0].exit_price == 12.0


def test_open_position_closes_at_end_and_dollars_per_trade_caps_size():
    bars = bars_from([(10, 10, 10, 10), (10, 10, 10, 10), (10, 10, 10, 10), (20, 20, 20, 20)])
    strat = Scripted({1: Signal(Side.BUY, None, "go")})
    r = run(strat, bars, starting_equity=10_000.0, dollars_per_trade=100.0)
    assert r.trades[0].quantity == 10 and r.trades[0].reason == "end" and r.trades[0].exit_price == 20.0
    assert r.metrics["max_drawdown_pct"] == 0.0 and r.metrics["exposure_pct"] > 0


def test_no_trades_metrics_and_format():
    bars = bars_from([(10, 10, 10, 10)] * 5)
    r = run(Scripted({}), bars)
    assert r.trades == [] and r.metrics["trades"] == 0 and r.metrics["win_rate_pct"] == 0.0
    text = format_metrics(r)
    assert "trades" in text and "max_drawdown_pct" in text


def test_costs_reconcile_pnl_with_equity_and_slip_against_the_trader():
    from aitk.engine.fills import CostModel
    bars = bars_from([(10, 10, 10, 10), (10, 10, 10, 10), (10, 10, 10, 10), (12, 12, 12, 12), (12, 12, 12, 12)])
    strat = Scripted({1: Signal(Side.BUY, None, "go"), 3: Signal(Side.SELL, None, "out")})
    cost = CostModel(slippage_pct=1.0, commission=1.0)
    r = run(strat, bars, starting_equity=1000.0, cost=cost)
    t = r.trades[0]
    assert t.entry_price == pytest.approx(10.1)        # slipped up on the buy
    assert t.exit_price == pytest.approx(11.88)        # slipped down on the sell
    assert t.quantity == 99                            # floor(1000 / 10.1)
    assert t.pnl == pytest.approx(t.quantity * (11.88 - 10.1) - 2.0)
    assert sum(x.pnl for x in r.trades) == pytest.approx(r.final_equity - r.starting_equity)
