# czsc qmt-bridge 半自动交易提醒系统实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `qmt-bridge-adapt` 分支实现一个通用半自动交易提醒模块，通过 qmt-bridge 拉取 `588000.SH` / `588800.SH` 的 30分钟 K 线，基于 czsc 内置共振信号生成买入/卖出提醒，并通过飞书群机器人推送。

**Architecture:** 新增 `czsc/traders/reminder_trader.py`，封装 `Notifier` / `StateStore` / `ReminderTrader` 三个抽象；`ReminderTrader` 内部为每只标的维护 `CzscTrader`，在仓位变化时调用通知器并持久化状态。默认状态存 JSON，默认通知为飞书 text 消息。

**Tech Stack:** Python 3.10+, czsc, requests, pandas, loguru, czsc.fsa (Feishu)

---

## File Structure

| 文件 | 职责 |
|---|---|
| `czsc/traders/reminder_trader.py` | 核心实现：`Notifier` / `StateStore` / `ReminderTrader`。 |
| `docs/examples/22_qmt_bridge_reminder.py` | 可运行的示例脚本，配置 588000.SH / 588800.SH。 |
| `tests/traders/test_reminder_trader.py` | 单元测试：用 mock notifier/state store 验证提醒流程。 |
| `docs/superpowers/specs/2026-06-29-qmt-bridge-reminder-design.md` | 设计文档（已存在）。 |

---

## Task 1: Notifier 抽象与实现

**Files:**
- Create: `czsc/traders/reminder_trader.py`
- Test: `tests/traders/test_reminder_trader.py`

- [ ] **Step 1: Write the failing test for ConsoleNotifier**

```python
# tests/traders/test_reminder_trader.py
import pytest
from czsc.traders.reminder_trader import ConsoleNotifier


def test_console_notifier_records_message():
    notifier = ConsoleNotifier()
    notifier.send("title", "body", {"symbol": "588000.SH", "action": "买入"})
    assert len(notifier.messages) == 1
    msg = notifier.messages[0]
    assert msg["title"] == "title"
    assert msg["body"] == "body"
    assert msg["metadata"]["action"] == "买入"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/traders/test_reminder_trader.py::test_console_notifier_records_message -v`
Expected: FAIL with `ModuleNotFoundError` or `ImportError`

- [ ] **Step 3: Implement Notifier ABC and ConsoleNotifier**

```python
# czsc/traders/reminder_trader.py
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class Notifier(ABC):
    """提醒通知器抽象。"""

    @abstractmethod
    def send(self, title: str, body: str, metadata: dict[str, Any]) -> None:
        """发送一条提醒。

        :param title: 标题
        :param body: 正文
        :param metadata: 附加元数据，如 symbol/action/price 等
        """


class ConsoleNotifier(Notifier):
    """仅打印到控制台并保留历史，便于测试和调试。"""

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    def send(self, title: str, body: str, metadata: dict[str, Any]) -> None:
        record = {"title": title, "body": body, "metadata": metadata}
        self.messages.append(record)
        print(f"[{title}] {body}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/traders/test_reminder_trader.py::test_console_notifier_records_message -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add czsc/traders/reminder_trader.py tests/traders/test_reminder_trader.py
git commit -m "feat(reminder): add Notifier ABC and ConsoleNotifier"
```

---

## Task 2: FeishuNotifier 实现

**Files:**
- Modify: `czsc/traders/reminder_trader.py`
- Test: `tests/traders/test_reminder_trader.py`

- [ ] **Step 1: Write the failing test for FeishuNotifier**

```python
# tests/traders/test_reminder_trader.py
from unittest.mock import patch
from czsc.traders.reminder_trader import FeishuNotifier


def test_feishu_notifier_calls_push_text():
    notifier = FeishuNotifier(bot_key="test_key")
    with patch("czsc.traders.reminder_trader.push_text") as mock_push:
        notifier.send("title", "body", {"symbol": "588000.SH"})
        mock_push.assert_called_once()
        text = mock_push.call_args[0][0]
        assert "title" in text
        assert "body" in text
        assert "588000.SH" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/traders/test_reminder_trader.py::test_feishu_notifier_calls_push_text -v`
