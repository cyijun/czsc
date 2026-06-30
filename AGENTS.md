# CZSC —— AI 编程助手项目指南

> 本文件面向 AI 编程助手（Agent）。读者应被假设对项目一无所知；所有信息均来自仓库实际内容，不加入推测。
>
> 项目人类开发者文档见 `README.md`、`CLAUDE.md` 与 `docs/`。

---

## 1. 项目概览

**CZSC**（缠中说禅技术分析工具）是一个量化交易技术分析库，专注于缠论核心概念（分型、笔、中枢、信号-事件-交易体系）的自动识别与多级别联立决策。

- **混合架构**：核心算法（CZSC、分型、笔、中枢、信号、交易器、TA 算子）使用 **Rust** 实现，通过 **PyO3** 编译为 Python 扩展模块 `czsc._native`；Python 侧仅做薄封装、数据格式转换与生态连接。
- **双发布目标**：同一个 git tag 同时产出 Python wheel（PyPI）与 Rust crate（crates.io）。
- **单一版本源**：`Cargo.toml` 中 `[workspace.package].version]` 是唯一版本来源；`pyproject.toml` 使用 `dynamic = ["version"]`，由 maturin 注入。
- **当前状态**：1.0.x 系列为 Rust 重构后的版本，与 0.9.x 不兼容；Python 端不再保留缠论算法的纯 Python 回退路径。

---

## 2. 技术栈与架构

### 2.1 核心技术栈

| 层级 | 技术 |
|------|------|
| 语言 | Rust（stable，edition 2024）、Python（>=3.10） |
| Rust 构建 | Cargo + `rust-toolchain.toml` |
| Python/Rust 绑定 | PyO3 0.28 + numpy 0.28 |
| Python 打包 | maturin（abi3-py310，单 wheel 覆盖 Python 3.10–3.13） |
| Python 依赖管理 | `uv`（`pyproject.toml` + `uv.lock`） |
| 代码质量 | `ruff`（format + lint）、`basedpyright`、cargo fmt、clippy |
| 测试 | pytest、cargo test、Criterion benchmark |
| CI/CD | GitHub Actions（`.github/workflows/`） |
| 可视化 | plotly、lightweight-charts（输出 HTML） |
| 回测生态 | 硬依赖 `wbt`（Weight Backtest） |

### 2.2 Rust Workspace 架构

Rust 代码位于 `crates/`，共 9 个 crate：

| Crate | 说明 | 是否发布到 crates.io |
|-------|------|----------------------|
| `czsc-core` | 缠论核心：FX、BI、ZS、CZSC、枚举、错误链 | 是 |
| `czsc-utils` | 工具：BarGenerator、交易时间、重采样、单调性 | 是 |
| `czsc-ta` | 技术指标算子（EMA、SMA、rolling_rank 等） | 是 |
| `czsc-signals` | 220+ 信号函数，按 `#[signal]` 宏自动注册 | 是 |
| `czsc-trader` | CzscTrader、CzscSignals、策略/优化/回测引擎 | 是 |
| `czsc-derive` | 自定义 derive / 辅助 proc-macro | 是 |
| `czsc-signal-macros` | `#[signal]`、`#[signal_module]` 宏 | 是 |
| `czsc` | facade crate，重新导出上述 crate | 是 |
| `czsc-python` | PyO3 绑定聚合器，产出 `czsc._native` 扩展；`publish = false` | 否 |

依赖方向：

```text
czsc-python → czsc-core / czsc-utils / czsc-ta / czsc-signals / czsc-trader / czsc-derive
czsc-signals → czsc-core / czsc-ta / czsc-signal-macros
czsc-trader  → czsc-core / czsc-utils / czsc-signals / czsc-derive
czsc-utils   → czsc-core / czsc-derive
czsc         → czsc-core / czsc-utils / czsc-ta / czsc-signals / czsc-trader
```

### 2.3 Python 包结构

```text
czsc/                              # Python 顶层包
├── __init__.py                    # 静态导入全部公共 API，__all__ 定义公开契约
├── _native/                       # Rust 扩展产物 + 自动生成的 __init__.pyi stub
├── _format_standard_kline.py      # DataFrame → list[RawBar]
├── _resample_bars.py              # K 线重采样的 Python 边界胶水
├── _runtime_adapters.py           # 运行时适配：周期排序、bars 规范化、事件归一
├── aphorism.py, envs.py, mock.py, models.py, research.py, strategies.py
├── cli/                           # `czsc` 命令行入口
├── connectors/                    # 数据源适配（Tushare / 天勤 / CCXT / 本地缓存）
├── fsa/                           # 飞书自动化工具
├── traders/                       # 交易 API facade
└── utils/                         # 工具子包（analysis / data / io / plotting / optimize / trade）
```

