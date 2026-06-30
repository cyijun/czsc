# 本地 ETF / A 股分钟数据连接器设计

**日期**: 2026-06-15  
**范围**: `czsc/connectors/etf_min_connector.py`、`czsc/connectors/stock_min_connector.py`、`czsc/connectors/_local_minute_utils.py` 及对应测试。  
**状态**: 设计评审中

## 背景与目标

为 `/mnt/h/etf_min/etf_min_parquet_2000-2025` 与 `/mnt/h/stock_min/stk_min_parquet_2000-2025` 两个本地只读 parquet 数据集提供 CZSC 连接器，使用户可以像调用 `ts_connector.get_raw_bars` 一样读取本地分钟数据。

核心约束：
- **只读源数据**：所有代码不得修改 `/mnt/h/` 下的 parquet。
- **对齐现有接口**：`get_raw_bars(symbol, freq, sdt, edt, fq, raw_bars)` + `get_symbols(step)`。
- **优先复用项目依赖**：使用已声明的 `polars>=0.20.0` 做 lazy 查询，避免内存爆炸。

## 数据布局

### ETF 数据

路径：`/mnt/h/etf_min/etf_min_parquet_2000-2025/`

```
etf_1min.parquet   (~3.76 GB, 302M 行)
etf_5min.parquet   (~0.95 GB)
etf_15min.parquet  (~0.35 GB)
etf_30min.parquet  (~0.18 GB)
etf_60min.parquet  (~0.09 GB)
```

Schema:
- `datetime`: timestamp[ns]
- `code`: string，**已带交易所前缀**，如 `sh510050`、`sz159915`
- `exchange`: string，`sh` / `sz`
- `name`: string
- `open`/`high`/`low`/`close`: double
- `volume`: double
- `amount`: double

### A 股数据

路径：`/mnt/h/stock_min/stk_min_parquet_2000-2025/`

```
1min/
├── sz/sz000001.parquet
├── sh/sh000001.parquet
└── bj/...
5min/ ...
15min/ ...
30min/ ...
60min/ ...
```

Schema:
- `datetime`: timestamp[us]
- `code`: string，**6 位数字**，如 `000001`
- `exchange`: string，`sz` / `sh` / `bj`
- `open`/`high`/`low`/`close`: double
- `volume`: int64
- `amount`: double
- 以及 `change`、`pct_change`、`turnover`、`float_share`、`total_share`

## 设计决策

| 问题 | 决策 | 理由 |
|------|------|------|
| 模块组织 | 两个薄模块 + 一个共享工具文件 | 与 `ts_connector` / `local_data.py` 风格一致，用户说“分别做连接器”。 |
| 查询引擎 | Polars lazy (`scan_parquet` + `filter`) | 项目已依赖 polars；对 ETF 大文件可按 symbol 过滤后收集，避免全量加载。 |
| Symbol 输入 | 兼容三种：`510300.SH`、`sh510300`、`510300` | 用户要求兼容。 |
| Symbol 输出 | 统一为 `510300.SH` / `000001.SZ` | 与 Tushare connector 对齐。 |
| 周期处理 | 精确匹配优先，否则从 1min 重采样 | 本地已预计算 1/5/15/30/60min，优先用精确文件；缺失时回退到 1min 用 `czsc.resample_bars`。 |
| 缓存 | 第一版不做 | 用户明确先不做。 |
| 复权 `fq` | 从 `/mnt/h/fq_factor/<prefixed_code>.csv` 读取前/后复权因子，按交易日合并到 OHLC 与 `amount`，默认 `后复权` | 因子文件缺失时回退到未复权并警告；因子含非正值时过滤后再使用。 |

## 文件结构

```
czsc/connectors/
├── etf_min_connector.py       # ETF 入口：get_symbols / get_raw_bars
├── stock_min_connector.py     # A 股入口：get_symbols / get_raw_bars
└── _local_minute_utils.py     # 共享工具

tests/connectors/
├── test_etf_min_connector.py
└── test_stock_min_connector.py
```

## 接口契约

### ETF

```python
import czsc.connectors.etf_min_connector as emc

symbols = emc.get_symbols()  # list[str]，如 ["510300.SH", "159915.SZ", ...]
bars = emc.get_raw_bars("510300.SH", "5分钟", "20240101", "20240131", raw_bars=True)
```

### A 股

```python
import czsc.connectors.stock_min_connector as smc

symbols = smc.get_symbols(step="sz")  # 可选 all/sz/sh/bj
bars = smc.get_raw_bars("000001.SZ", "1分钟", "20240101", "20240131", raw_bars=True)
```

### `get_raw_bars` 签名

```python
def get_raw_bars(
    symbol: str,
    freq: str | czsc.Freq,
    sdt: str | datetime,
    edt: str | datetime,
    fq: str = "后复权",
    raw_bars: bool = True,
) -> list[czsc.RawBar] | pd.DataFrame:
    ...
```

## Symbol 解析