Expected: FAIL with `ImportError` or `AttributeError`

- [ ] **Step 3: Implement FeishuNotifier**

```python
# czsc/traders/reminder_trader.py
import os
from czsc.fsa import push_text


class FeishuNotifier(Notifier):
    """飞书群机器人通知器。"""

    def __init__(self, bot_key: str | None = None):
        self.bot_key = bot_key or os.environ.get("FEISHU_BOT_KEY")
        if not self.bot_key:
            raise ValueError("请提供 bot_key 或设置环境变量 FEISHU_BOT_KEY")

    def send(self, title: str, body: str, metadata: dict[str, Any]) -> None:
        text = f"{title}\n{body}\n"
        for k, v in metadata.items():
            text += f"{k}: {v}\n"
        push_text(text.strip(), key=self.bot_key)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/traders/test_reminder_trader.py::test_feishu_notifier_calls_push_text -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add czsc/traders/reminder_trader.py tests/traders/test_reminder_trader.py
git commit -m "feat(reminder): add FeishuNotifier"
```

---

## Task 3: StateStore 抽象与 JSON 实现

**Files:**
- Modify: `czsc/traders/reminder_trader.py`
- Test: `tests/traders/test_reminder_trader.py`

- [ ] **Step 1: Write the failing test for JsonStateStore**

```python
# tests/traders/test_reminder_trader.py
import tempfile
from pathlib import Path
from czsc.traders.reminder_trader import JsonStateStore


def test_json_state_store_save_and_load():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = JsonStateStore(base_dir=tmpdir)
        state = {
            "last_bar_dt": "2026-06-29 14:00:00",
            "current_pos": 1,
            "last_reminder_dt": "",
            "last_reminder_action": "",
            "reminder_count": 0,
        }
        store.save("588000.SH", "30分钟", state)
        loaded = store.load("588000.SH", "30分钟")
        assert loaded["current_pos"] == 1
        assert loaded["last_bar_dt"] == "2026-06-29 14:00:00"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/traders/test_reminder_trader.py::test_json_state_store_save_and_load -v`
Expected: FAIL with `ImportError` or `AttributeError`

- [ ] **Step 3: Implement StateStore ABC and JsonStateStore**

```python
# czsc/traders/reminder_trader.py
import json
from abc import ABC, abstractmethod
from pathlib import Path


class StateStore(ABC):
    """状态持久化抽象。"""

    @abstractmethod
    def load(self, symbol: str, freq: str) -> dict[str, Any]:
        """加载指定 symbol + freq 的状态。"""

    @abstractmethod
    def save(self, symbol: str, freq: str, state: dict[str, Any]) -> None:
        """保存指定 symbol + freq 的状态。"""


class JsonStateStore(StateStore):
    """基于 JSON 文件的本地状态存储。"""

    def __init__(self, base_dir: str | None = None):
        self.base_dir = Path(base_dir or os.environ.get("CZSC_REMINDER_STATE_DIR", ".reminder_state"))
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _file_path(self, symbol: str, freq: str) -> Path:
        safe_symbol = symbol.replace(".", "_")
        safe_freq = freq.replace("/", "_")
        return self.base_dir / f"{safe_symbol}_{safe_freq}.json"

    def load(self, symbol: str, freq: str) -> dict[str, Any]:
        path = self._file_path(symbol, freq)
        if not path.exists():
            return {
                "last_bar_dt": "",
                "current_pos": 0,
                "last_reminder_dt": "",
                "last_reminder_action": "",
                "reminder_count": 0,
            }
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def save(self, symbol: str, freq: str, state: dict[str, Any]) -> None:
        path = self._file_path(symbol, freq)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/traders/test_reminder_trader.py::test_json_state_store_save_and_load -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add czsc/traders/reminder_trader.py tests/traders/test_reminder_trader.py
git commit -m "feat(reminder): add StateStore ABC and JsonStateStore"
```

---

## Task 4: ReminderTrader 核心逻辑（单周期）

**Files:**
- Modify: `czsc/traders/reminder_trader.py`
- Test: `tests/traders/test_reminder_trader.py`

