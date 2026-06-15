from pathlib import Path

import pandas as pd
import pytest

import czsc
import czsc.connectors.stock_min_connector as smc

DATA_PATH = Path("/mnt/h/stock_min/stk_min_parquet_2000-2025")

pytestmark = pytest.mark.skipif(
    not DATA_PATH.exists(),
    reason="本地 A 股分钟数据不存在",
)


def test_stock_get_symbols_all():
    symbols = smc.get_symbols()
    assert "000001.SZ" in symbols


def test_stock_get_symbols_sz():
    symbols = smc.get_symbols(step="sz")
    assert "000001.SZ" in symbols
    assert all(s.endswith(".SZ") for s in symbols)


def test_stock_get_raw_bars_tushare_format():
    bars = smc.get_raw_bars("000001.SZ", "1分钟", "20240101", "20240131")
    assert len(bars) > 0
    assert isinstance(bars[0], czsc.RawBar)
    assert bars[0].freq == czsc.Freq.F1


def test_stock_get_raw_bars_all_formats():
    bars1 = smc.get_raw_bars("000001.SZ", "1分钟", "20240101", "20240131")
    bars2 = smc.get_raw_bars("sz000001", "1分钟", "20240101", "20240131")
    bars3 = smc.get_raw_bars("000001", "1分钟", "20240101", "20240131")
    assert len(bars1) == len(bars2) == len(bars3) > 0


def test_stock_get_raw_bars_dataframe():
    df = smc.get_raw_bars("000001.SZ", "1分钟", "20240101", "20240131", raw_bars=False)
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["symbol", "dt", "open", "close", "high", "low", "vol", "amount"]
    assert len(df) > 0


def test_stock_resample_fallback():
    bars = smc.get_raw_bars("000001.SZ", "2分钟", "20240101", "20240131")
    assert len(bars) > 0
    assert bars[0].freq == czsc.Freq.F2
