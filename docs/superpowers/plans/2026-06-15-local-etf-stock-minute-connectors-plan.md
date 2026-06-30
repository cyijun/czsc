# 本地 ETF / A 股分钟数据连接器实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `czsc/connectors/` 下实现两个本地只读分钟数据连接器（ETF 与 A 股），并配套测试。

**Architecture:** 两个薄模块复用同一个 `_local_minute_utils.py` 工具层；工具层负责 symbol 解析、周期映射、列标准化；连接器层负责 parquet 路径解析、Polars 读取/过滤、频率回退、输出转换。

**Tech Stack:** Python 3.12, Polars 1.41, pandas, CZSC (Rust/PyO3), pytest

---

## 前置检查

当前已在分支 `feat/local-etf-stock-min-connectors`，设计文档位于 `docs/superpowers/specs/2026-06-15-local-etf-stock-minute-connectors-design.md`。

源数据路径（只读）：
- `/mnt/h/etf_min/etf_min_parquet_2000-2025`
- `/mnt/h/stock_min/stk_min_parquet_2000-2025`

---

## Task 1: 共享工具模块 `_local_minute_utils.py`

**Files:**
- Create: `czsc/connectors/_local_minute_utils.py`
- Test: `tests/connectors/test_local_minute_utils.py`

### Step 1: 编写 `_parse_symbol` 测试

```python
import pytest
from czsc.connectors._local_minute_utils import _parse_symbol


def test_parse_symbol_tushare():
    assert _parse_symbol("510300.SH") == ("sh510300", "sh", "510300")
    assert _parse_symbol("000001.SZ") == ("sz000001", "sz", "000001")


def test_parse_symbol_prefixed():
    assert _parse_symbol("sh510300") == ("sh510300", "sh", "510300")
    assert _parse_symbol("sz000001") == ("sz000001", "sz", "000001")


def test_parse_symbol_plain():
    assert _parse_symbol("510300") == ("510300", "", "510300")
    assert _parse_symbol("000001") == ("000001", "", "000001")
```

Run: `uv run --no-sync pytest tests/connectors/test_local_minute_utils.py -v`
Expected: FAIL with `_parse_symbol` not defined.

### Step 2: 实现 `_parse_symbol`

```python
"""Shared utilities for local ETF and A-share minute data connectors."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


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
```

Run: `uv run --no-sync pytest tests/connectors/test_local_minute_utils.py -v`
Expected: PASS

### Step 3: 编写 `_freq_to_dir` 测试

```python
import czsc
from czsc.connectors._local_minute_utils import _freq_to_dir


def test_freq_to_dir_string():
    assert _freq_to_dir("1分钟") == "1min"
    assert _freq_to_dir("5分钟") == "5min"
    assert _freq_to_dir("60分钟") == "60min"


def test_freq_to_dir_enum():
    assert _freq_to_dir(czsc.Freq.F5) == "5min"


def test_freq_to_dir_unsupported():
    with pytest.raises(ValueError):
        _freq_to_dir("日线")
```

Run: `uv run --no-sync pytest tests/connectors/test_local_minute_utils.py::test_freq_to_dir_string -v`
Expected: FAIL

### Step 4: 实现 `_freq_to_dir`

Add to `czsc/connectors/_local_minute_utils.py`:

```python
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
```

Run: `uv run --no-sync pytest tests/connectors/test_local_minute_utils.py -v`
Expected: PASS

### Step 5: 编写 `_standardize_kline` 与 `_filter_by_date` 测试

```python
import pandas as pd
from czsc.connectors._local_minute_utils import _standardize_kline, _filter_by_date


def test_standardize_kline():
    df = pd.DataFrame({
        "datetime": pd.to_datetime(["2024-01-01 09:31:00", "2024-01-01 09:32:00"]),
        "open": [1.0, 1.1],
        "close": [2.0, 2.1],
        "high": [3.0, 3.1],
        "low": [0.5, 0.6],
        "volume": [100, 200],
        "amount": [1000.0, 2000.0],
    })
    out = _standardize_kline(df, "sh", "510300")
    assert list(out.columns) == ["symbol", "dt", "open", "close", "high", "low", "vol", "amount"]
    assert out["symbol"].tolist() == ["510300.SH", "510300.SH"]
    assert out["dt"].dtype == "datetime64[ns]"


def test_standardize_kline_empty():
    out = _standardize_kline(pd.DataFrame(), "sh", "510300")
    assert list(out.columns) == ["symbol", "dt", "open", "close", "high", "low", "vol", "amount"]
    assert len(out) == 0


def test_filter_by_date():
    df = pd.DataFrame({
        "dt": pd.to_datetime(["2024-01-01", "2024-01-15", "2024-02-01"]),
        "close": [1.0, 2.0, 3.0],
    })
    out = _filter_by_date(df, "2024-01-01", "2024-01-31")
    assert len(out) == 2
    assert out["dt"].iloc[-1] == pd.Timestamp("2024-01-15")
```

