"""A-share minute data connector for local parquet dataset."""

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
    _filter_by_date,
    _freq_to_dir,
    _parse_symbol,
    _standardize_kline,
)

_STOCK_BASE_PATH = Path(os.environ.get("CZSC_STOCK_MIN_PATH", "/mnt/h/stock_min/stk_min_parquet_2000-2025"))
_EXCHANGES = ("sz", "sh", "bj")


def get_symbols(step: str = "all") -> list[str]:
    """Return list of available A-share symbols.

    :param step: "all" | "sz" | "sh" | "bj"
    """
    step = step.lower()
    exchanges = _EXCHANGES if step == "all" else (step,)

    symbols = []
    freq_dir = _freq_to_dir("1分钟")
    for exchange in exchanges:
        dir_path = _STOCK_BASE_PATH / freq_dir / exchange
        if not dir_path.exists():
            continue
        for file in sorted(dir_path.glob("*.parquet")):
            prefixed = file.stem
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
    """读取本地 A 股分钟 parquet，返回标准化 K 线。

    参数:
        symbol: 股票代码，支持 000001.SZ / sz000001 / 000001
        freq: 目标周期
        sdt: 开始时间
        edt: 结束时间
        fq: 复权类型，本地数据按原样提供，本参数仅做签名兼容
        raw_bars: True 返回 list[RawBar]，False 返回 DataFrame
    """
    prefixed_code, exchange, numeric = _parse_symbol(symbol)

    freq_str = freq.value if isinstance(freq, czsc.Freq) else freq
    freq_dir = _freq_to_dir(freq) if freq_str in {"1分钟", "5分钟", "15分钟", "30分钟", "60分钟"} else None

    exact_path = _resolve_stock_path(freq_dir, exchange, numeric) if freq_dir else None
    if exact_path and exact_path.exists():
        df = _read_stock_bars(exact_path, exchange, numeric)
    else:
        base_path = _resolve_stock_path(_freq_to_dir("1分钟"), exchange, numeric)
        if not base_path or not base_path.exists():
            raise FileNotFoundError(f"找不到股票 {symbol} 的 1分钟数据文件")
        df = _read_stock_bars(base_path, exchange, numeric)
        df = cast(
            pd.DataFrame,
            czsc.resample_bars(df, target_freq=freq, raw_bars=False, base_freq="1分钟"),
        )

    df = _filter_by_date(df, sdt, edt)
    if df.empty:
        return [] if raw_bars else df

    if raw_bars:
        freq_enum = czsc.Freq(freq) if isinstance(freq, str) else freq
        return format_standard_kline(df, freq=freq_enum)
    return df


def _resolve_stock_path(freq_dir: str, exchange: str, numeric: str) -> Path | None:
    if exchange:
        return _STOCK_BASE_PATH / freq_dir / exchange / f"{exchange}{numeric}.parquet"
    for ex in _EXCHANGES:
        path = _STOCK_BASE_PATH / freq_dir / ex / f"{ex}{numeric}.parquet"
        if path.exists():
            return path
    return None


def _read_stock_bars(path: Path, exchange: str, numeric: str) -> pd.DataFrame:
    df = pl.read_parquet(str(path)).to_pandas()
    return _standardize_kline(df, exchange, numeric)
