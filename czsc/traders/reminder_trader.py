from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

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
