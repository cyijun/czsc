from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from datetime import timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from loguru import logger

import czsc
from czsc.connectors import qmt_bridge_connector
from czsc.fsa import push_text


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
        sdt = pd.to_datetime(last_dt) if last_dt else pd.Timestamp.now() - pd.Timedelta(days=self.lookback)
        edt = pd.Timestamp.now() + pd.Timedelta(days=1)
        bars = self.data_client(symbol, freq, sdt.strftime("%Y%m%d"), edt.strftime("%Y%m%d"))
        if isinstance(bars, pd.DataFrame):
            bars = czsc.format_standard_kline(bars, freq=freq)
        return bars

    def _update_symbol(self, symbol: str) -> list[dict[str, Any]]:
        reminders: list[dict[str, Any]] = []
        filter_pos = self._update_filter_symbol(symbol)

        bars = self._load_bars(symbol, self.freq)
        if not bars:
            logger.warning(f"{symbol} 无 {self.freq} 数据")
            return reminders

        if symbol not in self._traders:
            self._traders[symbol] = self._init_trader(symbol, self.freq, self.positions)
        trader = self._traders[symbol]

        state = self.state_store.load(symbol, self.freq)
        last_dt_str = state.get("last_bar_dt", "")
        last_dt = pd.to_datetime(last_dt_str) if last_dt_str else pd.Timestamp.min

        for bar in bars:
            if bar.dt <= last_dt:
                continue
            trader.update(bar)
            if trader.pos_changed:
                new_pos = trader.get_ensemble_pos()
                action = self._decide_action(state["current_pos"], new_pos, filter_pos)
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

    def _update_filter_symbol(self, symbol: str) -> int:
        """更新过滤周期 trader，返回当前 filter 仓位。"""
        if not self.filter_freq or not self.filter_positions:
            return 1

        bars = self._load_bars(symbol, self.filter_freq)
        if symbol not in self._filter_traders:
            self._filter_traders[symbol] = self._init_trader(symbol, self.filter_freq, self.filter_positions)
        trader = self._filter_traders[symbol]

        state = self.state_store.load(symbol, self.filter_freq)
        last_dt_str = state.get("last_bar_dt", "")
        last_dt = pd.to_datetime(last_dt_str) if last_dt_str else pd.Timestamp.min

        current_pos = state.get("current_pos", 0)
        for bar in bars:
            if bar.dt <= last_dt:
                continue
            trader.update(bar)
            if trader.pos_changed:
                current_pos = 1 if trader.get_ensemble_pos() > 0 else 0
            last_dt = max(last_dt, pd.to_datetime(bar.dt))

        state["last_bar_dt"] = last_dt.strftime("%Y-%m-%d %H:%M:%S")
        state["current_pos"] = current_pos
        self.state_store.save(symbol, self.filter_freq, state)
        return current_pos

    def _decide_action(self, old_pos: int, new_pos: float, filter_pos: int) -> str:
        old = int(old_pos)
        new = 1 if new_pos > 0 else 0
        if old == 0 and new == 1:
            return "买入" if filter_pos > 0 else ""
        if old == 1 and new == 0:
            return "卖出" if filter_pos == 0 else "减仓"
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
