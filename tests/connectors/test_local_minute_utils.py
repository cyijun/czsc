import pandas as pd
import pytest

import czsc
from czsc.connectors._local_minute_utils import (
    _filter_by_date,
    _freq_to_dir,
    _parse_symbol,
    _standardize_kline,
)


def test_parse_symbol_tushare():
    assert _parse_symbol("510300.SH") == ("sh510300", "sh", "510300")
    assert _parse_symbol("000001.SZ") == ("sz000001", "sz", "000001")


def test_parse_symbol_prefixed():
    assert _parse_symbol("sh510300") == ("sh510300", "sh", "510300")
    assert _parse_symbol("sz000001") == ("sz000001", "sz", "000001")


def test_parse_symbol_plain():
    assert _parse_symbol("510300") == ("510300", "", "510300")
    assert _parse_symbol("000001") == ("000001", "", "000001")


def test_freq_to_dir_string():
    assert _freq_to_dir("1分钟") == "1min"
    assert _freq_to_dir("5分钟") == "5min"
    assert _freq_to_dir("60分钟") == "60min"


def test_freq_to_dir_enum():
    assert _freq_to_dir(czsc.Freq.F5) == "5min"
    assert _freq_to_dir(czsc.Freq.F1) == "1min"


def test_freq_to_dir_unsupported():
    with pytest.raises(ValueError):
        _freq_to_dir("日线")


def test_standardize_kline():
    df = pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2024-01-01 09:31:00", "2024-01-01 09:32:00"]),
            "open": [1.0, 1.1],
            "close": [2.0, 2.1],
            "high": [3.0, 3.1],
            "low": [0.5, 0.6],
            "volume": [100, 200],
            "amount": [1000.0, 2000.0],
        }
    )
    out = _standardize_kline(df, "sh", "510300")
    assert list(out.columns) == ["symbol", "dt", "open", "close", "high", "low", "vol", "amount"]
    assert out["symbol"].tolist() == ["510300.SH", "510300.SH"]
    assert out["dt"].dtype == "datetime64[ns]"


def test_standardize_kline_empty():
    out = _standardize_kline(pd.DataFrame(), "sh", "510300")
    assert list(out.columns) == ["symbol", "dt", "open", "close", "high", "low", "vol", "amount"]
    assert len(out) == 0


def test_filter_by_date():
    df = pd.DataFrame(
        {
            "dt": pd.to_datetime(["2024-01-01", "2024-01-15", "2024-02-01"]),
            "close": [1.0, 2.0, 3.0],
        }
    )
    out = _filter_by_date(df, "2024-01-01", "2024-01-31")
    assert len(out) == 2
    assert out["dt"].iloc[-1] == pd.Timestamp("2024-01-15")