> `czsc/utils/plotting/backtest_visualizer.py` 新增 `BacktestVisualizer`：把 `CzscStrategyBase.backtest`
> 结果一键输出为 wbt 绩效报告 + lightweight-charts 交易点位图；支持通过 `chart_freq` 指定
> `日线` 等更大周期绘制交易点位。示例见 `docs/examples/21_backtest_visualizer.py` 与
> `docs/examples/21_etf_backtest_visualizer.py`，文档见 `docs/examples.md` / `docs/public_api.md` §16。

---

## 3. 关键配置文件

| 文件 | 作用 |
|------|------|
| `Cargo.toml` | Rust workspace 定义、成员、统一版本、共享依赖、release profile |
| `rust-toolchain.toml` | Rust 稳定版 + rustfmt + clippy |
| `.cargo/config.toml` | 启用增量编译 |
| `pyproject.toml` | Python 包元数据、依赖、可选依赖、pytest / ruff / basedpyright / maturin 配置 |
| `uv.lock` | uv 依赖锁定文件 |
| `Cargo.lock` | Rust 依赖锁定文件 |
| `.github/workflows/code-quality.yml` | CI：Rust 单 crate 测试、Python 测试矩阵、stub 漂移检查、格式化、lint、安全/依赖审计 |
| `.github/workflows/python-publish.yml` | 构建并发布 abi3 wheel + sdist 到 PyPI；smoke-test；GitHub Release + sigstore 签名 |
| `.github/workflows/rust-publish.yml` | 按依赖层分层发布 crate 到 crates.io；tag push 仅 dry-run，dispatch 才真发 |
| `.github/workflows/claude.yml` | issue/comment 触发 Claude Code 的自动化 workflow |

---

## 4. 构建与开发命令

### 4.1 环境准备

```bash
# 安装 Rust（如尚未安装）
# curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# 安装/同步 Python 依赖（开发全量）
uv sync --extra all

# 构建本地 Rust 扩展（开发模式）
uv run maturin develop

# 生产/发布模式构建
uv run maturin develop --release
```

> 注意：当系统默认 Python < 3.10 时，需显式设置 `export PYO3_PYTHON=$(which python3.12)`（或任意 3.10+ 解释器）。

### 4.2 测试

```bash
# Python 测试（默认跳过 slow 用例）
uv run --no-sync pytest

# 跑全套（含 slow 用例，CI / 发布前必须跑）
uv run --no-sync pytest --run-slow

# 带覆盖率
uv run --no-sync pytest --cov=czsc

# Rust 单 crate 测试（CI 中的 rust-tests job）
cargo test -p czsc-derive -p czsc-core -p czsc-utils -p czsc-ta -p czsc-signal-macros --no-fail-fast

# 注意：czsc-signals / czsc-trader / czsc-python 因启用 extension-module，不能用 workspace 级 cargo test；
# 它们由 Python pytest 通过 maturin develop 端到端覆盖。
```

### 4.3 代码质量

```bash
# Python 格式化与检查
uv run --no-sync ruff format czsc/ tests/
uv run --no-sync ruff check czsc/ tests/

# Python 类型检查（CI 中设了 || true，不阻塞 merge）
uv run --no-sync basedpyright czsc/

# Rust 格式化与 clippy
cargo fmt --all
cargo clippy --workspace --all-targets -- -D warnings
```

### 4.4 stub 生成（修改 PyO3 暴露接口后必须跑）

```bash
PYO3_PYTHON=$(uv run python -c 'import sys; print(sys.executable)') \
  cargo run --bin stub_gen -p czsc-python --no-default-features --features stub-gen

# 必须无 diff，否则 CI stub-drift job 会失败
git diff --exit-code czsc/_native/__init__.pyi
```

### 4.5 CLI 使用

项目入口：`pyproject.toml` 定义 `czsc = "czsc.cli:app"`。

```bash
# 查看所有子命令
uv run czsc --help

# 常用子命令
uv run czsc signals      # 信号目录与文档
uv run czsc research     # 策略研究 / 回放 / 配置解析
uv run czsc data         # 造数与质量校验
uv run czsc plot         # HTML 可视化
uv run czsc analyze      # 对 K 线跑缠论分析
uv run czsc backtest     # 回测
uv run czsc bench        # 性能基准
uv run czsc schema       # 导出命令 schema（支持 --json）
```

---

## 5. 测试策略

### 5.1 测试目录组织

```text
tests/
├── conftest.py                  # 全局：--run-slow 开关
├── unit/                        # 单元测试（核心契约、枚举、parity、resample、strategy）
├── compat/                      # 兼容性/回归测试（公开 API 快照、API 移除防护）
├── integration/                 # 集成测试（权重回测）
├── smoke/                       # 安装/导入冒烟测试
└── cli/                         # CLI 各子命令测试
```

