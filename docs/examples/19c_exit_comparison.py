"""案例 19c：三买策略退出规则对比（本地分钟数据）

对比 5 种退出规则：
1. baseline：笔向下（表里关系V230101_向下）
2. fixed_10：固定持有 10 根 30 分钟 K 线后平仓
3. fixed_20：固定持有 20 根 30 分钟 K 线后平仓
4. stop_300：止损 300 元（与 baseline 同止损）
5. stop_150：止损 150 元（更紧止损）

运行：
    python docs/examples/19c_exit_comparison.py

产物：
    docs/examples/_output/19c_exit_comparison/stats_table.csv
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

OUTPUT_DIR = Path(__file__).resolve().parent / "_output" / "19c_exit_comparison"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

BASE_FREQ = "30分钟"
FEE_RATE = 0.0002

_OPEN_EVENT = f"{BASE_FREQ}_D1_三买辅助V230228_三买_任意_任意_0"
_NOT_ZT = f"{BASE_FREQ}_D1_涨跌停V230331_涨停_任意_任意_0"
_EXIT_BI_DOWN = f"{BASE_FREQ}_D1_表里关系V230101_向下_任意_任意_0"


def build_position(
    symbol: str,
    exit_rule: str,
    stop_loss: float = 300.0,
) -> Position:
    """根据 exit_rule 构造 Position。

    exit_rule:
        - "baseline"      : 笔向下平仓
        - "fixed_10"      : 固定持有 10 根 K 线后平仓（timeout=10）
        - "fixed_20"      : 固定持有 20 根 K 线后平仓（timeout=20）
        - "stop_300"      : 同 baseline 但止损 300
        - "stop_150"      : 同 baseline 但止损 150
    """
    open_event = Event.load(
        {
            "name": "三买V230228_开多",
            "operate": "开多",
            "signals_all": [_OPEN_EVENT],
            "signals_not": [_NOT_ZT],
        }
    )

    if exit_rule in ("baseline", "stop_300", "stop_150"):
        exit_event = Event.load(
            {
                "name": "笔向下_平多",
                "operate": "平多",
                "signals_all": [_EXIT_BI_DOWN],
            }
        )
        exits = [exit_event]
    elif exit_rule in ("fixed_10", "fixed_20"):
        # 固定持有期：不依赖信号平仓，靠 timeout 强制平仓
        exits = []
    else:
        raise ValueError(f"unknown exit_rule: {exit_rule}")

    timeout = {"fixed_10": 10, "fixed_20": 20}.get(exit_rule, 16 * 30)
    sl = {"stop_150": 150.0}.get(exit_rule, stop_loss)

    return Position(
        name=f"30min_三买_{exit_rule}",
        symbol=symbol,
        opens=[open_event],
        exits=exits,
        interval=3600 * 4,
        timeout=timeout,
        stop_loss=sl,
        t0=False,
    )


class ExitCompareStrategy(CzscStrategyBase):
    """根据 exit_rule 参数化退出规则。"""

    def __init__(self, symbol: str, exit_rule: str, stop_loss: float = 300.0) -> None:
        super().__init__(symbol=symbol)
        self._exit_rule = exit_rule
        self._stop_loss = stop_loss

    @property
    def symbol(self) -> str:
        return self.kwargs["symbol"]

    @property
    def positions(self) -> list[Position]:
        return [build_position(self.symbol, self._exit_rule, self._stop_loss)]


def holds_to_weight_df(holds: pd.DataFrame) -> pd.DataFrame:
    df = holds[["dt", "symbol", "pos", "price"]].rename(columns={"pos": "weight"})
    if df.duplicated(subset=["dt", "symbol"]).any():
        df = df.groupby(["dt", "symbol"], as_index=False).agg(
            weight=("weight", "mean"),
            price=("price", "first"),
        )
    return df[["dt", "symbol", "weight", "price"]]


def run_one(
    tag: str,
    strategy: CzscStrategyBase,
    bars: list,
    sdt_bt: str,
) -> dict[str, float]:
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

    out_html = OUTPUT_DIR / f"{tag}.html"
    generate_backtest_report(
        df=dfw,
        output_path=str(out_html),
        title=f"案例 19c - {tag} 回测报告",
        fee_rate=FEE_RATE,
        weight_type="ts",
        yearly_days=252,
    )
    print(f"  [{tag}] HTML 报告: {out_html}  (size={out_html.stat().st_size:,} bytes)")
    return wb.stats


def run_period(
    period_label: str,
    sdt_data: str,
    edt_data: str,
    sdt_bt: str,
) -> pd.DataFrame:
    """对同一数据段跑 5 种退出规则，返回 stats DataFrame（index=指标, columns=规则）。"""
    symbol = "510300.SH"
    print(f"\n{'='*60}")
    print(f"[数据] {period_label}: {symbol} {BASE_FREQ} {sdt_data}~{edt_data}  backtest_sdt={sdt_bt}")
    bars = get_etf_bars(
        symbol=symbol,
        freq=BASE_FREQ,
        sdt=sdt_data,
        edt=edt_data,
        raw_bars=True,
    )
    print(f"[数据] 共 {len(bars)} 根；{bars[0].dt} ~ {bars[-1].dt}")

    exit_rules = ["baseline", "fixed_10", "fixed_20", "stop_300", "stop_150"]
    stats_map: dict[str, dict[str, float]] = {}
    for rule in exit_rules:
        tag = f"{period_label}_{rule}"
        strategy = ExitCompareStrategy(symbol=symbol, exit_rule=rule)
        stats_map[rule] = run_one(tag, strategy, bars, sdt_bt)

    df = pd.DataFrame(stats_map)
    df.index.name = "指标"
    return df


def main() -> None:
    # 第一段：2020-2024
    df1 = run_period(
        period_label="2020_2024",
        sdt_data="20200101",
        edt_data="20241231",
        sdt_bt="2020-07-01",
    )

    # 第二段：2024-2025
    df2 = run_period(
        period_label="2024_2025",
        sdt_data="20220101",
        edt_data="20251231",
        sdt_bt="2024-01-01",
    )

    # 合并打印
    print("\n" + "=" * 80)
    print("=== 退出规则对比：2020-2024 ===")
    print(df1.to_string())
    print("\n=== 退出规则对比：2024-2025 ===")
    print(df2.to_string())

    # 保存 CSV
    csv_path = OUTPUT_DIR / "stats_table.csv"
    combined = pd.concat([df1.add_suffix("_2020_2024"), df2.add_suffix("_2024_2025")], axis=1)
    combined.to_csv(csv_path)
    print(f"\n[完成] CSV 已保存: {csv_path}")
    print(f"[完成] HTML 报告目录: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
