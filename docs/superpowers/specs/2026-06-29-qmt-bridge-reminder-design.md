# czsc 半自动交易提醒系统设计

## 1. 背景与目标

基于 czsc 项目实现一个半自动交易提醒系统：

- **数据源**：`qmt-bridge` 服务端（默认 `http://qmt-vm:18888`）。
- **标的**：`588000.SH`（科创50ETF华夏）、`588800.SH`（科创100ETF华夏）。
- **周期**：主交易周期 `30分钟`，可选日线周期做方向过滤。
- **通知渠道**：飞书群机器人。
- **自动化程度**：只提醒，不下单。
- **运行方式**：本地定时脚本，由 cron/任务计划程序每 30 分钟触发一次。
- **信号来源**：czsc 内置缠论信号组合（如 `三买辅助V230228` + `表里关系V230101` 共振）。

## 2. 总体架构

新增核心模块 `czsc/traders/reminder_trader.py`，对外提供 `ReminderTrader` 类：

```
┌─────────────────────────────────────────────────────────────┐
│                     ReminderTrader                          │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │ DataFeed    │  │ SignalEngine │  │ Notifier         │   │
│  │ (qmt-bridge)│  │ (CzscTrader) │  │ (Feishu/Console) │   │
│  └──────┬──────┘  └──────┬───────┘  └────────┬─────────┘   │
│         │                │                     │             │
│  ┌──────▼────────────────▼─────────────────────▼─────────┐  │
│  │              StateStore (JSON，可扩展 SQLite)           │  │
│  │  - 每只标的最新 bar 时间                               │  │
│  │  - 每只标的当前仓位（0/1）                             │  │
│  │  - 最近已发送的提醒，避免重复                          │  │
│  └────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

`ReminderTrader` 职责：

1. 按配置从 qmt-bridge 拉取多只 ETF 的 K 线。
2. 用 `CzscTrader` 维护每只标的的信号状态。
3. 当仓位发生变化时调用通知器发送飞书消息。
4. 把状态持久化到本地，避免每次重启后重新计算历史信号。

## 3. 核心组件

### 3.1 `ReminderTrader`

```python
class ReminderTrader:
    def __init__(
        self,
        symbols: list[str],
        freq: str,
        positions: list[Position],
        filter_freq: str | None = None,
        filter_positions: list[Position] | None = None,
        data_client: Callable | None = None,
        notifier: Notifier | None = None,
        state_store: StateStore | None = None,
        lookback: int = 500,
        reminder_cooldown_minutes: int = 60,
    ):
        ...

    def run_once(self) -> list[dict]:
        """单次执行：拉取数据、更新信号、发送提醒、持久化状态。"""
        ...
```

参数说明：

| 参数 | 说明 |
|---|---|
| `symbols` | 标的代码列表，如 `["588000.SH", "588800.SH"]`。 |
| `freq` | 主交易周期，如 `"30分钟"`。 |
| `positions` | 主周期对应的 `Position` 列表。 |
| `filter_freq` | 过滤周期，如 `"日线"`；为 `None` 时不做过滤。 |
| `filter_positions` | 过滤周期对应的 `Position` 列表。 |
| `data_client` | 数据源函数，默认 `qmt_bridge_connector.get_raw_bars`。 |
| `notifier` | 通知器，默认 `ConsoleNotifier`。 |
| `state_store` | 状态存储，默认 `JsonStateStore`。 |
| `lookback` | 初始化时拉取的历史 bar 数量。 |
| `reminder_cooldown_minutes` | 同一 action 最小提醒间隔。 |

### 3.2 `Notifier` 抽象

```python
class Notifier(ABC):
    @abstractmethod
    def send(self, title: str, body: str, metadata: dict) -> None: ...

class FeishuNotifier(Notifier):
    def __init__(self, bot_key: str): ...

class ConsoleNotifier(Notifier):
    """仅打印到控制台，用于本地调试。"""
```

飞书消息格式示例：

```
【交易提醒】2026-06-29 14:00
标的：588000.SH 科创50ETF华夏
信号：由空仓 → 满仓
操作：买入
最新价：1.234
```

### 3.3 `StateStore` 抽象

```python
class StateStore(ABC):
    @abstractmethod
    def load(self, symbol: str, freq: str) -> dict: ...

    @abstractmethod
    def save(self, symbol: str, freq: str, state: dict) -> None: ...

class JsonStateStore(StateStore):
    """JSON 文件持久化，适合简单场景。"""