### 5.2 关键测试约定

- **模拟数据**：测试中禁止使用硬编码 K 线；统一使用 `czsc.mock.generate_symbol_kines` / `generate_klines_with_weights`。
- **慢测试**：依赖 `time.sleep`、子进程冷启动或大计算量的测试标记 `@pytest.mark.slow`；默认被 `conftest.py` 跳过，发布前必须 `--run-slow`。
- **parity 测试**：存在 Rust/Python 行为一致性测试，例如 `test_strategy_save_load_parity.py`、`test_monotonicity_parity.py`、`test_core_parity.py`。
- **公开 API 回归**：`tests/compat/` 使用快照基线，防止已删除的 API（如 `czsc.svc`、`czsc.ta`、`czsc.core`）被重新引入。
- **Rust 端测试限制**：CI 不对 `czsc-signals` / `czsc-trader` / `czsc-python` 跑 `cargo test`；这些 crate 的单元/集成逻辑由 Python 端到端测试覆盖。

---

## 6. 代码规范与开发约定

### 6.1 Python 代码风格

配置位置：`pyproject.toml`。

- 行长度：**120**。
- linter：ruff，选中 `E, F, I, UP, B, SIM, C4`；忽略 `E501, SIM112`。
- formatter：ruff（空格缩进）。
- 类型检查：basedpyright，模式 `standard`，目标 Python 3.10。
- 顶层导入顺序：在 `czsc/__init__.py` 中手工编排，文件头有 `# isort: skip_file`，**不要重排**。

### 6.2 Rust 代码风格

- 使用 `cargo fmt` 格式化。
- clippy 在 CI 中必须零警告：`-D warnings`。
- 工具链版本由 `rust-toolchain.toml` 锁定。

### 6.3 Rust ↔ Python 行为一致（开发宪法第一条）

这是项目最重要的硬约束：

- 同一个名字（如 `CZSC`、`generate_czsc_signals`、`CzscStrategyBase`）在 Rust crate 与 Python wheel 中行为必须一致。
- Python 侧**只允许**两类工作：
  1. **纯透传**：`from czsc._native import xxx` 后直接 re-export。
  2. **不可避免的 PyO3 边界胶水**：DataFrame ↔ Arrow IPC、`pathlib.Path` ↔ `String`、周期字符串映射等。
- **禁止**在 Python 侧写参数归一化、默认值补齐、返回值字段重命名、错误码翻译、`isinstance` 多态分支等适配层。
- 违反信号：Python 函数体内出现 `if isinstance(bars, pd.DataFrame): ... elif isinstance(bars, list): ...` 等多态分支；Python 返回 dict 字段顺序/命名与 Rust 端 `serde` 输出不一致等。

### 6.4 模块与命名约定

- 信号函数在 Rust 中通过 `#[signal]` 宏注册到全局 `SIGNAL_REGISTRY`；**不再使用** `V<yyMMdd>` 版本后缀。
- Python 端信号命名空间：`czsc._native.signals.{bar,cvolp,cxt,obv,pressure,tas,vol}`（底层 `crates/czsc-signals/src/` 有更多子模块）。
- 历史已删除路径：**不要**恢复 `czsc.core`、`czsc/signals/`、`czsc.svc`、`czsc.ta` 顶层别名、`CZSC_USE_PYTHON`。
- 新增 Python wrapper 前，PR 描述必须先回答“为什么不能改成 Rust 实现”。

### 6.5 文档与示例

- 所有公开函数必须写完整 docstring。
- 示例脚本集中在 `docs/examples/`，索引在 `docs/examples.md`。
- 发布前检查清单：`docs/release_checklist.md`。

---

## 7. 发布与部署流程

### 7.1 版本管理

- 唯一版本源：`Cargo.toml [workspace.package].version`。
- git tag 格式：`v<VERSION>`。
- `pyproject.toml` 必须保持 `dynamic = ["version"]`；硬编码会被 `crates/czsc-python/build.rs` 在编译期拒绝。
- CI 在发布 PyPI 时会三重校验：git tag == Cargo.toml version == wheel filename 版本（含 SemVer → PEP 440 归一化）。

### 7.2 Python 包发布

触发：push tag `v*`。

流程：

1. 构建 6 平台 abi3 wheel（Linux x86_64/aarch64/musllinux、macOS x86_64/arm64、Windows x64）。
2. 构建 sdist。
3. smoke-test 部分平台（Linux x86_64、macOS arm64、Windows x64）。
4. 校验版本一致性。
5. 上传 PyPI（Trusted Publishing / OIDC，无仓库 token）。
6. 创建 GitHub Release 并 sigstore 签名。