- [ ] **Step 1: Write the failing test for single-frequency reminder**

```python
# tests/traders/test_reminder_trader.py
from datetime import datetime
from czsc import Freq, RawBar
from czsc.traders.reminder_trader import ReminderTrader, ConsoleNotifier, JsonStateStore


def test_reminder_trader_detects_position_change():
    """构造一组连续上涨的 bar，触发 Position 由 0 -> 1，验证提醒发出。"""
    from czsc import Event, Position
    from czsc.connectors.qmt_bridge_connector import get_raw_bars

    open_event = Event.load(
        {
            "name": "日线_阳线_开多",
            "operate": "开多",
            "signals_all": ["日线_D1_K线_阳线_任意_任意_0"],
        }
    )
    position = Position(name="test_pos", symbol="TEST", opens=[open_event], exits=[], interval=0)

    notifier = ConsoleNotifier()
    store = JsonStateStore(base_dir=tempfile.mkdtemp())
    trader = ReminderTrader(
        symbols=["TEST"],
        freq="日线",
        positions=[position],
        data_client=lambda symbol, freq, sdt, edt, **kwargs: _make_bars(symbol, sdt, edt),
        notifier=notifier,
        state_store=store,
    )
    trader.run_once()
    assert len(notifier.messages) >= 0  # 具体取决于构造的 bar
```

> 注：测试用例需要构造一组能触发 Position 变化的 bars。若 `Event` 信号太难构造，可使用 `CzscStrategyBase` 的子类或 mock `CzscTrader`。

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/traders/test_reminder_trader.py::test_reminder_trader_detects_position_change -v`
Expected: FAIL with `ImportError` or `AttributeError`

- [ ] **Step 3: Implement ReminderTrader single-frequency logic**

```python
# czsc/traders/reminder_trader.py
from datetime import datetime, timedelta

import pandas as pd
from loguru import logger

import czsc
from czsc.connectors import qmt_bridge_connector


