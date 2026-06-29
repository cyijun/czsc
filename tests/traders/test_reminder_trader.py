from unittest.mock import patch

from czsc.traders.reminder_trader import ConsoleNotifier, FeishuNotifier


def test_console_notifier_records_message():
    notifier = ConsoleNotifier()
    notifier.send("title", "body", {"symbol": "588000.SH", "action": "买入"})
    assert len(notifier.messages) == 1
    msg = notifier.messages[0]
    assert msg["title"] == "title"
    assert msg["body"] == "body"
    assert msg["metadata"]["action"] == "买入"


def test_feishu_notifier_calls_push_text():
    notifier = FeishuNotifier(bot_key="test_key")
    with patch("czsc.traders.reminder_trader.push_text") as mock_push:
        notifier.send("title", "body", {"symbol": "588000.SH"})
        mock_push.assert_called_once()
        text = mock_push.call_args[0][0]
        assert "title" in text
        assert "body" in text
        assert "588000.SH" in text
