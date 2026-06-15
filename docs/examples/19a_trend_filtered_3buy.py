"""案例 19a：趋势过滤三买策略回测（本地分钟数据）

对比两种配置：
(a) 原始单三买事件（baseline）
(b) 三买 + 趋势过滤（笔向上）

覆盖两个时间窗口：
- 2020-01-01 ~ 2024-12-31，回测起点 2020-07-01
- 2022-01-01 ~ 2025-12-31，回测起点 2024-01-01

运行：
    python docs/examples/19a_trend_filtered_3buy.py

产物：
    docs/examples/_output/19a_trend_filtered_3buy/
        └── *.html
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

OUTPUT_DIR = Path(__file__).resolve().parent / "_output" / "19a_trend_filtered_3buy"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

BASE_FREQ = "30分钟"
FEE_RATE = 0.0002

_EXIT_SIG_BI_DOWN = f"{BASE_FREQ}_D1_表里关系V230101_向下_任意_任意_0"
_NOT_SIG_ZHANGTING = f"{BASE_FREQ}_D1_涨跌停V230331_涨停_任意_任意_0"
_SIG_THIRD_BUY = f"{BASE_FREQ}_D1_三买辅助V230228_三买_任意_任意_0"
_SIG_BI_UP = f"{BASE_FREQ}_D1_表里关系V230101_向上_任意_任意_0"


def build_baseline_position(symbol: str) -> Position:
    """30 分钟纯笔三买开多 + 笔向下平多。"""
    open_event = Event.load(
        {
            "name": "三买V230228_开多",
            "operate": "开多",
            "signals_all": [_SIG_THIRD_BUY],
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
        name="30min_三买_baseline",
        symbol=symbol,
        opens=[open_event],
        exits=[exit_event],
        interval=3600 * 4,
        timeout=16 * 30,
        stop_loss=300,
        t0=False,
    )


def build_trend_filtered_position(symbol: str) -> Position:
    """30 分钟三买 + 笔向上趋势过滤 开多 + 笔向下平多。"""
    open_event = Event.load(
        {
            "name": "三买V230228_趋势过滤_开多",
            "operate": "开多",
            "signals_all": [_SIG_THIRD_BUY, _SIG_BI_UP],
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
        name="30min_三买_趋势过滤",
        symbol=symbol,
        opens=[open_event],
        exits=[exit_event],
        interval=3600 * 4,
        timeout=16 * 30,
        stop_loss=300,
        t0=False,
    )


class BaselineStrategy(CzscStrategyBase):
    """原始单 Event 三买策略。"""

    @property
    def positions(self) -> list[Position]:
        return [build_baseline_position(self.symbol)]


class TrendFilteredStrategy(CzscStrategyBase):
    """趋势过滤三买策略。"""

    @property
    def positions(self) -> list[Position]:
        return [build_trend_filtered_position(self.symbol)]


def holds_to_weight_df(holds: pd.DataFrame) -> pd.DataFrame:
    """把 ResearchResult.holds_df() 转成 wbt 期望的权重表。"""
    df = holds[["dt", "symbol", "pos", "price"]].rename(columns={"pos": "weight"})
    if df.duplicated(subset=["dt", "symbol"]).any():
        df = df.groupby(["dt", "symbol"], as_index=False).agg(
            weight=("weight", "mean"),
            price=("price", "first"),
        )
    df["weight"] = df["weight"].astype("float64")
    df["price"] = df["price"].astype("float64")
    return df[["dt", "symbol", "weight", "price"]]


def run_one(tag: str, strategy: CzscStrategyBase, bars: list, sdt_bt: str) -> dict[str, float]:
    """跑一遍 backtest -> wbt -> HTML 报告，返回 stats 摘要。"""
    print(f"\n=== [{tag}] 开始回测 ===")
    print(f"  symbol     = {strategy.symbol}")
    print(f"  base_freq  = {strategy.base_freq} | freqs = {strategy.freqs}")
    print(f"  sdt_bt     = {sdt_bt}")

    res = strategy.backtest(bars, sdt=sdt_bt)
    pairs = res.pairs_df()
    holds = res.holds_df()
    print(f"  bars={len(bars)} pairs.shape={pairs.shape} holds.shape={holds.shape}")

    dfw = holds_to_weight_df(holds)
    wb = WeightBacktest(data=dfw, fee_rate=FEE_RATE, weight_type="ts", yearly_days=252)

    out_html = OUTPUT_DIR / f"{tag}.html"
    generate_backtest_report(
        df=dfw,
        output_path=str(out_html),
        title=f"案例 19a - {tag} 回测报告（本地分钟数据）",
        fee_rate=FEE_RATE,
        weight_type="ts",
        yearly_days=252,
    )
    print(f"  [{tag}] HTML 报告: {out_html}  (size={out_html.stat().st_size:,} bytes)")
    return wb.stats


def extract_stats(stats: dict[str, float]) -> dict[str, float]:
    """提取关键指标用于对比表格。"""
    key_map = {
        "annual_return": "年化收益",
        "sharpe": "夏普比率",
        "calmar": "卡玛比率",
        "max_drawdown": "最大回撤",
        "win_rate": "交易胜率",
        "trade_count": "交易次数",
    }
    return {k: stats.get(v, float("nan")) for k, v in key_map.items()}


def main() -> None:
    periods = [
        ("2020_full", "20200101", "20241231", "2020-07-01"),
        ("2024_2025", "20220101", "20251231", "2024-01-01"),
    ]

    all_rows: list[dict] = []

    for period_tag, sdt_data, edt_data, sdt_bt in periods:
        print(f"\n{'='*60}")
        print(f"[数据] 读取 510300.SH {BASE_FREQ} 数据 {sdt_data} ~ {edt_data}")
        bars = get_etf_bars(
            symbol="510300.SH",
            freq=BASE_FREQ,
            sdt=sdt_data,
            edt=edt_data,
            raw_bars=True,
        )
        print(f"[数据] 共 {len(bars)} 根；{bars[0].dt} ~ {bars[-1].dt}")

        for cfg_name, StrategyCls in [
            ("baseline", BaselineStrategy),
            ("trend_filtered", TrendFilteredStrategy),
        ]:
            strategy = StrategyCls(symbol="510300.SH")
            tag = f"{period_tag}_{cfg_name}"
            stats = run_one(tag, strategy, bars, sdt_bt)
            row = extract_stats(stats)
            row["period"] = period_tag
            row["config"] = cfg_name
            all_rows.append(row)

    df_cmp = pd.DataFrame(all_rows)
    df_cmp = df_cmp[["period", "config", "annual_return", "sharpe", "calmar", "max_drawdown", "win_rate", "trade_count"]]
    df_cmp = df_cmp.sort_values(["period", "config"]).reset_index(drop=True)

    print("\n" + "=" * 60)
    print("=== 趋势过滤三买 绩效对比 ===")
    print(df_cmp.to_string(index=False))
    print("=" * 60)
    print("\n[完成] HTML 报告全部生成到：", OUTPUT_DIR)


if __name__ == "__main__":
    main()