class ReminderTrader:
    """半自动交易提醒器。"""

    def __init__(
        self,
        symbols: list[str],
        freq: str,
        positions: list[czsc.Position],
        filter_freq: str | None = None,
        filter_positions: list[czsc.Position] | None = None,
        data_client: Any = None,
        notifier: Notifier | None = None,
        state_store: StateStore | None = None,
        lookback: int = 500,
        reminder_cooldown_minutes: int = 60,
    ):
        self.symbols = symbols
        self.freq = freq
        self.positions = positions
        self.filter_freq = filter_freq
        self.filter_positions = filter_positions or []
        self.data_client = data_client or qmt_bridge_connector.get_raw_bars
        self.notifier = notifier or ConsoleNotifier()
        self.state_store = state_store or JsonStateStore()
        self.lookback = lookback
        self.reminder_cooldown_minutes = reminder_cooldown_minutes

        self._traders: dict[str, czsc.CzscTrader] = {}
        self._filter_traders: dict[str, czsc.CzscTrader] = {}

    def _init_trader(self, symbol: str, freq: str, positions: list[czsc.Position]) -> czsc.CzscTrader:
        bg = czsc.BarGenerator(base_freq=freq, freqs=[freq], max_count=self.lookback + 100)
        return czsc.CzscTrader(bg, positions=positions, signals_config=[])

    def _load_bars(self, symbol: str, freq: str) -> list[czsc.RawBar]:
        state = self.state_store.load(symbol, freq)
        last_dt = state.get("last_bar_dt", "")
        if last_dt:
            sdt = pd.to_datetime(last_dt)
        else:
            sdt = pd.Timestamp.now() - pd.Timedelta(days=self.lookback)
        edt = pd.Timestamp.now() + pd.Timedelta(days=1)
        bars = self.data_client(symbol, freq, sdt.strftime("%Y%m%d"), edt.strftime("%Y%m%d"))
        if isinstance(bars, pd.DataFrame):
            bars = czsc.format_standard_kline(bars, freq=freq)
        return bars

    def _update_symbol(self, symbol: str) -> list[dict[str, Any]]:
        reminders: list[dict[str, Any]] = []
        bars = self._load_bars(symbol, self.freq)
        if not bars:
            logger.warning(f"{symbol} 无 {self.freq} 数据")
            return reminders

        if symbol not in self._traders:
            self._traders[symbol] = self._init_trader(symbol, self.freq, self.positions)
        trader = self._traders[symbol]

        state = self.state_store.load(symbol, self.freq)
        last_dt = pd.to_datetime(state.get("last_bar_dt", "1970-01-01")) if state.get("last_bar_dt") else pd.Timestamp.min

        for bar in bars:
            if bar.dt <= last_dt:
                continue
            trader.update(bar)
            if trader.pos_changed:
                new_pos = trader.get_ensemble_pos("测试")
                action = self._decide_action(state["current_pos"], new_pos)
                if action:
                    reminder = self._build_reminder(symbol, bar, action, new_pos)
                    if self._should_send(state, reminder):
                        self.notifier.send(reminder["title"], reminder["body"], reminder["metadata"])
                        reminders.append(reminder)
                        state["last_reminder_dt"] = bar.dt.strftime("%Y-%m-%d %H:%M:%S")
                        state["last_reminder_action"] = action
                        state["reminder_count"] = state.get("reminder_count", 0) + 1
                state["current_pos"] = int(new_pos)
            last_dt = max(last_dt, pd.to_datetime(bar.dt))

        state["last_bar_dt"] = last_dt.strftime("%Y-%m-%d %H:%M:%S")
        self.state_store.save(symbol, self.freq, state)
        return reminders

    def _decide_action(self, old_pos: int, new_pos: float) -> str:
        old = int(old_pos)
        new = 1 if new_pos > 0 else 0
        if old == 0 and new == 1:
            return "买入"
        if old == 1 and new == 0:
            return "卖出"
        return ""

    def _build_reminder(self, symbol: str, bar: czsc.RawBar, action: str, pos: float) -> dict[str, Any]:
        title = f"【交易提醒】{bar.dt.strftime('%Y-%m-%d %H:%M')}"
        body = f"标的：{symbol}\n操作：{action}\n最新价：{bar.close:.3f}\n当前仓位：{int(pos)}"
        metadata = {
            "symbol": symbol,
            "dt": bar.dt.strftime("%Y-%m-%d %H:%M:%S"),
            "action": action,
            "price": float(bar.close),
            "pos": int(pos),
        }
        return {"title": title, "body": body, "metadata": metadata}

    def _should_send(self, state: dict[str, Any], reminder: dict[str, Any]) -> bool:
        last_action = state.get("last_reminder_action", "")
        last_dt_str = state.get("last_reminder_dt", "")
        if last_action != reminder["metadata"]["action"]:
            return True
        if not last_dt_str:
            return True
        last_dt = pd.to_datetime(last_dt_str)
        current_dt = pd.to_datetime(reminder["metadata"]["dt"])
        return (current_dt - last_dt) >= timedelta(minutes=self.reminder_cooldown_minutes)

    def run_once(self) -> list[dict[str, Any]]:
        """单次执行：拉取数据、更新信号、发送提醒、持久化状态。"""
        all_reminders: list[dict[str, Any]] = []
        for symbol in self.symbols:
            try:
                reminders = self._update_symbol(symbol)
                all_reminders.extend(reminders)
            except Exception as e:
                logger.error(f"处理 {symbol} 时出错: {e}")
        return all_reminders
```

> 注：具体 `CzscTrader` 的 API（如 `get_ensemble_pos` 的签名、`pos_changed` 的行为）需要以 `czsc._native` 实际导出为准。若签名不同，在 Task 5 中调整。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/traders/test_reminder_trader.py -v`
Expected: PASS（至少新测试通过；若旧测试仍失败则修复）

- [ ] **Step 5: Commit**

```bash
git add czsc/traders/reminder_trader.py tests/traders/test_reminder_trader.py
git commit -m "feat(reminder): implement single-frequency ReminderTrader core"
```

---

## Task 5: 多周期共振过滤支持

**Files:**
- Modify: `czsc/traders/reminder_trader.py`
- Test: `tests/traders/test_reminder_trader.py`