# 未来可按需增加 SQLiteStateStore 等实现。
```

持久化字段：

| 字段 | 说明 |
|---|---|
| `symbol` | 标的代码。 |
| `freq` | 周期。 |
| `last_bar_dt` | 最近处理的 bar 时间。 |
| `current_pos` | 当前仓位（0/1）。 |
| `filter_current_pos` | 过滤周期当前仓位（0/1），多周期模式下使用。 |
| `last_reminder_dt` | 最近提醒时间。 |
| `last_reminder_action` | 最近提醒动作（买入/卖出）。 |
| `reminder_count` | 累计提醒次数。 |

### 3.4 信号引擎

内部为每个 symbol 维护一个 `CzscTrader`：

```python
self._traders: dict[str, CzscTrader] = {
    "588000.SH": CzscTrader(bg, positions=positions, signals_config=signals_config),
    ...
}
```

其中 `signals_config` 由 `positions` 和 `filter_positions` 中的事件信号推导而来（通过 `czsc.get_signals_config`），确保 `CzscTrader` 会计算 Position 所需的信号。

多周期模式下，每个 symbol 维护两个 `CzscTrader`（`freq` 和 `filter_freq`）。

## 4. 数据流

### 4.1 单周期流程

```
定时触发（cron 每 30 分钟）
    │
    ▼
拉取 symbol 的 30分钟 K 线（从 last_bar_dt 到最新）
    │
    ▼
逐根喂给 CzscTrader.update(bar)
    │
    ▼
若 ct.pos_changed：
    生成提醒 → Notifier.send(...)
    更新 StateStore
    │
    ▼
结束
```

### 4.2 多周期共振流程

每个 symbol 维护两个仓位：

- `pos_d`：日线级别方向仓位。
- `pos_30m`：30分钟级别交易仓位。

提醒决策表：

| pos_d | pos_30m 变化 | 是否提醒 | 说明 |
|---|---|---|---|
| 1 | 0 → 1 | ✅ 买入提醒 | 日线看多，30分钟出现买点。 |
| 1 | 1 → 0 | ⚠️ 减仓提醒 | 日线仍看多，30分钟卖点，可减仓。 |
| 0 | 0 → 1 | ❌ 不提醒 | 日线看空，不做多。 |
| 0 | 1 → 0 | ✅ 卖出提醒 | 日线看空，30分钟卖点，清仓。 |

### 4.3 防重复提醒

- 同一 `(symbol, action)` 在 `reminder_cooldown_minutes` 内只提醒一次。
- 程序重启后，若仓位未变化，不触发提醒。

## 5. 错误处理

| 场景 | 处理 |
|---|---|
| qmt-bridge 不可达 | 记录 warning，本次跳过，下次定时任务再试。 |
| 某只 ETF 无数据 | 单独跳过该 symbol，其他 symbol 正常处理。 |
| 飞书发送失败 | 记录 error 到本地日志，状态仍更新，避免无限重发。 |
| 历史 bar 不足 | 用 `lookback` 控制，不足时发 warning 但继续运行。 |
| 程序异常退出 | `StateStore` 保证已处理状态和仓位不丢失。 |

## 6. 运行与部署

### 6.1 脚本入口

新增示例脚本 `docs/examples/22_qmt_bridge_reminder.py`：

```python
import os
from czsc.traders.reminder_trader import ReminderTrader, FeishuNotifier
from czsc.connectors import qmt_bridge_connector

# 由用户填充具体 Position 配置
positions_30m = [...]
positions_d = [...]

trader = ReminderTrader(
    symbols=["588000.SH", "588800.SH"],
    freq="30分钟",
    filter_freq="日线",
    positions=positions_30m,
    filter_positions=positions_d,
    data_client=qmt_bridge_connector.get_raw_bars,
    notifier=FeishuNotifier(bot_key=os.environ["FEISHU_BOT_KEY"]),
)

trader.run_once()
```

### 6.2 cron 配置

macOS/Linux：

```bash
*/30 9-15 * * 1-5 /path/to/.venv/bin/python /path/to/22_qmt_bridge_reminder.py >> /path/to/reminder.log 2>&1
```

Windows：使用任务计划程序每 30 分钟执行一次。

非交易时间 cron 本身不会触发（如上 cron 已限定 9-15 点、工作日）；如需在脚本内部再加一道交易时间过滤，可由调用方自行判断。

## 7. 范围与限制

- 本期只实现数据获取与提醒发送，不下单。
- 不开发 Web UI，历史提醒以飞书消息记录为准。
- 本期先支持单一主周期 + 可选单一过滤周期，未来可扩展为多主周期并行。

## 8. 待实现清单

1. 新增 `czsc/traders/reminder_trader.py`：
   - `Notifier` / `FeishuNotifier` / `ConsoleNotifier`
   - `StateStore` / `JsonStateStore`（未来可扩展 SQLiteStateStore）
   - `ReminderTrader`
2. 新增 `docs/examples/22_qmt_bridge_reminder.py` 示例脚本。
3. 新增 `tests/traders/test_reminder_trader.py` 单元测试（使用 mock notifier 和 state store）。
4. 运行示例验证连通性与提醒流程。