Run: `uv run --no-sync pytest tests/connectors/test_local_minute_utils.py -v`
Expected: FAIL

### Step 6: 实现 `_standardize_kline` 与 `_filter_by_date`

Add to `czsc/connectors/_local_minute_utils.py`:

```python
import czsc


def _standardize_kline(
    df: pd.DataFrame,
    exchange: str,
    numeric: str,
) -> pd.DataFrame:
    """Convert raw parquet columns to CZSC standard 8-column layout."""
    if df.empty:
        return pd.DataFrame(
            columns=["symbol", "dt", "open", "close", "high", "low", "vol", "amount"]
        )

    out = pd.DataFrame()
    out["dt"] = (
        pd.to_datetime(df["datetime"])
        .dt.tz_localize(None)
        .astype("datetime64[ns]")
    )
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
        out[["symbol", "dt", "open", "close", "high", "low", "vol", "amount"]]
        .sort_values("dt")
        .reset_index(drop=True)
    )


def _filter_by_date(
    df: pd.DataFrame,
    sdt: str | datetime,
    edt: str | datetime,
) -> pd.DataFrame:
    sdt = pd.to_datetime(sdt)
    edt = pd.to_datetime(edt)
    return df[(df["dt"] >= sdt) & (df["dt"] <= edt)].reset_index(drop=True)
```

Run: `uv run --no-sync pytest tests/connectors/test_local_minute_utils.py -v`
Expected: PASS

### Step 7: Commit

```bash
git add czsc/connectors/_local_minute_utils.py tests/connectors/test_local_minute_utils.py
git commit -m "$(cat <<'EOF'
feat(connectors): add shared utilities for local minute data connectors

- symbol parser supporting Tushare, prefixed, and plain formats
- frequency-to-directory mapping
- kline standardization and date filtering helpers

Generated with [Claude Code](https://claude.ai/claude-code)
via [Happy](https://happy.engineering)

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Happy <yesreply@happy.engineering>
EOF
)"
```

---

## Task 2: ETF 连接器 `etf_min_connector.py`

**Files:**
- Create: `czsc/connectors/etf_min_connector.py`
- Test: `tests/connectors/test_etf_min_connector.py`

### Step 1: 编写 ETF 测试

```python
import os
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
```

Run: `uv run --no-sync pytest tests/connectors/test_etf_min_connector.py -v`
Expected: FAIL with module not found.

### Step 2: 实现 `etf_min_connector.py`

```python
"""ETF minute data connector for local parquet dataset."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

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

_ETF_BASE_PATH = Path(
    os.environ.get("CZSC_ETF_MIN_PATH", "/mnt/h/etf_min/etf_min_parquet_2000-2025")
)


def get_symbols() -> list[str]:
    """Return list of available ETF symbols in Tushare style."""
    path = _ETF_BASE_PATH / "etf_1min.parquet"
    if not path.exists():
        raise FileNotFoundError(f"ETF 数据文件不存在: {path}")

    codes = pl.scan_parquet(str(path)).select(["code", "exchange"]).unique().collect()

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
        freq: 目标周期，支持 CZSC 中文周期字符串或 Freq 枚举
        sdt: 开始时间
        edt: 结束时间
        fq: 复权类型，支持 ``"前复权"``、``"后复权"``、``"不复权"``；默认 ``"后复权"``。
            从 ``/mnt/h/fq_factor/<prefixed_code>.csv`` 读取复权因子，按交易日合并到
            OHLC 与成交额；因子文件缺失时回退到未复权并警告。
        raw_bars: True 返回 list[RawBar]，False 返回 DataFrame
    """
    prefixed_code, exchange, numeric = _parse_symbol(symbol)
    freq_dir = _freq_to_dir(freq)

    exact_path = _ETF_BASE_PATH / f"etf_{freq_dir}.parquet"
    if exact_path.exists():
        df = _read_etf_bars(exact_path, prefixed_code, exchange, numeric)
    else:
        base_path = _ETF_BASE_PATH / "etf_1min.parquet"
        if not base_path.exists():
            raise FileNotFoundError(f"找不到 ETF 1分钟数据文件: {base_path}")
        df = _read_etf_bars(base_path, prefixed_code, exchange, numeric)
        df = czsc.resample_bars(df, target_freq=freq, raw_bars=False, base_freq="1分钟")

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
        lf = lf.filter(
            (pl.col("code") == f"sh{numeric}") | (pl.col("code") == f"sz{numeric}")
        )
    df = lf.collect().to_pandas()
    return _standardize_kline(df, exchange, numeric)
```

Run: `uv run --no-sync pytest tests/connectors/test_etf_min_connector.py -v`
Expected: PASS (if data exists).

### Step 3: Commit