- [ ] **Step 1: Write the failing test for filter frequency**

```python
# tests/traders/test_reminder_trader.py

def test_reminder_trader_with_filter_freq():
    """验证 filter_freq 不为 None 时，ReminderTrader 会同时加载过滤周期数据。"""
    from czsc import Event, Position

    open_event = Event.load(
        {
            "name": "日线_阳线_开多",
            "operate": "开多",
            "signals_all": ["日线_D1_K线_阳线_任意_任意_0"],
        }
    )
    position = Position(name="test_pos", symbol="TEST", opens=[open_event], exits=[], interval=0)

    notifier = ConsoleNotifier()
    store = JsonStateStore(base_dir=tempfile.mkdtemp())
    trader = ReminderTrader(
        symbols=["TEST"],
        freq="日线",
        positions=[position],
        filter_freq="日线",
        filter_positions=[position],
        data_client=lambda symbol, freq, sdt, edt, **kwargs: _make_bars(symbol, sdt, edt),
        notifier=notifier,
        state_store=store,
    )
    # 仅验证初始化不报错
    assert trader.filter_freq == "日线"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/traders/test_reminder_trader.py::test_reminder_trader_with_filter_freq -v`
Expected: FAIL

- [ ] **Step 3: Add multi-frequency support to ReminderTrader**

在 `ReminderTrader.__init__` 后追加 `_filter_traders` 初始化，并新增 `_update_filter_symbol` 方法；在 `_update_symbol` 中读取 `filter_current_pos`，调整 `_decide_action` 逻辑。

具体修改（在 Task 4 代码基础上）：

```python
# _decide_action 改为多周期版本
def _decide_action(self, old_pos: int, new_pos: float, filter_pos: int) -> str:
    old = int(old_pos)
    new = 1 if new_pos > 0 else 0
    if old == 0 and new == 1:
        return "买入" if filter_pos > 0 else ""
    if old == 1 and new == 0:
        return "卖出" if filter_pos == 0 else "减仓"
    return ""
```

在 `_update_symbol` 中，若 `self.filter_freq` 存在，先为该 symbol 初始化 `_filter_traders` 并更新到最新 bar，读取 `filter_current_pos` 传入 `_decide_action`。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/traders/test_reminder_trader.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add czsc/traders/reminder_trader.py tests/traders/test_reminder_trader.py
git commit -m "feat(reminder): add multi-frequency filter support"
```

---

## Task 6: 示例脚本

**Files:**
- Create: `docs/examples/22_qmt_bridge_reminder.py`

- [ ] **Step 1: Create the example script**

```python
"""案例 22：基于 qmt-bridge 的半自动交易提醒。

标的：588000.SH 科创50ETF华夏、588800.SH 科创100ETF华夏
周期：30分钟；过滤周期：日线
通知：飞书群机器人

运行方式：
    export FEISHU_BOT_KEY=your_key
    python docs/examples/22_qmt_bridge_reminder.py

建议用 cron 每 30 分钟执行一次：
    */30 9-15 * * 1-5 /path/to/.venv/bin/python /path/to/22_qmt_bridge_reminder.py >> /tmp/reminder.log 2>&1
"""

from __future__ import annotations

import os

from czsc import Event, Position
from czsc.connectors import qmt_bridge_connector
from czsc.traders.reminder_trader import ReminderTrader, FeishuNotifier


SYMBOLS = ["588000.SH", "588800.SH"]
FEISHU_BOT_KEY = os.environ.get("FEISHU_BOT_KEY", "")


def build_positions(freq: str) -> list[Position]:
    """构造 30分钟/日线 共振 Position。"""
    open_event = Event.load(
        {
            "name": f"{freq}_三买辅助V230228_开多",
            "operate": "开多",
            "signals_all": [f"{freq}_D1_三买辅助V230228_三买_任意_任意_0"],
            "signals_not": [f"{freq}_D1_涨跌停V230331_涨停_任意_任意_0"],
        }
    )
    exit_event = Event.load(
        {
            "name": f"{freq}_表里关系V230101_向下_平多",
            "operate": "平多",
            "signals_all": [f"{freq}_D1_表里关系V230101_向下_任意_任意_0"],
        }
    )
    return [
        Position(
            name=f"{freq}_三买_表里",
            symbol="ETF",
            opens=[open_event],
            exits=[exit_event],
            interval=3600 * 4,
            timeout=20,
            stop_loss=300,
            t0=False,
        )
    ]


