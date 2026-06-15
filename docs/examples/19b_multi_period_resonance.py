"""案例 19b：多周期共振 三买 策略回测（本地分钟数据）

对比：
- 单周期 baseline：30 分钟
- 多周期共振：30 分钟 + 60 分钟（同一 三买 event）

数据：510300.SH，本地 ETF 分钟 parquet
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from wbt import WeightBacktest

from czsc import CzscStrategyBase, Event, Position
from czsc.connectors.etf_min_connector import get_raw_bars as get_etf_bars

OUTPUT_DIR = Path(__file__).resolve().parent / "_output" / "19b_multi_period_resonance"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

FEE_RATE = 0.0002


def _build_position(symbol: str, base_freq: str) -> Position:
    """给定周期，构造 三买 开多 + 笔向下 平多 Position。"""
    open_event = Event.load(
        {
            "name": f"{base_freq}_三买V230228_开多",
            "operate": "开多",
            "signals_all": [f"{base_freq}_D1_三买辅助V230228_三买_任意_任意_0"],
            "signals_not": [f"{base_freq}_D1_涨跌停V230331_涨停_任意_任意_0"],
        }
    )
    exit_event = Event.load(
        {
            "name": f"{base_freq}_笔向下_平多",
            "operate": "平多",
            "signals_all": [f"{base_freq}_D1_表里关系V230101_向下_任意_任意_0"],
        }
    )
    return Position(
        name=f"{base_freq}_三买",
        symbol=symbol,
        opens=[open_event],
        exits=[exit_event],
        interval=3600 * 4,
        timeout=16 * 30,
        stop_loss=300,
        t0=False,
    )


class SingleFreqStrategy(CzscStrategyBase):
    """单周期 baseline：30 分钟。"""

    @property
    def positions(self) -> list[Position]:
        return [_build_position(self.symbol, "30分钟")]


class MultiFreqResonanceStrategy(CzscStrategyBase):
    """多周期共振：30 分钟 + 60 分钟。"""

    @property
    def positions(self) -> list[Position]:
        return [
            _build_position(self.symbol, "30分钟"),
            _build_position(self.symbol, "60分钟"),
        ]


def holds_to_weight_df(holds: pd.DataFrame) -> pd.DataFrame:
    """把 ResearchResult.holds_df() 转成 wbt 期望的权重表。"""
    df = holds[["dt", "symbol", "pos", "price"]].rename(columns={"pos": "weight"})
    if df.duplicated(subset=["dt", "symbol"]).any():
        df = df.groupby(["dt", "symbol"], as_index=False).agg(
            weight=("weight", "mean"),
            price=("price", "first"),
        )
    return df[["dt", "symbol", "weight", "price"]]


def run_one(tag: str, strategy: CzscStrategyBase, bars: list, sdt_bt: str) -> dict[str, float]:
    """跑一遍 backtest -> wbt，返回 stats 摘要。"""
    print(f"\n=== [{tag}] 开始回测 ===")
    print(f"  symbol     = {strategy.symbol}")
    print(f"  base_freq  = {strategy.base_freq} | freqs = {strategy.freqs}")

    res = strategy.backtest(bars, sdt=sdt_bt)
    pairs = res.pairs_df()
    holds = res.holds_df()
    print(f"  bars={len(bars)} pairs.shape={pairs.shape} holds.shape={holds.shape}")

    dfw = holds_to_weight_df(holds)
    wb = WeightBacktest(data=dfw, fee_rate=FEE_RATE, weight_type="ts", yearly_days=252)
    print(f"  [{tag}] 核心绩效指标：")
    for k, v in wb.stats.items():
        print(f"    {k}: {v}")

    return wb.stats


def run_window(sdt_data: str, edt_data: str, sdt_bt: str) -> dict[str, dict[str, float]]:
    """读取数据并跑两个策略。"""
    print(f"\n{'='*60}")
    print(f"数据窗口: {sdt_data} ~ {edt_data} | 回测起点: {sdt_bt}")
    print(f"{'='*60}")

    # 多周期策略需要以 30 分钟为 base_freq，框架会自动合成 60 分钟
    bars = get_etf_bars(
        symbol="510300.SH",
        freq="30分钟",
        sdt=sdt_data,
        edt=edt_data,
        raw_bars=True,
    )
    print(f"[数据] 510300.SH 30分钟 共 {len(bars)} 根；{bars[0].dt} ~ {bars[-1].dt}")

    stats = {}
    stats["30min_only"] = run_one("30min_only", SingleFreqStrategy(symbol="510300.SH"), bars, sdt_bt)
    stats["30min_60min_resonance"] = run_one(
        "30min_60min_resonance", MultiFreqResonanceStrategy(symbol="510300.SH"), bars, sdt_bt
    )
    return stats


def main() -> None:
    # 窗口 1：2020-2024
    stats1 = run_window("20200101", "20241231", "2020-07-01")

    # 窗口 2：2024-2025
    stats2 = run_window("20220101", "20251231", "2024-01-01")

    # 汇总对比
    print("\n" + "=" * 60)
    print("汇总对比表")
    print("=" * 60)

    for label, stats in [("2020-2024", stats1), ("2024-2025", stats2)]:
        df = pd.DataFrame(stats)
        print(f"\n--- {label} ---")
        print(df.to_string())

    # 合并输出
    all_stats = {}
    for k, v in stats1.items():
        all_stats[f"{k}_2020-2024"] = v
    for k, v in stats2.items():
        all_stats[f"{k}_2024-2025"] = v

    df_all = pd.DataFrame(all_stats)
    print("\n--- 全量对比 ---")
    print(df_all.to_string())

    print("\n[完成] 输出目录：", OUTPUT_DIR)


if __name__ == "__main__":
    main()
