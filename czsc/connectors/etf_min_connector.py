"""ETF minute data connector for local parquet dataset."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import cast

import pandas as pd
import polars as pl

import czsc
from czsc._format_standard_kline import format_standard_kline
from czsc.connectors._local_minute_utils import (
    _apply_fq,
    _filter_by_date,
    _freq_to_dir,
    _parse_symbol,
    _standardize_kline,
)

_ETF_BASE_PATH = Path(os.environ.get("CZSC_ETF_MIN_PATH", "/mnt/h/etf_min/etf_min_parquet_2000-2026"))


def get_symbols() -> list[str]:
    """Return list of available ETF symbols in Tushare style."""
    path = _ETF_BASE_PATH / "etf_1min.parquet"
    if not path.exists():
        raise FileNotFoundError(f"ETF 数据文件不存在: {path}")

    codes = pl.scan_parquet(str(path)).select(["code", "exchange"]).unique().collect(engine="streaming")

    symbols = []
    for row in codes.iter_rows(named=True):
        prefixed = row["code"]
        exchange = row["exchange"]
        numeric = prefixed[2:]
        symbols.append(f"{numeric}.{exchange.upper()}")
    return sorted(set(symbols))


def get_raw_bars(
    symbol: str,
    freq: czsc.Freq | str,
    sdt: str | datetime,
    edt: str | datetime,
    fq: str = "后复权",
    raw_bars: bool = True,
) -> list[czsc.RawBar] | pd.DataFrame:
    """读取本地 ETF 分钟 parquet，返回标准化 K 线。

    参数:
        symbol: ETF 代码，支持 510300.SH / sh510300 / 510300
        freq: 目标周期
        sdt: 开始时间
        edt: 结束时间
        fq: 复权类型，支持 ``"前复权"``、``"后复权"``、``"不复权"``；
            默认 ``"后复权"``。若该 ETF 没有复权因子文件，则回退到未复权并警告。
        raw_bars: True 返回 list[RawBar]，False 返回 DataFrame
    """
    prefixed_code, exchange, numeric = _parse_symbol(symbol)

    freq_str = freq.value if isinstance(freq, czsc.Freq) else freq
    freq_dir = _freq_to_dir(freq) if freq_str in {"1分钟", "5分钟", "15分钟", "30分钟", "60分钟"} else None

    exact_path = _ETF_BASE_PATH / f"etf_{freq_dir}.parquet" if freq_dir else None
    if exact_path and exact_path.exists():
        df = _read_etf_bars(exact_path, prefixed_code, exchange, numeric)
    else:
        base_path = _ETF_BASE_PATH / "etf_1min.parquet"
        if not base_path.exists():
            raise FileNotFoundError(f"找不到 ETF 1分钟数据文件: {base_path}")
        df = _read_etf_bars(base_path, prefixed_code, exchange, numeric)
        df = cast(pd.DataFrame, czsc.resample_bars(df, target_freq=freq, raw_bars=False, base_freq="1分钟"))

    df = _apply_fq(df, prefixed_code, fq=fq)
    df = _filter_by_date(df, sdt, edt)
    if df.empty:
        return [] if raw_bars else df

    if raw_bars:
        freq_enum = czsc.Freq(freq) if isinstance(freq, str) else freq
        return format_standard_kline(df, freq=freq_enum)
    return df


def _read_etf_bars(
    path: Path,
    prefixed_code: str,
    exchange: str,
    numeric: str,
) -> pd.DataFrame:
    lf = pl.scan_parquet(str(path))
    if exchange:
        lf = lf.filter(pl.col("code") == prefixed_code)
    else:
        lf = lf.filter((pl.col("code") == f"sh{numeric}") | (pl.col("code") == f"sz{numeric}"))
    df = lf.collect().to_pandas()
    return _standardize_kline(df, exchange, numeric)
