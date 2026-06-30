from pathlib import Path

import pandas as pd
import pytest

import czsc
import czsc.connectors.stock_min_connector as smc

DATA_PATH = Path("/mnt/h/stock_min/stk_min_parquet_2000-2026")

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


def test_stock_fq_default_is_hfq():
    """默认 fq='后复权' 应与 '不复权' 价格不同。"""
    df_hfq = smc.get_raw_bars("000001.SZ", "30分钟", "20240101", "20240131", raw_bars=False, fq="后复权")
    df_raw = smc.get_raw_bars("000001.SZ", "30分钟", "20240101", "20240131", raw_bars=False, fq="不复权")
    assert not df_hfq["close"].equals(df_raw["close"])


def test_stock_fq_qfq_relation():
    """同一交易日的 前复权/后复权 收盘价比例应为固定值。"""
    df_qfq = smc.get_raw_bars("000001.SZ", "30分钟", "20240101", "20240131", raw_bars=False, fq="前复权")
    df_hfq = smc.get_raw_bars("000001.SZ", "30分钟", "20240101", "20240131", raw_bars=False, fq="后复权")
    ratio = df_qfq["close"] / df_hfq["close"]
    daily_std = ratio.groupby(df_qfq["dt"].dt.date).std()
    assert (daily_std < 1e-12).all()
