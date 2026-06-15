"""案例 19：用本地 ETF / A 股分钟连接器跑 Event 三买策略回测

基于案例 14 的真实数据回测模式，改为从本地 parquet 读取分钟数据：
- ETF 数据源：czsc.connectors.etf_min_connector
- A 股数据源：czsc.connectors.stock_min_connector

数据只读，不修改原始 parquet。连接器内部使用 polars lazy 过滤，避免全量加载。

运行：
    uv run --no-sync python docs/examples/19_local_minute_event_backtest.py

产物：
    docs/examples/_output/19_local_minute_event_backtest/
        ├── 510300_SH_30min_single_event.html
        └── 000001_SZ_30min_single_event.html
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from wbt import generate_backtest_report

from czsc import (
    CzscStrategyBase,
    Event,
    Position,
    WeightBacktest,
)
from czsc.connectors.etf_min_connector import get_raw_bars as get_etf_bars
from czsc.connectors.stock_min_connector import get_raw_bars as get_stock_bars

OUTPUT_DIR = Path(__file__).resolve().parent / "_output" / "19_local_minute_event_backtest"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

BASE_FREQ = "30分钟"
SDT_DATA = "20200101"
EDT_DATA = "20241231"
SDT_BT = "2020-07-01"
FEE_RATE = 0.0002

_EXIT_SIG_BI_DOWN = f"{BASE_FREQ}_D1_表里关系V230101_向下_任意_任意_0"
_NOT_SIG_ZHANGTING = f"{BASE_FREQ}_D1_涨跌停V230331_涨停_任意_任意_0"


def build_single_event_position(symbol: str) -> Position:
    """30 分钟纯笔三买（cxt_third_buy_V230228）开多 + 笔向下平多。"""
    open_event = Event.load(
        {
            "name": "三买V230228_开多",
            "operate": "开多",
            "signals_all": [f"{BASE_FREQ}_D1_三买辅助V230228_三买_任意_任意_0"],
            "signals_not": [_NOT_SIG_ZHANGTING],
        }
    )
    exit_event = Event.load(
        {
            "name": "笔向下_平多",
            "operate": "平多",
            "signals_all": [_EXIT_SIG_BI_DOWN],
        }
    )
    return Position(
        name="30min_三买_single",
        symbol=symbol,
        opens=[open_event],
        exits=[exit_event],
        interval=3600 * 4,
        timeout=16 * 30,
        stop_loss=300,
        t0=False,
    )


class SingleEventStrategy(CzscStrategyBase):
    """30 分钟单 Event 三买策略。"""

    @property
    def positions(self) -> list[Position]:
        return [build_single_event_position(self.symbol)]


def holds_to_weight_df(holds: pd.DataFrame) -> pd.DataFrame:
    """把 ResearchResult.holds_df() 转成 wbt 期望的权重表。"""
    df = holds[["dt", "symbol", "pos", "price"]].rename(columns={"pos": "weight"})
    if df.duplicated(subset=["dt", "symbol"]).any():
        df = df.groupby(["dt", "symbol"], as_index=False).agg(
            weight=("weight", "mean"),
            price=("price", "first"),
        )
    return df[["dt", "symbol", "weight", "price"]]


def run_one(tag: str, strategy: CzscStrategyBase, bars: list) -> dict[str, float]:
    """跑一遍 backtest -> wbt -> HTML 报告，返回 stats 摘要。"""
    print(f"\n=== [{tag}] 开始回测 ===")
    print(f"  symbol     = {strategy.symbol}")
    print(f"  base_freq  = {strategy.base_freq} | freqs = {strategy.freqs}")

    res = strategy.backtest(bars, sdt=SDT_BT)
    pairs = res.pairs_df()
    holds = res.holds_df()
    print(f"  bars={len(bars)} pairs.shape={pairs.shape} holds.shape={holds.shape}")

    dfw = holds_to_weight_df(holds)
    wb = WeightBacktest(data=dfw, fee_rate=FEE_RATE, weight_type="ts", yearly_days=252)
    print(f"  [{tag}] 核心绩效指标：")
    for k, v in wb.stats.items():
        print(f"    {k}: {v}")

    out_html = OUTPUT_DIR / f"{tag}.html"
    generate_backtest_report(
        df=dfw,
        output_path=str(out_html),
        title=f"案例 19 - {tag} 回测报告（本地分钟数据）",
        fee_rate=FEE_RATE,
        weight_type="ts",
        yearly_days=252,
    )
    print(f"  [{tag}] HTML 报告: {out_html}  (size={out_html.stat().st_size:,} bytes)")
    return wb.stats


def main() -> None:
    cases = [
        ("510300_SH_30min_single_event", "510300.SH", get_etf_bars),
        ("000001_SZ_30min_single_event", "000001.SZ", get_stock_bars),
    ]

    all_stats: dict[str, dict[str, float]] = {}
    for tag, symbol, get_bars in cases:
        print(f"\n[数据] 正在从本地 parquet 读取 {symbol} {BASE_FREQ} K 线...")
        bars = get_bars(
            symbol=symbol,
            freq=BASE_FREQ,
            sdt=SDT_DATA,
            edt=EDT_DATA,
            raw_bars=True,
        )
        print(f"[数据] {bars[0].symbol} {bars[0].freq} 共 {len(bars)} 根；{bars[0].dt} ~ {bars[-1].dt}")

        strategy = SingleEventStrategy(symbol=symbol)
        all_stats[tag] = run_one(tag, strategy, bars)

    cmp = pd.DataFrame(all_stats)
    print("\n=== 本地分钟数据 三买绩效对比 ===")
    print(cmp.to_string())
    print("\n[完成] HTML 报告全部生成到：", OUTPUT_DIR)


if __name__ == "__main__":
    main()
