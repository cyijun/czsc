from __future__ import annotations

import os
from abc import ABC, abstractmethod
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
