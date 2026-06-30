"""Shared utilities for local ETF and A-share minute data connectors."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import loguru
import pandas as pd

import czsc

logger = loguru.logger

_FQ_FACTOR_BASE_PATH = Path(os.environ.get("CZSC_FQ_FACTOR_PATH", "/mnt/h/fq_factor"))


def _parse_symbol(symbol: str) -> tuple[str, str, str]:
    """Parse symbol into (prefixed_code, exchange, numeric_code).

    Accepts Tushare style (510300.SH), prefixed style (sh510300),
    or plain numeric code (510300).
    """
    symbol = symbol.strip().upper()
    if "." in symbol:
        numeric, exchange = symbol.split(".", 1)
        exchange = exchange.lower()
        return f"{exchange}{numeric}", exchange, numeric

    lower = symbol.lower()
    if lower.startswith(("sh", "sz", "bj")):
        exchange = lower[:2]
        numeric = symbol[2:]
        return lower, exchange, numeric

    return symbol, "", symbol


_FREQ_DIR_MAP: dict[str, str] = {
    "1分钟": "1min",
    "5分钟": "5min",
    "15分钟": "15min",
    "30分钟": "30min",
    "60分钟": "60min",
}


def _freq_to_dir(freq: czsc.Freq | str) -> str:
    """Map CZSC frequency to directory/file suffix name."""
    if isinstance(freq, czsc.Freq):
        freq = freq.value
    if freq not in _FREQ_DIR_MAP:
        raise ValueError(f"不支持的频率: {freq}，仅支持 {list(_FREQ_DIR_MAP.keys())}")
    return _FREQ_DIR_MAP[freq]


def _standardize_kline(
    df: pd.DataFrame,
    exchange: str,
    numeric: str,
) -> pd.DataFrame:
    """Convert raw parquet columns to CZSC standard 8-column layout."""
    if df.empty:
        return pd.DataFrame(columns=["symbol", "dt", "open", "close", "high", "low", "vol", "amount"])

    out = pd.DataFrame()
    out["dt"] = pd.to_datetime(df["datetime"]).dt.tz_localize(None).astype("datetime64[ns]")
    out["open"] = df["open"].astype("float64")
    out["close"] = df["close"].astype("float64")
    out["high"] = df["high"].astype("float64")
    out["low"] = df["low"].astype("float64")
    out["vol"] = df["volume"].astype("float64")
    out["amount"] = df["amount"].astype("float64")

    if not exchange and "exchange" in df.columns and len(df["exchange"].unique()) == 1:
        exchange = str(df["exchange"].iloc[0]).lower()

    out["symbol"] = f"{numeric}.{exchange.upper()}"

    return (
        out[["symbol", "dt", "open", "close", "high", "low", "vol", "amount"]].sort_values("dt").reset_index(drop=True)
    )


def _filter_by_date(
    df: pd.DataFrame,
    sdt: str | datetime,
    edt: str | datetime,
) -> pd.DataFrame:
    sdt = pd.to_datetime(sdt)
    edt = pd.to_datetime(edt)
    return df[(df["dt"] >= sdt) & (df["dt"] <= edt)].reset_index(drop=True)


def _load_fq_factor(prefixed_code: str) -> pd.DataFrame | None:
    """Load forward/backward adjustment factors for a prefixed symbol.

    The factor CSV is expected at ``<CZSC_FQ_FACTOR_PATH>/<prefixed_code>.csv``
    with columns ``日期,前复权因子,后复权因子``.

    :param prefixed_code: e.g. ``sh510300`` or ``sz000001``
    :return: DataFrame with ``dt`` plus factor columns, or None if file missing.
    """
    path = _FQ_FACTOR_BASE_PATH / f"{prefixed_code}.csv"
    if not path.exists():
        return None

    df = pd.read_csv(path, dtype={"日期": str})
    df = df.rename(columns={"日期": "dt", "前复权因子": "qfq", "后复权因子": "hfq"})
    df["dt"] = pd.to_datetime(df["dt"])
    return df[["dt", "qfq", "hfq"]]


def _apply_fq(df: pd.DataFrame, prefixed_code: str, fq: str = "后复权") -> pd.DataFrame:
    """Apply forward/backward adjustment to OHLC and amount by trade date.

    The factor file is joined on the date part of ``dt``.  Volume is kept
    unchanged.  If the factor file is missing, the DataFrame is returned
    unchanged and a warning is logged.

    When ``prefixed_code`` is a plain numeric code (e.g. ``"510300"``), the
    actual exchange prefix is inferred from ``df["symbol"]``.

    :param df: standard 8-column DataFrame from ``_standardize_kline``
    :param prefixed_code: e.g. ``sh510300``
    :param fq: ``"前复权"``, ``"后复权"`` or ``"不复权"``
    :return: adjusted DataFrame
    """
    if fq == "不复权":
        return df

    if fq not in {"前复权", "后复权"}:
        raise ValueError(f"不支持的复权类型: {fq!r}，仅支持 前复权/后复权/不复权")

    # If the caller passed a plain numeric code, infer exchange from df["symbol"].
    if not prefixed_code.lower().startswith(("sh", "sz", "bj")):
        symbols = df["symbol"].unique()
        if len(symbols) == 1 and "." in symbols[0]:
            numeric, exchange = symbols[0].split(".", 1)
            prefixed_code = f"{exchange.lower()}{numeric}"

    factor_df = _load_fq_factor(prefixed_code)
    if factor_df is None:
        logger.warning(f"未找到 {prefixed_code} 的复权因子文件，返回未复权数据")
        return df

    factor_col = "qfq" if fq == "前复权" else "hfq"

    # Drop non-positive factors (e.g. historical data quirks) before merging.
    factor_df = factor_df[factor_df[factor_col] > 0].copy()
    if factor_df.empty:
        logger.warning(f"{prefixed_code} 的 {fq} 因子无有效正值，返回未复权数据")
        return df

    out = df.copy()
    out["trade_date"] = out["dt"].dt.normalize()
    factor_df["trade_date"] = factor_df["dt"].dt.normalize()

    out = out.merge(factor_df[["trade_date", factor_col]], on="trade_date", how="left")
    # Forward/backward fill so that intraday minutes and edge dates get a factor.
    out[factor_col] = out[factor_col].ffill().bfill()

    if out[factor_col].isna().any():
        raise ValueError(f"{prefixed_code} 的复权因子存在缺失，无法完成复权")

    factor = out[factor_col].astype(float)
    for col in ("open", "high", "low", "close"):
        out[col] = out[col] * factor
    out["amount"] = out["amount"] * factor

    return out.drop(columns=["trade_date", factor_col])
