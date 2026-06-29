"""qmt-bridge connector 测试。

这些测试依赖可访问的 qmt-bridge 服务端（默认 http://qmt-vm:18888）。
若服务不可达，测试会自动跳过。
"""

import pandas as pd
import pytest
import requests

import czsc
import czsc.connectors.qmt_bridge_connector as qbc

QMT_BRIDGE_URL = getattr(qbc, "QMT_BRIDGE_URL", "http://qmt-vm:18888")


def _service_available() -> bool:
    """检查 qmt-bridge 服务是否可达。"""
    try:
        session = requests.Session()
        session.trust_env = False
        resp = session.get(f"{QMT_BRIDGE_URL.rstrip('/')}/api/etf/list", timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _service_available(), reason="qmt-bridge 服务不可达")


def test_get_symbols_etf():
    symbols = qbc.get_symbols("etf")
    assert isinstance(symbols, list)
    assert len(symbols) > 0
    assert all(isinstance(s, str) for s in symbols)


def test_get_raw_bars_daily():
    bars = qbc.get_raw_bars("000001.SZ", "日线", "20250101", "20250131")
    assert len(bars) > 0
    assert isinstance(bars[0], czsc.RawBar)
    assert bars[0].freq == czsc.Freq.D


def test_get_raw_bars_minute():
    bars = qbc.get_raw_bars("000001.SZ", "5分钟", "20250102", "20250103")
    assert isinstance(bars, list)
    # 分钟数据可能为空（取决于服务端本地缓存），仅做类型断言
    if bars:
        assert isinstance(bars[0], czsc.RawBar)
        assert bars[0].freq == czsc.Freq.F5


def test_get_raw_bars_dataframe():
    df = qbc.get_raw_bars("000001.SZ", "日线", "20250101", "20250131", raw_bars=False)
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["dt", "symbol", "open", "high", "low", "close", "vol", "amount"]


def test_get_raw_bars_fq_mapping():
    """测试不同复权类型映射不报错。"""
    for fq in ["前复权", "后复权", "不复权"]:
        bars = qbc.get_raw_bars("000001.SZ", "日线", "20250101", "20250131", fq=fq)
        assert isinstance(bars, list)


def test_get_raw_bars_etf():
    """ETF 行情可能为空（取决于服务端数据），仅验证接口可用。"""
    symbols = qbc.get_symbols("etf")
    if not symbols:
        pytest.skip("无 ETF 代码")
    symbol = "510300.SH" if "510300.SH" in symbols else symbols[0]
    bars = qbc.get_raw_bars(symbol, "日线", "20250101", "20250131")
    assert isinstance(bars, list)