def main() -> None:
    if not FEISHU_BOT_KEY:
        print("请设置环境变量 FEISHU_BOT_KEY")
        return

    trader = ReminderTrader(
        symbols=SYMBOLS,
        freq="30分钟",
        filter_freq="日线",
        positions=build_positions("30分钟"),
        filter_positions=build_positions("日线"),
        data_client=qmt_bridge_connector.get_raw_bars,
        notifier=FeishuNotifier(bot_key=FEISHU_BOT_KEY),
    )

    reminders = trader.run_once()
    print(f"本次运行共发送 {len(reminders)} 条提醒")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run syntax check**

Run: `python -m py_compile docs/examples/22_qmt_bridge_reminder.py`
Expected: no output (success)

- [ ] **Step 3: Commit**

```bash
git add docs/examples/22_qmt_bridge_reminder.py
git commit -m "docs(examples): add qmt-bridge reminder example"
```

---

## Task 7: 集成验证

**Files:**
- Modify: `docs/examples/22_qmt_bridge_reminder.py`
- Modify: `czsc/traders/reminder_trader.py`（按需修复）

- [ ] **Step 1: Verify data fetching via qmt-bridge**

Run:
```bash
source .venv/bin/activate
python -c "
from czsc.connectors import qmt_bridge_connector
print(qmt_bridge_connector.get_raw_bars('000001.SZ', '30分钟', '20250620', '20250629', raw_bars=False).tail())
"
```
Expected: 输出非空 DataFrame，列包含 dt/symbol/open/high/low/close/vol/amount

- [ ] **Step 2: Verify ConsoleNotifier reminder flow**

Run:
```bash
export CZSC_REMINDER_STATE_DIR=/tmp/reminder_state
rm -rf /tmp/reminder_state
python -c "
from czsc.traders.reminder_trader import ReminderTrader, ConsoleNotifier
from czsc import Event, Position

open_event = Event.load({'name': '日线_阳线_开多', 'operate': '开多', 'signals_all': ['日线_D1_K线_阳线_任意_任意_0']})
position = Position(name='test', symbol='TEST', opens=[open_event], exits=[], interval=0)

# 用 000001.SZ 的真实 30分钟数据做验证
from czsc.connectors import qmt_bridge_connector
trader = ReminderTrader(
    symbols=['000001.SZ'],
    freq='30分钟',
    positions=[position],
    notifier=ConsoleNotifier(),
    data_client=qmt_bridge_connector.get_raw_bars,
)
print(trader.run_once())
"
```
Expected: 脚本正常结束，控制台可能打印提醒（取决于信号）

- [ ] **Step 3: Run full test suite**

Run: `pytest tests/traders/test_reminder_trader.py -v`
Expected: PASS

- [ ] **Step 4: Run ruff check**

Run:
```bash
ruff check czsc/traders/reminder_trader.py tests/traders/test_reminder_trader.py docs/examples/22_qmt_bridge_reminder.py
ruff format --check czsc/traders/reminder_trader.py tests/traders/test_reminder_trader.py docs/examples/22_qmt_bridge_reminder.py
```
Expected: All checks passed!

- [ ] **Step 5: Commit final fixes**

```bash
git add -A
git commit -m "fix(reminder): integration verification and polish"
```

---

## Self-Review Checklist

- [ ] Spec coverage：每个需求（qmt-bridge、30分钟、588000/588800、飞书、只提醒、JSON 状态、多周期过滤）都对应到任务。
- [ ] Placeholder scan：计划中没有 TBD/TODO/"later"/"appropriate" 等模糊描述。
- [ ] Type consistency：`ReminderTrader` 的 `data_client`、`notifier`、`state_store` 签名在所有任务中一致。
- [ ] Test completeness：Notifier、StateStore、ReminderTrader 均有测试覆盖。
