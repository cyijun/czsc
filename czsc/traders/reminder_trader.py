from __future__ import annotations

from abc import ABC, abstractmethod
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
