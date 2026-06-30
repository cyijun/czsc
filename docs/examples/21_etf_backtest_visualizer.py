"""案例 21b：用 BacktestVisualizer 可视化回测 ETF 筛选报告标的

基于 ``19k_all_3buy_strategies_etf.py`` 的 best_per_symbol.csv，
对每只 ETF 的最优策略跑一遍 ``BacktestVisualizer``，同时输出：

- ``{symbol}_{strategy}_report.html``：wbt 绩效报告
- ``{symbol}_{strategy}_日线_chart.html``：日线 lightweight-charts 交易点位图

运行：
    uv run --no-sync python docs/examples/21_etf_backtest_visualizer.py

产物：
    docs/examples/_output/21_etf_backtest_visualizer/
        ├── stats.csv
        ├── 588200.SH_fixed_20_report.html
        ├── 588200.SH_fixed_20_日线_chart.html
        └── ...
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd

from czsc.connectors.etf_min_connector import get_raw_bars as get_etf_bars
from czsc.utils.plotting.backtest_visualizer import BacktestVisualizer

OUTPUT_DIR = Path(__file__).resolve().parent / "_output" / "21_etf_backtest_visualizer"

# 复用 19k 的策略构造器和参数
_K19_PATH = Path(__file__).resolve().parent / "19k_all_3buy_strategies_etf.py"
_spec = importlib.util.spec_from_file_location("_k19", _K19_PATH)
_k19 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_k19)


def main() -> None:
    best_csv = Path(__file__).resolve().parent / "_output" / "19k_all_3buy_strategies_etf" / "best_per_symbol.csv"
    if not best_csv.exists():
        raise FileNotFoundError(f"请先运行 19k_all_3buy_strategies_etf.py 生成 {best_csv}")

    best_df = pd.read_csv(best_csv)
    strategy_map = dict(_k19.STRATEGIES)

    viz = BacktestVisualizer(
        fee_rate=_k19.FEE_RATE,
        weight_type="ts",
        yearly_days=_k19.YEARLY_DAYS,
        output_dir=OUTPUT_DIR,
        theme="light",
        chart_freq="日线",
        tail_bars=None,
    )

    all_stats: list[dict] = []
    for _, row in best_df.iterrows():
        symbol = row["symbol"]
        strategy_name = row["strategy"]
        StrategyCls = strategy_map[strategy_name]
        tag = f"{symbol}_{strategy_name}"

        print(f"\n{'=' * 60}")
        print(f"标的: {symbol} | 策略: {strategy_name}")
        print(f"{'=' * 60}")

        bars = get_etf_bars(symbol, _k19.BASE_FREQ, _k19.SDT_DATA, _k19.EDT_DATA, raw_bars=True)
        if not bars:
            print(f"[warn] {symbol} 无数据，跳过")
            continue
        print(f"[数据] {bars[0].symbol} {bars[0].freq} 共 {len(bars)} 根；{bars[0].dt} ~ {bars[-1].dt}")

        res = viz.run(tag, StrategyCls(symbol=symbol), bars, sdt=_k19.SDT_BT)
        stats_row = {"symbol": symbol, "strategy": strategy_name}
        stats_row.update(res["stats"])
        all_stats.append(stats_row)

        for name, path in res["outputs"].items():
            print(f"  {name}: {path}")

    if all_stats:
        summary_df = pd.DataFrame(all_stats)
        summary_csv = OUTPUT_DIR / "stats.csv"
        summary_df.to_csv(summary_csv, index=False, float_format="%.6f")
        print(f"\n[汇总] 绩效表已保存: {summary_csv}")
        print(
            summary_df[["symbol", "strategy", "年化收益", "夏普比率", "卡玛比率", "最大回撤", "交易胜率"]].to_string(
                index=False
            )
        )

    print(f"\n[完成] 全部产物已保存到：{OUTPUT_DIR}")


if __name__ == "__main__":
    main()
