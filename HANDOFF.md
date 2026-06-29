# Handoff：回测修复分支交接文档

> 本文档说明如何在另一台机器（有数据的回测机器）上接手并验证 `fix/backtest-report-and-timeout` 分支。

---

## 1. 分支信息

- **源分支**：`feat/local-etf-stock-min-connectors`（你的 fork）
- **修复分支**：`fix/backtest-report-and-timeout`
- **仓库地址**：`https://github.com/cyijun/czsc`

```bash
# 拉取并切换到修复分支
git fetch origin
git checkout origin/fix/backtest-report-and-timeout -b fix/backtest-report-and-timeout
```

---

## 2. 已修复的问题

### 2.1 交易次数显示为非整数

- **文件**：`report/generate_backtest_report.py`、`docs/examples/19g_sector_report.py`
- **修复**：汇总/展示时对 `trades` 列做 `round().astype(int)`，PDF 表里不再显示 `12.5000`。

### 2.2 固定持仓 K 线数（设计歧义，未修改）

- **文件**：`crates/czsc-core/src/objects/position.rs`
- **状态**：已回退，保持上游原始行为。
- **说明**：`timeout=20` 时实际持仓 21 根 K 线，可能是设计歧义（"最大持仓数" vs "经过 timeout 根后再检查"）。由于无法确认上游意图，为避免破坏回测结果可比性，未改动此逻辑。
- **workaround**：如需 `fixed_20` 实际持仓 20 根，策略里可设 `timeout=19`。

### 2.3 未来函数诊断脚本

- **文件**：`scripts/compare_execution_lag.py`
- **作用**：在不改 Rust 引擎的前提下，对比三种执行方式的绩效差异：
  - 同 bar close 成交（当前引擎行为）
  - 延后 1 根 K 线 open 成交
  - 延后 1 根 K 线 close 成交

---

## 3. 环境准备

### 3.1 基础依赖

确保机器上有：
- Python ≥ 3.10
- Rust + cargo
- uv（Python 包管理）

### 3.2 安装 Python 依赖

```bash
uv sync --extra dev
```

> 如果网络慢或依赖已满足，可加 `--no-sync` 跳过 lockfile 检查。

### 3.3 编译 Rust 扩展

```bash
maturin develop --release
```

或开发模式（更快，但未优化）：

```bash
maturin develop
```

---

## 4. 验证修复

### 4.1 构建与格式检查

```bash
# Rust
cargo check -p czsc-core
cargo fmt --all -- --check

# Python
uv run --no-sync ruff check report/generate_backtest_report.py docs/examples/19g_sector_report.py scripts/compare_execution_lag.py
```

### 4.2 交易次数整数化验证

如果本地有 19f / 19e 产出的 CSV，可以直接跑：

```bash
uv run --no-sync python docs/examples/19g_sector_report.py
```

输出里的 `trades` 列应为整数。

如果要生成 PDF 报告：

```bash
uv run --no-sync python report/generate_backtest_report.py
```

### 4.3 timeout 行为观察

跑任意一个带 `fixed_10` / `fixed_20` 的示例，观察实际持仓 K 线数。

```bash
uv run --no-sync python docs/examples/19c_exit_comparison.py
```

当前上游行为：`timeout=20` 实际持仓 21 根 K 线。如果你需要恰好 20 根，策略里设 `timeout=19`。

> 注意：这台机器如果没有本地 parquet 数据，上述脚本会报错或跳过。

---

## 5. 运行未来函数诊断

### 5.1 基本用法

```bash
uv run --no-sync python scripts/compare_execution_lag.py
```

默认读取 `510300.SH` 的 30 分钟数据，跑三个策略并输出对比表。

### 5.2 如何解读结果

输出示例：

```
=== 30min_fixed20 ===
    执行方式      年化收益  夏普比率  卡玛比率  最大回撤  交易胜率  交易次数
 同 bar close     0.324    1.25     6.15    -0.053   0.727     45
 延后 1 根 open   0.198    0.87     3.82    -0.052   0.711     45
 延后 1 根 close  0.256    1.05     4.90    -0.052   0.716     45
```

- **同 bar close 明显更高**：说明当前引擎有显著未来函数收益，实盘难复现。
- **三者接近**：策略对执行延迟不敏感，结果较稳健。
- **延后 open 明显更差**：说明信号 bar 后开盘常跳空，实盘进场成本高。

### 5.3 自定义标的和窗口

编辑脚本内 `main()` 函数顶部的常量：

```python
symbol = "510300.SH"
sdt_data, edt_data, sdt_bt = "20240101", "20260612", "2025-01-01"
```

也可以在 `main()` 里增加其他策略类。

---

## 6. 关于"最准的成交价"

常见问题：最准的回测成交价是不是"下一根更小粒度 K 线的 close"？

**答案是：理论上更接近实盘，但实现更复杂。**

### 6.1 几种执行方式的准确度排序

从最不严谨到最严谨：

1. **同 bar close 成交**（当前引擎）：未来函数，收益高估。
2. **同周期 next bar close**：已消除未来函数，但仍偏乐观。
3. **同周期 next bar open**：严格，但忽略开盘跳空和滑点。
4. **更小周期 next bar close**（如 30 分钟信号用 1 分钟 close）：更接近真实成交，但需更高频数据。
5. **更小周期 VWAP/TWAP + 滑点**：更真实，但需分钟级数据和冲击成本模型。
6. **tick 级撮合 + 盘口 + 滑点**：最接近实盘，但数据和实现成本高。

### 6.2 为什么"更小周期 next bar close"更准？

实盘不可能精确在开盘或收盘瞬间成交。用 1 分钟/5 分钟等更小周期的价格作为成交价，能部分模拟"信号确认后市场已经跑了一段"的真实情况。

### 6.3 需要注意的坑

- **未来函数风险**：如果用 1 分钟 close，必须确保该 1 分钟 bar 的时间戳 **严格晚于** 30 分钟信号 bar 的收盘时间。不能拿同一 30 分钟 bar 内部的 1 分钟数据。
- **数据对齐**：需要同时维护信号周期（30 分钟）和执行周期（1 分钟）两条时间序列。
- **T+1 仍然生效**：`Position` 引擎的 `t0=False` 已经保证跨日才能平仓，不需要额外处理。
- **计算成本**：更小粒度数据量更大，回测更慢。

### 6.4 推荐做法

如果回测机器有 1 分钟数据，建议扩展 `scripts/compare_execution_lag.py`：

- 30 分钟信号确认后，用下一根 1 分钟 K 线的 close 作为成交价；
- 或直接用 1 分钟 VWAP；
- 再加一个固定滑点（如 1 BP）作为冲击成本。

这样得到的结果比"同周期 next bar open"更可信。

---

## 7. 后续 TODO

- [ ] 在有数据的机器上跑 `19c_exit_comparison.py`，验证 `fixed_10`/`fixed_20` 持仓 K 线数。
- [ ] 跑 `19g_sector_report.py` / `report/generate_backtest_report.py`，验证交易次数为整数。
- [ ] 跑 `scripts/compare_execution_lag.py`，量化未来函数影响。
- [ ] 根据诊断结果决定是否修改 Rust 引擎，实现真正的 next-bar / 更小粒度成交模式。
- [ ] （可选）扩展诊断脚本，支持 1 分钟/5 分钟更高频执行价格。

---

## 8. 联系人/备注

- 问题记录：`REVIEW_BACKTEST.md`
- 本分支仅包含 Python 层修复 + 诊断脚本，未改动 Rust 执行引擎的未来函数逻辑。
