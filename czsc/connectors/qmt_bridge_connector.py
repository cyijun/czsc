"""QMT Bridge 数据连接器。

通过 HTTP 调用 qmt-bridge 服务端（默认 http://qmt-vm:18888）暴露的行情接口，
为 czsc 提供标准化的 ``get_symbols`` 和 ``get_raw_bars`` 数据获取能力。

author: zengbin93
email: zeng_bin8888@163.com
create_dt: 2025/06/29
describe: QMT Bridge 数据源
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any

import pandas as pd
import requests

import czsc
from czsc._format_standard_kline import format_standard_kline

# qmt-bridge 服务端地址，可通过环境变量覆盖
QMT_BRIDGE_URL = os.environ.get("CZSC_QMT_BRIDGE_URL", "http://qmt-vm:18888")

# 是否信任环境代理设置。默认为 False，避免 macOS 等系统代理配置干扰局域网直连。
_QMT_BRIDGE_TRUST_PROXY = os.environ.get("CZSC_QMT_BRIDGE_TRUST_PROXY", "false").lower() in ("1", "true", "yes")

# czsc 周期 -> qmt-bridge 周期
_FREQ_MAP: dict[str, str] = {
    "1分钟": "1m",
    "5分钟": "5m",
    "15分钟": "15m",
    "30分钟": "30m",
    "60分钟": "1h",
    "日线": "1d",
    "周线": "1w",
    "月线": "1mon",
}

# xtquant 中 >=5m 的周期由 5m 数据合成，下载时需要先下载 5m 基础数据
_FREQ_NEEDS_5M_BASE: set[str] = {"15m", "30m", "1h"}

# czsc 复权类型 -> qmt-bridge dividend_type
_FQ_MAP: dict[str, str] = {
    "前复权": "front",
    "后复权": "back",
    "等比前复权": "front_ratio",
    "等比后复权": "back_ratio",
    "不复权": "none",
}


def _get_session() -> requests.Session:
    """获取配置好的 requests Session。

    默认禁用系统环境代理，避免 macOS 等系统代理配置干扰对 qmt-vm 的局域网直连。
    如需启用环境代理，设置环境变量 ``CZSC_QMT_BRIDGE_TRUST_PROXY=true``。
    """
    session = requests.Session()
    session.trust_env = _QMT_BRIDGE_TRUST_PROXY
    return session


def _request(method: str, path: str, **params: Any) -> dict[str, Any]:
    """向 qmt-bridge 发起 HTTP 请求并返回 data 字段。"""
    url = f"{QMT_BRIDGE_URL.rstrip('/')}{path}"
    session = _get_session()
    try:
        if method.upper() == "GET":
            resp = session.get(url, params=params, timeout=30)
        else:
            resp = session.post(url, json=params, timeout=30)
        resp.raise_for_status()
        result = resp.json()
    except requests.RequestException as e:
        raise ConnectionError(f"请求 qmt-bridge 失败: {url}, 错误: {e}") from e
    except ValueError as e:
        raise ValueError(f"qmt-bridge 返回非 JSON 响应: {url}, 错误: {e}") from e

    if isinstance(result, dict) and "data" in result:
        return result["data"]
    return result


def _download_history_data(stock_list: list[str], period: str, start_time: str, end_time: str) -> dict[str, Any]:
    """触发 qmt-bridge 服务端下载历史 K 线数据到本地。

    该接口为异步操作，服务端在后台执行下载任务。
    """
    return _request(
        "POST",
        "/api/download/history_data2",
        stock_list=stock_list,
        period=period,
        start_time=start_time,
        end_time=end_time,
    )


def _normalize_kline(records: list[dict[str, Any]], symbol: str) -> pd.DataFrame:
    """将 qmt-bridge 返回的 K 线记录标准化为 czsc 标准列。"""
    if not records:
        return pd.DataFrame(columns=["dt", "symbol", "open", "high", "low", "close", "vol", "amount"])

    df = pd.DataFrame(records)

    # 时间列：优先使用 ``index``（本地时间字符串）。qmt-bridge 的 index 字段
    # 由 xtquant DataFrame 索引生成，为本地交易时间；日线为 20250627，
    # 分钟线为 20250627143000，需根据长度选择格式。
    if "index" in df.columns:
        index_len = df["index"].astype(str).str.len().iloc[0]
        if index_len == 8:
            df["dt"] = pd.to_datetime(df["index"], format="%Y%m%d", errors="coerce")
        elif index_len == 14:
            df["dt"] = pd.to_datetime(df["index"], format="%Y%m%d%H%M%S", errors="coerce")
        else:
            df["dt"] = pd.to_datetime(df["index"], errors="coerce")
    elif "time" in df.columns:
        df["dt"] = pd.to_datetime(df["time"], unit="ms", utc=True).dt.tz_convert("Asia/Shanghai").dt.tz_localize(None)
    elif "date" in df.columns:
        df["dt"] = pd.to_datetime(df["date"])
    else:
        raise ValueError("qmt-bridge 返回的 K 线数据中未找到时间列（time/date/index）")

    if df["dt"].isna().all():
        raise ValueError("qmt-bridge 返回的 K 线时间解析失败")

    # 成交量字段兼容：qmt-bridge 返回 ``volume``，czsc 使用 ``vol``
    if "volume" in df.columns and "vol" not in df.columns:
        df["vol"] = df["volume"]

    # 补充 symbol 列
    df["symbol"] = symbol

    # 确保 amount 存在（某些场景可能缺失）
    if "amount" not in df.columns:
        df["amount"] = 0.0

    # 标准化列类型
    for col in ["open", "high", "low", "close", "vol", "amount"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df[["dt", "symbol", "open", "high", "low", "close", "vol", "amount"]].copy()


def get_symbols(asset: str = "etf") -> list[str]:
    """获取标的代码列表。

    :param asset: 资产类型，当前仅支持 ``"etf"``
    :return: 标的代码列表
    """
    asset = asset.lower()
    if asset == "etf":
        data = _request("GET", "/api/etf/list")
        return list(data.get("stocks", []))
    raise ValueError(f"不支持的 asset 类型: {asset}，当前仅支持 etf")


def get_raw_bars(
    symbol: str,
    freq: czsc.Freq | str,
    sdt: str | datetime,
    edt: str | datetime,
    fq: str = "前复权",
    raw_bars: bool = True,
    use_local: bool = False,
) -> list[czsc.RawBar] | pd.DataFrame:
    """从 qmt-bridge 获取标准化 K 线数据。

    :param symbol: 标的代码，如 ``"510300.SH"``
    :param freq: 周期，支持 ``"1分钟"`` / ``"5分钟"`` / ... / ``"日线"`` 等
    :param sdt: 开始时间
    :param edt: 结束时间
    :param fq: 复权类型，可选 ``"前复权"`` / ``"后复权"`` / ``"等比前复权"`` / ``"等比后复权"`` / ``"不复权"``
    :param raw_bars: True 返回 ``list[RawBar]``，False 返回 ``pd.DataFrame``
    :param use_local: 是否使用 ``/api/market/local_data``（仅读取本地缓存，不触发网络拉取）
    :return: RawBar 列表或标准化后的 DataFrame
    """
    freq_str = freq.value if isinstance(freq, czsc.Freq) else str(freq)
    period = _FREQ_MAP.get(freq_str)
    if period is None:
        raise ValueError(f"不支持的周期: {freq_str}，支持的周期为: {list(_FREQ_MAP.keys())}")

    dividend_type = _FQ_MAP.get(fq, "none")
    start_time = pd.to_datetime(sdt).strftime("%Y%m%d")
    end_time = pd.to_datetime(edt).strftime("%Y%m%d")

    endpoint = "/api/market/local_data" if use_local else "/api/market/market_data_ex"
    data = _request(
        "GET",
        endpoint,
        stocks=symbol,
        period=period,
        start_time=start_time,
        end_time=end_time,
        count=-1,
        dividend_type=dividend_type,
        fill_data=True,
    )

    records = data.get(symbol, []) if isinstance(data, dict) else []

    # xtquant 中 15m/30m/1h 等周期由 5m 数据合成，若本地无 5m 基础数据则查询为空。
    # 当目标周期需要 5m 基础数据且当前未返回数据时，尝试触发 5m 数据下载后重试。
    if not records and period in _FREQ_NEEDS_5M_BASE and not use_local:
        try:
            _download_history_data([symbol], "5m", start_time, end_time)
            # 等待服务端后台下载完成，qmt-bridge 默认单只 5m 超时约 10 秒
            time.sleep(12)
            data = _request(
                "GET",
                endpoint,
                stocks=symbol,
                period=period,
                start_time=start_time,
                end_time=end_time,
                count=-1,
                dividend_type=dividend_type,
                fill_data=True,
            )
            records = data.get(symbol, []) if isinstance(data, dict) else []
        except Exception:
            pass

    df = _normalize_kline(records, symbol)

    # 按时间范围过滤（qmt-bridge 可能返回边界外数据）
    sdt_dt = pd.to_datetime(sdt)
    edt_dt = pd.to_datetime(edt)
    df = df[(df["dt"] >= sdt_dt) & (df["dt"] <= edt_dt)].copy().reset_index(drop=True)

    if df.empty:
        return [] if raw_bars else df

    if raw_bars:
        freq_enum = czsc.Freq(freq) if isinstance(freq, str) else freq
        return format_standard_kline(df, freq=freq_enum)
    return df