```bash
git add czsc/connectors/etf_min_connector.py tests/connectors/test_etf_min_connector.py
git commit -m "$(cat <<'EOF'
feat(connectors): add ETF local minute data connector

- read from /mnt/h/etf_min/etf_min_parquet_2000-2025
- polars lazy filter by code/exchange
- exact freq match with 1min resample fallback

Generated with [Claude Code](https://claude.ai/claude-code)
via [Happy](https://happy.engineering)

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Happy <yesreply@happy.engineering>
EOF
)"
```

---

## Task 3: A 股连接器 `stock_min_connector.py`

**Files:**
- Create: `czsc/connectors/stock_min_connector.py`
- Test: `tests/connectors/test_stock_min_connector.py`

### Step 1: 编写 A 股测试

```python
from pathlib import Path

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
    assert list(df.columns) == ["symbol", "dt", "open", "close", "high", "low", "vol", "amount"]
    assert len(df) > 0


def test_stock_resample_fallback():
    bars = smc.get_raw_bars("000001.SZ", "2分钟", "20240101", "20240131")
    assert len(bars) > 0
    assert bars[0].freq == czsc.Freq.F2
```

Run: `uv run --no-sync pytest tests/connectors/test_stock_min_connector.py -v`
Expected: FAIL with module not found.

### Step 2: 实现 `stock_min_connector.py`

```python
"""A-share minute data connector for local parquet dataset."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

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

_STOCK_BASE_PATH = Path(
    os.environ.get("CZSC_STOCK_MIN_PATH", "/mnt/h/stock_min/stk_min_parquet_2000-2025")
)
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
        fq: 复权类型，支持 ``"前复权"``、``"后复权"``、``"不复权"``；默认 ``"后复权"``。
            从 ``/mnt/h/fq_factor/<prefixed_code>.csv`` 读取复权因子，按交易日合并到
            OHLC 与成交额；因子文件缺失时回退到未复权并警告。
        raw_bars: True 返回 list[RawBar]，False 返回 DataFrame
    """
    prefixed_code, exchange, numeric = _parse_symbol(symbol)
    freq_dir = _freq_to_dir(freq)

    exact_path = _resolve_stock_path(freq_dir, exchange, numeric)
    if exact_path and exact_path.exists():
        df = _read_stock_bars(exact_path, exchange, numeric)
    else:
        base_path = _resolve_stock_path(_freq_to_dir("1分钟"), exchange, numeric)
        if not base_path or not base_path.exists():
            raise FileNotFoundError(f"找不到股票 {symbol} 的 1分钟数据文件")
        df = _read_stock_bars(base_path, exchange, numeric)
        df = czsc.resample_bars(df, target_freq=freq, raw_bars=False, base_freq="1分钟")

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
```

Run: `uv run --no-sync pytest tests/connectors/test_stock_min_connector.py -v`
Expected: PASS (if data exists).

### Step 3: Commit

```bash
git add czsc/connectors/stock_min_connector.py tests/connectors/test_stock_min_connector.py
git commit -m "$(cat <<'EOF'
feat(connectors): add A-share local minute data connector

- read from /mnt/h/stock_min/stk_min_parquet_2000-2025
- per-symbol parquet files organized by exchange
- exact freq match with 1min resample fallback

Generated with [Claude Code](https://claude.ai/claude-code)
via [Happy](https://happy.engineering)

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Happy <yesreply@happy.engineering>
EOF
)"
```

---

## Task 4: 代码质量与集成检查

### Step 1: 运行 ruff 格式化和检查

```bash
uv run --no-sync ruff format czsc/connectors/_local_minute_utils.py czsc/connectors/etf_min_connector.py czsc/connectors/stock_min_connector.py tests/connectors/
uv run --no-sync ruff check czsc/connectors/_local_minute_utils.py czsc/connectors/etf_min_connector.py czsc/connectors/stock_min_connector.py tests/connectors/
```

Expected: no errors.

### Step 2: 运行全部新增测试

```bash
uv run --no-sync pytest tests/connectors/ -v
```

Expected: all PASS (skipped if local data missing).

### Step 3: Commit 格式修复

```bash
git add -A
git commit -m "$(cat <<'EOF'
style(connectors): format new local minute connector modules

Generated with [Claude Code](https://claude.ai/claude-code)
via [Happy](https://happy.engineering)

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Happy <yesreply@happy.engineering>
EOF
)"
```

---

## 自检清单

- [x] Spec coverage: symbol 兼容、精确周期/重采样回退、Polars 读取、`get_symbols`、只读约束、无缓存、不复权均有对应任务。
- [x] Placeholder scan: 无 TBD/TODO/空实现。
- [x] Type consistency: `_parse_symbol` / `_freq_to_dir` / `_standardize_kline` 签名在全计划一致。
- [x] File paths: 全部使用绝对路径或环境变量可覆盖的默认值。
- [x] 测试策略: 所有测试在未找到本地数据时 `skipif`，CI 安全。

---

## 执行方式选择

**Plan complete and saved to `docs/superpowers/plans/2026-06-15-local-etf-stock-minute-connectors-plan.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using `executing-plans`, batch execution with checkpoints

**Which approach?**
