from pathlib import Path

import pytest

import czsc
import czsc.connectors.etf_min_connector as emc

DATA_PATH = Path("/mnt/h/etf_min/etf_min_parquet_2000-2025")

pytestmark = pytest.mark.skipif(
    not DATA_PATH.exists(),
    reason="本地 ETF 分钟数据不存在",
)


def test_etf_get_symbols():
    symbols = emc.get_symbols()
    assert "510300.SH" in symbols
    assert "159915.SZ" in symbols


def test_etf_get_raw_bars_tushare_format():
    bars = emc.get_raw_bars("510300.SH", "5分钟", "20240101", "20240131")
    assert len(bars) > 0
    assert isinstance(bars[0], czsc.RawBar)
    assert bars[0].freq == czsc.Freq.F5


def test_etf_get_raw_bars_all_formats():
    bars1 = emc.get_raw_bars("510300.SH", "5分钟", "20240101", "20240131")
    bars2 = emc.get_raw_bars("sh510300", "5分钟", "20240101", "20240131")
    bars3 = emc.get_raw_bars("510300", "5分钟", "20240101", "20240131")
    assert len(bars1) == len(bars2) == len(bars3) > 0


def test_etf_get_raw_bars_dataframe():
    df = emc.get_raw_bars("510300.SH", "5分钟", "20240101", "20240131", raw_bars=False)
    assert list(df.columns) == ["symbol", "dt", "open", "close", "high", "low", "vol", "amount"]
    assert len(df) > 0


def test_etf_resample_fallback():
    bars = emc.get_raw_bars("510300.SH", "2分钟", "20240101", "20240131")
    assert len(bars) > 0
    assert bars[0].freq == czsc.Freq.F2
