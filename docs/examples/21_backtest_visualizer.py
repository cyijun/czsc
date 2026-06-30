"""案例 21：BacktestVisualizer 一键可视化回测

使用 ``czsc.utils.plotting.backtest_visualizer.BacktestVisualizer`` 把
``CzscStrategyBase`` 回测结果同时输出为：

- ``{tag}_report.html``：wbt 绩效报告（净值 / 回撤 / 收益分布）
- ``{tag}_chart.html``：lightweight-charts 交易点位图（K 线 + 分型 + 笔 + 开平仓箭头）

本案例参考 ``/mnt/h/可视化方法`` 中的三个可视化案例：

- 基于 Event 的策略回测 + wbt HTML 报告
- lightweight_charts 缠论可视化
- 把信号函数画到 K 线主图（这里把开平仓事件当作 marker 画到主图）

运行：
    uv run --no-sync python docs/examples/21_backtest_visualizer.py

产物：
    docs/examples/_output/21_backtest_visualizer/
        ├── single_event_report.html
        ├── single_event_chart.html
        ├── multi_event_report.html
        └── multi_event_chart.html
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from czsc import CzscStrategyBase, Event, Position, format_standard_kline
from czsc.mock import generate_symbol_kines
from czsc.utils.plotting.backtest_visualizer import BacktestVisualizer

OUTPUT_DIR = Path(__file__).resolve().parent / "_output" / "21_backtest_visualizer"

SYMBOL = "000001"
BASE_FREQ = "30分钟"
SDT_DATA = "20220101"
EDT_DATA = "20240301"
SDT_BT = "2022-07-01"
FEE_RATE = 0.0002

_EXIT_SIG_BI_DOWN = f"{BASE_FREQ}_D1_表里关系V230101_向下_任意_任意_0"
_NOT_SIG_ZHANGTING = f"{BASE_FREQ}_D1_涨跌停V230331_涨停_任意_任意_0"


def _build_exit_event() -> Event:
    return Event.load(
        {
            "name": "笔向下_平多",
            "operate": "平多",
            "signals_all": [_EXIT_SIG_BI_DOWN],
        }
    )


def build_single_event_position(symbol: str) -> Position:
    open_event = Event.load(
        {
            "name": "三买V230228_开多",
            "operate": "开多",
            "signals_all": [f"{BASE_FREQ}_D1_三买辅助V230228_三买_任意_任意_0"],
            "signals_not": [_NOT_SIG_ZHANGTING],
        }
    )
    return Position(
        name="30min_三买_single",
        symbol=symbol,
        opens=[open_event],
        exits=[_build_exit_event()],
        interval=3600 * 4,
        timeout=16 * 30,
        stop_loss=300,
        t0=False,
    )


def build_multi_event_position(symbol: str) -> Position:
    opens = [
        Event.load(
            {
                "name": "三买V230228_开多",
                "operate": "开多",
                "signals_all": [f"{BASE_FREQ}_D1_三买辅助V230228_三买_任意_任意_0"],
                "signals_not": [_NOT_SIG_ZHANGTING],
            }
        ),
        Event.load(
            {
                "name": "三买V230318_开多",
                "operate": "开多",
                "signals_all": [f"{BASE_FREQ}_D1#SMA#34_BS3辅助V230318_三买_任意_任意_0"],
                "signals_not": [_NOT_SIG_ZHANGTING],
            }
        ),
    ]
    return Position(
        name="30min_三买_multi",
        symbol=symbol,
        opens=opens,
        exits=[_build_exit_event()],
        interval=3600 * 4,
        timeout=16 * 30,
        stop_loss=300,
        t0=False,
    )


class SingleEventStrategy(CzscStrategyBase):
    @property
    def positions(self) -> list[Position]:
        return [build_single_event_position(self.symbol)]


class MultiEventStrategy(CzscStrategyBase):
    @property
    def positions(self) -> list[Position]:
        return [build_multi_event_position(self.symbol)]


def main() -> None:
    df = generate_symbol_kines(SYMBOL, BASE_FREQ, SDT_DATA, EDT_DATA, seed=42)
    bars = format_standard_kline(df, freq=BASE_FREQ)
    print(f"[数据] {bars[0].symbol} {bars[0].freq} 共 {len(bars)} 根；{bars[0].dt} ~ {bars[-1].dt}")

    viz = BacktestVisualizer(
        fee_rate=FEE_RATE,
        weight_type="ts",
        yearly_days=252,
        output_dir=OUTPUT_DIR,
        theme="light",
        tail_bars=600,
    )

    results: list[dict] = []
    for tag, StrategyCls in (("single_event", SingleEventStrategy), ("multi_event", MultiEventStrategy)):
        strategy = StrategyCls(symbol=SYMBOL)
        res = viz.run(tag, strategy, bars, sdt=SDT_BT)
        results.append({"tag": tag, **res["stats"]})
        print(f"\n=== [{tag}] ===")
        for k, v in res["stats"].items():
            print(f"  {k}: {v}")
        for name, path in res["outputs"].items():
            print(f"  {name}: {path}")

    cmp = pd.DataFrame(results).set_index("tag")
    print("\n=== 绩效对比 ===")
    print(cmp.to_string())
    print(f"\n[完成] 全部产物已保存到：{OUTPUT_DIR}")


if __name__ == "__main__":
    main()
