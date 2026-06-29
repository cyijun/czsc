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
from czsc.traders.reminder_trader import FeishuNotifier, ReminderTrader

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
