"""案例 21c：用 QMT Bridge + 本地 parquet 拼接数据回测 5 只 ETF（2026-06 至今）

注意：当前 qmt-vm 上的 QMT Bridge 只有 2026-05-29 起的 30 分钟数据，
不够 ``CzscStrategyBase.backtest`` 做缠论 warm-up。因此本脚本采用：

- 本地 parquet（``/mnt/h/etf_min``）提供 2024-01 至 2026-06-12 的历史数据
- QMT Bridge 补充 2026-06-13 至今的最新数据

对 19k 回测中表现最好的策略跑 ``BacktestVisualizer``：

- 159995.SZ（国证半导体芯片）→ fixed_20
- 512480.SH（中证全指半导体）→ fixed_20
- 515050.SH（中证 5G 通信）   → stop_150
- 515880.SH（全指通信设备）   → fixed_20
- 588200.SH（科创芯片）       → fixed_20

运行：
    uv run --no-sync python docs/examples/21_qmt_backtest_visualizer.py

产物：
    docs/examples/_output/21_qmt_backtest_visualizer/
        ├── stats.csv
        ├── {symbol}_{strategy}_report.html
        └── {symbol}_{strategy}_日线_chart.html
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd

from czsc.connectors.etf_min_connector import get_raw_bars as get_local_bars
from czsc.connectors.qmt_bridge_connector import get_raw_bars as get_qmt_bars
from czsc.utils.plotting.backtest_visualizer import BacktestVisualizer

OUTPUT_DIR = Path(__file__).resolve().parent / "_output" / "21_qmt_backtest_visualizer"

# 复用 19k 的策略构造器和常量
_K19_PATH = Path(__file__).resolve().parent / "19k_all_3buy_strategies_etf.py"
_spec = importlib.util.spec_from_file_location("_k19", _K19_PATH)
_k19 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_k19)

# 数据区间
SDT_LOCAL = "20240101"
EDT_LOCAL = "20260630"
SDT_QMT = "20260529"
EDT_QMT = "20260630"
SDT_BT = "2026-06-01"
BASE_FREQ = "30分钟"
FEE_RATE = _k19.FEE_RATE
YEARLY_DAYS = _k19.YEARLY_DAYS


def _load_best_strategy_map() -> dict[str, str]:
    """从 19k 的 best_per_symbol.csv 读取每只标的最优策略。"""
    best_csv = Path(__file__).resolve().parent / "_output" / "19k_all_3buy_strategies_etf" / "best_per_symbol.csv"
    if not best_csv.exists():
        return {}
    df = pd.read_csv(best_csv)
    return dict(zip(df["symbol"], df["strategy"], strict=False))


def get_combined_bars(symbol: str) -> list:
    """本地 parquet + QMT 拼接，QMT 补充本地数据结束后的最新行情。"""
    local_bars = get_local_bars(symbol, BASE_FREQ, SDT_LOCAL, EDT_LOCAL, raw_bars=True)
    qmt_bars = get_qmt_bars(symbol, BASE_FREQ, SDT_QMT, EDT_QMT, raw_bars=True)

    if not local_bars and not qmt_bars:
        return []

    # 以本地数据为基准，QMT 只取本地最后一条之后的最新数据
    if local_bars and qmt_bars:
        last_local_dt = local_bars[-1].dt
        extra = [b for b in qmt_bars if b.dt > last_local_dt]
        return list(local_bars) + extra

    return list(local_bars or qmt_bars)


def main() -> None:
    symbols = [
        "159995.SZ",  # 国证半导体芯片
        "512480.SH",  # 中证全指半导体
        "515050.SH",  # 中证 5G 通信
        "515880.SH",  # 全指通信设备
        "588200.SH",  # 科创芯片
    ]

    best_strategy_map = _load_best_strategy_map()
    strategy_map = dict(_k19.STRATEGIES)
    default_strategy = "fixed_20"

    viz = BacktestVisualizer(
        fee_rate=FEE_RATE,
        weight_type="ts",
        yearly_days=YEARLY_DAYS,
        output_dir=OUTPUT_DIR,
        theme="light",
        chart_freq="日线",
        tail_bars=None,
    )

    all_stats: list[dict] = []
    for symbol in symbols:
        strategy_name = best_strategy_map.get(symbol, default_strategy)
        StrategyCls = strategy_map[strategy_name]
        tag = f"{symbol}_{strategy_name}"

        print(f"\n{'=' * 60}")
        print(f"标的: {symbol} | 策略: {strategy_name}")
        print(f"{'=' * 60}")

        bars = get_combined_bars(symbol)
        if not bars:
            print(f"[warn] {symbol} 无数据，跳过")
            continue
        print(f"[数据] {bars[0].symbol} {bars[0].freq} 共 {len(bars)} 根；{bars[0].dt} ~ {bars[-1].dt}")

        strategy = StrategyCls(symbol=symbol)
        res = viz.run(tag, strategy, bars, sdt=SDT_BT)

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
