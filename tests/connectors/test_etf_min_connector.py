from pathlib import Path

import pandas as pd
import pytest

import czsc
import czsc.connectors.etf_min_connector as emc

DATA_PATH = Path("/mnt/h/etf_min/etf_min_parquet_2000-2026")

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
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["symbol", "dt", "open", "close", "high", "low", "vol", "amount"]
    assert len(df) > 0


def test_etf_resample_fallback():
    bars = emc.get_raw_bars("510300.SH", "2分钟", "20240101", "20240131")
    assert len(bars) > 0
    assert bars[0].freq == czsc.Freq.F2


def test_etf_fq_default_is_hfq():
    """默认 fq='后复权' 应与 '不复权' 价格不同（510300 有复权因子）。"""
    df_hfq = emc.get_raw_bars("510300.SH", "30分钟", "20240101", "20240131", raw_bars=False, fq="后复权")
    df_raw = emc.get_raw_bars("510300.SH", "30分钟", "20240101", "20240131", raw_bars=False, fq="不复权")
    assert not df_hfq["close"].equals(df_raw["close"])
    # 后复权收盘价应整体高于未复权（510300 近年因子 > 1）
    assert df_hfq["close"].mean() > df_raw["close"].mean()


def test_etf_fq_qfq_relation():
    """同一交易日的 前复权/后复权 收盘价比例应为固定值。"""
    df_qfq = emc.get_raw_bars("510300.SH", "30分钟", "20240101", "20240131", raw_bars=False, fq="前复权")
    df_hfq = emc.get_raw_bars("510300.SH", "30分钟", "20240101", "20240131", raw_bars=False, fq="后复权")
    ratio = df_qfq["close"] / df_hfq["close"]
    # 同一交易日内所有分钟的比例应相同（浮点误差范围内）
    daily_std = ratio.groupby(df_qfq["dt"].dt.date).std()
    assert (daily_std < 1e-12).all()