### 7.3 Rust crate 发布

触发：tag push 时仅 **dry-run**；真正发布需要手动 `workflow_dispatch` 并勾选 `do_publish=true`。

分层顺序（等待 crates.io index 同步）：

- layer 0：`czsc-derive`、`czsc-signal-macros`
- layer 1：`czsc-core`
- layer 2：`czsc-ta`、`czsc-utils`
- layer 3：`czsc-signals`
- layer 4：`czsc-trader`
- layer 5：`czsc`（facade）

支持 `start_layer` / `end_layer` 断点续发。

### 7.4 发布前自检（来自 `docs/release_checklist.md`）

关键项：

- CHANGELOG 已更新，breaking changes 单独成段。
- README / CLAUDE.md / `docs/examples.md` / 公开 docstring 与代码一致。
- `cargo fmt --all -- --check`、`cargo clippy --workspace --all-targets -- -D warnings` 通过。
- stub 已重新生成且无 diff。
- `uv run --no-sync pytest --run-slow` 通过。
- `cargo add czsc@=<VERSION>` 在干净 Rust 项目中能 `cargo check` 通过（rc.8 踩坑后的新增检查）。

---

## 8. 安全与合规

- **依赖审计**：CI `code-quality.yml` 在 master push / schedule 时跑 `safety check` 与 `bandit`，但每个 step 都 `|| true`，**不阻塞 merge**。
- **无仓库 secrets 泄露 PyPI token**：PyPI 使用 Trusted Publishing / OIDC；crates.io 仍使用 `CRATES_IO_TOKEN` secret。
- **最小权限**：Agent 不应在未经确认的情况下修改工作目录外文件、安装/删除系统级软件或执行 git mutations（commit/push/rebase 等）。
- **缓存目录**：默认 `~/.czsc`，可通过 `CZSC_HOME` 覆盖；提供 `empty_cache_path()` 清理。
- **输入校验**：Rust 端对 tz-aware datetime、NaN OHLCV 等采取 fail-loud 策略；Python 端应避免静默兜底。

---

## 9. 环境变量与设置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CZSC_VERBOSE` / `czsc_verbose` | `False` | 是否打印详细日志 |
| `CZSC_MIN_BI_LEN` / `czsc_min_bi_len` | `6` | 最小笔长度（去包含后的 K 线根数） |
| `CZSC_MAX_BI_NUM` / `czsc_max_bi_num` | `50` | 单个 CZSC 实例保留的最大笔数 |
| `CZSC_HOME` | `~/.czsc` | 缓存根目录 |

注意：`CZSC_USE_PYTHON` 已废弃并移除。

---

## 10. 常见陷阱与快速排查

| 现象 | 根因/处理 |
|------|-----------|
| `cargo test --workspace` 失败 | workspace 中 `czsc-python` 启用了 `extension-module`，不能与 libpython 链接；改跑单 crate 测试。 |
| 修改 Rust API 后 Python 侧类型提示仍旧 | 没有重跑 `stub_gen`；运行 §4.4 命令并提交 `czsc/_native/__init__.pyi`。 |
| CI 中 Python 3.10/3.11/3.12/3.13 某版本失败 | 检查 `abi3-py310` 是否仍然兼容；通常与 PyO3 边界或 `PYO3_PYTHON` 配置有关。 |
| 发布到 crates.io 后下游 `cargo check` 失败 | 检查 workspace 依赖是否使用 `version = "=X.Y.Z"` 严格锁定 prerelease；误发的 stable 需 yank。 |
| 测试中 `from czsc import ...` 触发循环导入 | 不要改动 `czsc/__init__.py` 的导入顺序；新子包若引用顶层符号，应分批导入。 |
| wheel smoke 缺少某些依赖 | smoke-test 使用 `--no-deps` + 最小依赖集；若新增顶层 import，需同步 `python-publish.yml` 的 pip install 列表。 |

---

## 11. 常用资源

- 公开 API 参考：`docs/public_api.md`
- 发布检查清单：`docs/release_checklist.md`
- 案例索引：`docs/examples.md`；脚本位置：`docs/examples/`
- 回测可视化类：`czsc/utils/plotting/backtest_visualizer.py`；示例：`docs/examples/21_backtest_visualizer.py`
- Rust stub 文件：`czsc/_native/__init__.pyi`
- 人类/Claude 专用指南：`CLAUDE.md`
- 外部文档：README.md 中列出的飞书 wiki、B 站教程等

---

*本文件基于仓库实际内容整理生成。如后续架构、CI 或约定发生变更，应同步更新本文件。*