由 `_local_minute_utils._parse_symbol(symbol)` 统一处理：

| 输入 | 输出 `(exchange_prefixed_code, exchange, numeric_code)` |
|------|--------------------------------------------------------|
| `"510300.SH"` | `("sh510300", "sh", "510300")` |
| `"sh510300"` | `("sh510300", "sh", "510300")` |
| `"510300"` | `("510300", "", "510300")` |
| `"000001.SZ"` | `("sz000001", "sz", "000001")` |
| `"sz000001"` | `("sz000001", "sz", "000001")` |
| `"000001"` | `("000001", "", "000001")` |

- 带 `.` 的输入按 Tushare 风格解析。
- 带 `sh`/`sz`/`bj` 前缀的输入直接拆分。
- 纯数字 code 需要连接器内部做 best-effort 推断。

## 数据流

```
symbol + freq
  → _parse_symbol → (prefixed_code, exchange, numeric)
  → _resolve_parquet_path → parquet 文件路径
  → Polars lazy 读取 + 按 symbol 过滤
  → .collect().to_pandas()
  → _standardize_kline(df, exchange, numeric)
      - datetime → dt (datetime64[ns], tz-naive)
      - volume → vol
      - 构造 symbol 列 = f"{numeric}.{exchange.upper()}"
  → 按 sdt/edt 过滤
  → raw_bars=True  → czsc.format_standard_kline → list[RawBar]
    raw_bars=False → 返回标准 8 列 DataFrame
```

### ETF 过滤策略

```python
lf = pl.scan_parquet(path)
if exchange:
    lf = lf.filter(pl.col("code") == prefixed_code)
else:
    # 纯数字 code，尝试 sh/sz 两种可能
    lf = lf.filter((pl.col("code") == f"sh{numeric}") | (pl.col("code") == f"sz{numeric}"))
df = lf.collect().to_pandas()
# 从返回行推断真实 exchange，再统一输出 symbol
```

### A 股路径解析

```python
if exchange:
    candidates = [base / freq_dir / exchange / f"{exchange}{numeric}.parquet"]
else:
    candidates = [base / freq_dir / ex / f"{ex}{numeric}.parquet" for ex in ("sz", "sh", "bj")]

path = next((p for p in candidates if p.exists()), None)
```

### 周期回退

```python
freq_dir_map = {
    "1分钟": "1min",
    "5分钟": "5min",
    "15分钟": "15min",
    "30分钟": "30min",
    "60分钟": "60min",
}

exact_path = resolve(freq_dir)
if exact_path.exists():
    df = read_and_filter(exact_path)
else:
    df = read_and_filter("1min")
    df = czsc.resample_bars(df, target_freq=freq, raw_bars=False, base_freq="1分钟")
```

## 列标准化输出

无论 ETF 还是 A 股，最终输出统一为：

```python
["symbol", "dt", "open", "close", "high", "low", "vol", "amount"]
```

其中：
- `dt`: `datetime64[ns]`，tz-naive
- `symbol`: 字符串，如 `"510300.SH"`
- 其余列：`float64`

## 错误处理

- **Symbol 格式错误**：`ValueError`，提示期望格式示例。
- **找不到 parquet 文件**：`FileNotFoundError`，消息包含尝试过的路径。
- **请求频率不在 1/5/15/30/60 分钟且没有 1min 文件**：`ValueError`。
- **ETF 大文件中无该 symbol 数据**：返回空列表 / 空 DataFrame，不抛异常。
- **Polars 收集失败**：向上抛出原始异常，消息附带文件路径。

## 测试策略

测试必须**只读** `/mnt/h/` 数据：

1. **Smoke test**：读取已知标的，断言返回非空。
   - ETF: `510300.SH`，5 分钟，`2024-01-01` 到 `2024-01-31`
   - A 股: `000001.SZ`，1 分钟，同上
2. **Symbol 兼容性**：同一标的用 `510300.SH`、`sh510300`、`510300` 三种写法调用，结果行数/时间范围一致。
3. **频率回退**：请求 `2分钟`（无精确 parquet）能从 1min 重采样返回数据。
4. **`get_symbols`**：返回列表包含测试标的。
5. **raw_bars=False**：返回 DataFrame，schema 符合标准 8 列。

## 非目标

- **不写缓存**：第一版不做 `DiskCache`。
- **不做复权计算**：`fq` 仅做签名兼容。
- **不修改源数据**：所有写操作限定在 `~/.czsc/` 或项目目录内。
- **不支持日/周/月/季/年线**：数据集仅含分钟数据。

## 风险与后续优化

- ETF 1min 文件 3.76 GB，Polars lazy 过滤单个 symbol 虽然快，但首次扫描仍可能耗时。若后续性能不足，可在 `~/.czsc/` 下增加按 symbol 分片的缓存（需用户后续确认）。
- A 股按 `sz/sh/bj` 目录组织，纯数字 code 推断需要文件系统探测；未来若目录结构变化，需同步更新路径解析。
