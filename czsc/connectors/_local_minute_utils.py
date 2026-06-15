"""Shared utilities for local ETF and A-share minute data connectors."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

import czsc


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
