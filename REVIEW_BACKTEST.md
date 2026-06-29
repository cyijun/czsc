# 回测问题记录

> 记录对 `feat/local-etf-stock-min-connectors` 分支回测脚本与报告的检查结果。

---

## 1. 交易次数显示为非整数

### 根因
在汇总阶段把 `trades` 也做了板块内平均，并统一格式化为 4 位小数。

### 位置
- `report/generate_backtest_report.py:60-61`
  ```python
  grouped = filtered.groupby(["sector", "strategy"])[METRICS].mean().reset_index()
  ```
  其中 `METRICS` 包含 `"trades"`。
- `report/generate_backtest_report.py:148-149`
  ```python
  data.append([f"{v:.4f}" if isinstance(v, float) else str(v) for v in row.values])
  ```
- `docs/examples/19g_sector_report.py:45` 有同样逻辑。

### 状态
✅ 已在 `fix/backtest-report-and-timeout` 分支修复。

### 修复方式
- `report/generate_backtest_report.py` / `docs/examples/19g_sector_report.py`：
  - `sector_summary` 与 `best_per_sector` 中对 `trades` 做 `round().astype(int)`；
  - `df_to_table` 中对 `trades` 列单独格式化为整数，其他浮点数仍保留 4 位小数。

---

## 2. 未来函数 / 同根 K 线成交

### 根因
Rust 执行引擎采用“当前 bar 收盘后出信号，同根 bar close 成交”的模型，属于 look-ahead bias。

### 位置
- `crates/czsc-trader/src/engine_v2/runtime/executor.rs:206-253`
- `crates/czsc-python/src/trader/generate.rs:89-98`
- `docs/examples/19d_daily_universe_3buy.py:89-90`
  - 用当前 bar close 作为成交价；
  - 用 `event.is_match(s)` 作为当前 bar 权重。
- `docs/examples/19d_daily_universe_3buy.py:98`
  - `df["n1b"] = df.groupby("symbol")["price"].pct_change().shift(-1).fillna(0)` 显式使用下一期收益。
- `_buy_and_hold_stats()`（line 174）也重复用了 `shift(-1)`。

### 受影响脚本
所有通过 `CzscStrategyBase.backtest()` 跑 Rust 引擎的 19 系列脚本：
- `19_local_minute_event_backtest.py`
- `19a_trend_filtered_3buy.py`
- `19b_multi_period_resonance.py`
- `19c_exit_comparison.py`
- `19e_combined_resonance_fixed20.py`
- `19f_sector_scanner.py`

### 诊断脚本
已添加 `scripts/compare_execution_lag.py`，可在不改 Rust 引擎的情况下，
把 `holds_df` 的成交价替换为下一根 bar 的 `open`/`close`，
对比三种执行方式的绩效差异（同 bar close / 延后 1 根 open / 延后 1 根 close）。

用法：
```bash
uv run --no-sync python scripts/compare_execution_lag.py
```

### 修复方向
- 严格方案：信号在当前 bar 收盘确认后，权重/开平仓操作延后 1 根 K 线，成交价用下一根 bar 的 `open` 或 `close`。
- 折中方案：保留当前 bar close 成交，但报告需明确标注为“理想化成交”，不代表实盘可复现。
- `19d` 应立即去掉 `shift(-1)` 并延后权重。

---

## 3. 固定持仓 K 线数（设计歧义，已回退）

### 说明
`Position` 超时平仓条件：

```rust
} else if bar_id - ev_bar_id > self.timeout {
```

`timeout=20` 时，需要 `bar_id - ev_bar_id > 20` 才会平仓，即实际持仓 21 根 K 线。

这可以有两种理解：

1. **bug**：注释说 timeout 是"最大允许持仓 K 线数量"，实际多持 1 根，与命名不符。
2. **设计歧义**：timeout 可能表示"开仓后经过 timeout 根 K 线才开始检查平仓"，即最少持仓 `timeout+1` 根。

由于缺少上游明确文档/测试确认这是 bug，且修改会影响现有回测结果的可比性，**已在 `fix/backtest-report-and-timeout` 分支回退此修改**，保持与上游行为一致。

### 状态
↩️ 已回退，`position.rs` 恢复为原始 `>` 判断。

### 建议
如果你希望 `fixed_20` 实际持仓恰好 20 根 K 线，可以在策略层把 `timeout=19` 作为 workaround，而不是改引擎。

---

## 4. 其他观察

- `19e` / `19f` 的 `get_bars()` 每次调用都重新 `set(get_etf_symbols())`，多标的扫描会重复读取 ETF parquet 的 symbol 列表，建议缓存。
- `holds_to_weight_df` 对重复 `dt/symbol` 的 weight 取 `mean`，多周期共振时可能把两个同向 position 的权重从 1.0 稀释成 0.5，需确认是否预期行为。
- `19f_sector_scanner.py` 的 baseline 用 `timeout=16*30` 作为“用笔向下平仓”的标记，逻辑正确但命名容易误导。
