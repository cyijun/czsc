import tempfile
from pathlib import Path
from unittest.mock import patch

from czsc.traders.reminder_trader import ConsoleNotifier, FeishuNotifier, JsonStateStore


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
