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
