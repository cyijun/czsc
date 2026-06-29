import tempfile
from unittest.mock import patch

from czsc import Event, Position
from czsc.connectors import qmt_bridge_connector
from czsc.traders.reminder_trader import ConsoleNotifier, FeishuNotifier, JsonStateStore, ReminderTrader


def test_reminder_trader_runs_once_without_error():
    """验证 ReminderTrader.run_once 能正常拉取数据、更新状态并返回 list。"""
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
        symbols=["000001.SZ"],
        freq="日线",
        positions=[position],
        data_client=qmt_bridge_connector.get_raw_bars,
        notifier=notifier,
        state_store=store,
    )
    reminders = trader.run_once()
    assert isinstance(reminders, list)

    # 验证状态被保存
    state = store.load("000001.SZ", "日线")
    assert state["last_bar_dt"] != ""


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


def test_reminder_trader_with_filter_freq():
    """验证 filter_freq 配置能正常初始化并执行。"""
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
        symbols=["000001.SZ"],
        freq="日线",
        positions=[position],
        filter_freq="日线",
        filter_positions=[position],
        data_client=qmt_bridge_connector.get_raw_bars,
        notifier=notifier,
        state_store=store,
    )
    reminders = trader.run_once()
    assert isinstance(reminders, list)
    assert trader.filter_freq == "日线"
