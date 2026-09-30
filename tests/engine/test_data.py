import pytest

from aitk.engine.data import CsvBars, DataError, SyntheticBars, sort_bars
from aitk.engine.models import Bar


def b(ts, c=1.0):
    return Bar(ts=ts, open=c, high=c, low=c, close=c)


def test_sort_bars_is_ascending_stable_and_idempotent():
    desc = [b("2024-01-03"), b("2024-01-02"), b("2024-01-01")]
    asc = sort_bars(desc)
    assert [x.ts for x in asc] == ["2024-01-01", "2024-01-02", "2024-01-03"]
    assert sort_bars(asc) == asc                       # already ascending: untouched
    assert sort_bars(sort_bars(desc)) == asc           # double application is a no-op
    assert sort_bars([]) == []


def test_csv_directory_source(tmp_path):
    (tmp_path / "SPY.csv").write_text(
        "Date,Open,High,Low,Close,Volume\n"
        "2024-01-03,3,4,2,3.5,100\n"
        "2024-01-02,2,3,1,2.5,100\n"
        "2024-01-04,4,5,3,4.5,100\n")
    src = CsvBars(tmp_path)
    bars = src.bars("spy", 10)
    assert [x.ts for x in bars] == ["2024-01-02", "2024-01-03", "2024-01-04"]
    assert bars[-1].close == 4.5 and bars[0].volume == 100.0
    assert src.bars("SPY", 2)[0].ts == "2024-01-03"
    assert src.last_price("SPY") == 4.5
    assert src.bars("SPY", 10, as_of="2024-01-03")[-1].ts == "2024-01-03"
    assert src.last_price("SPY", as_of="2024-01-02") == 2.5


def test_csv_single_file_with_symbol_column(tmp_path):
    f = tmp_path / "bars.csv"
    f.write_text("symbol,time,open,high,low,close,volume\n"
                 "AAA,2024-01-02,1,1,1,1,0\nBBB,2024-01-02,2,2,2,2,0\nAAA,2024-01-03,3,3,3,3,0\n")
    src = CsvBars(f)
    assert [x.close for x in src.bars("AAA", 5)] == [1.0, 3.0]
    assert src.last_price("BBB") == 2.0


def test_csv_rejects_missing_symbol_and_non_iso_dates(tmp_path):
    (tmp_path / "BAD.csv").write_text("date,open,high,low,close\n01/05/2024,1,1,1,1\n")
    src = CsvBars(tmp_path)
    with pytest.raises(DataError):
        src.bars("BAD", 5)
    with pytest.raises(DataError):
        src.bars("NOPE", 5)


def test_csv_rejects_missing_columns(tmp_path):
    (tmp_path / "X.csv").write_text("date,open,close\n2024-01-02,1,1\n")
    with pytest.raises(DataError):
        CsvBars(tmp_path).bars("X", 5)


def test_synthetic_is_deterministic_and_well_formed():
    a = SyntheticBars(seed=7, n=300).bars("SPY", 300)
    b2 = SyntheticBars(seed=7, n=300).bars("SPY", 300)
    assert a == b2 and len(a) == 300
    assert SyntheticBars(seed=8, n=300).bars("SPY", 300) != a
    assert SyntheticBars(seed=7, n=300).bars("QQQ", 300) != a
    for bar in a:
        assert bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high
        assert bar.low > 0
    assert [x.ts for x in a] == sorted(x.ts for x in a)
    assert SyntheticBars(seed=7, n=300).bars("SPY", 50) == a[-50:]
    cut = SyntheticBars(seed=7, n=300).bars("SPY", 300, as_of=a[100].ts)
    assert cut[-1].ts == a[100].ts and len(cut) == 101
    assert SyntheticBars(seed=7, n=300).last_price("SPY") == a[-1].close
