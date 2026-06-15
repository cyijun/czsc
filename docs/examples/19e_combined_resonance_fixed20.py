"""案例 19e：多周期共振 + 固定持仓 20 根 K 线 组合

把案例 19b 的多周期共振和案例 19c 的 fixed_20 出场结合起来，
覆盖到 2026 年数据，并加入隆基绿能、澜起科技两只个股做对比。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from wbt import WeightBacktest

from czsc import CzscStrategyBase, Event, Position
from czsc.connectors.etf_min_connector import get_raw_bars as get_etf_bars
from czsc.connectors.etf_min_connector import get_symbols as get_etf_symbols
from czsc.connectors.stock_min_connector import get_raw_bars as get_stock_bars

OUTPUT_DIR = Path(__file__).resolve().parent / "_output" / "19e_combined_resonance_fixed20"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

FEE_RATE = 0.0002

SYMBOLS = ["510300.SH", "601012.SH", "688008.SH"]


def get_bars(symbol: str, sdt: str, edt: str):
    etf_set = set(get_etf_symbols())
    if symbol in etf_set:
        return get_etf_bars(symbol, "30分钟", sdt, edt, raw_bars=True)
    return get_stock_bars(symbol, "30分钟", sdt, edt, raw_bars=True)


def _build_position(symbol: str, base_freq: str, timeout: int) -> Position:
    """构造 三买 开多 Position；timeout 控制固定持仓 K 线数。"""
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
    # timeout != 16*30 时，表示采用固定持仓；否则使用笔向下信号平仓
    use_timeout = timeout != 16 * 30
    return Position(
        name=f"{base_freq}_三买_{'fixed' + str(timeout) if use_timeout else 'baseline'}",
        symbol=symbol,
        opens=[open_event],
        exits=[] if use_timeout else [exit_event],
        interval=3600 * 4,
        timeout=timeout,
        stop_loss=300,
        t0=False,
    )


class Baseline30Strategy(CzscStrategyBase):
    """30 分钟 baseline：笔向下平仓。"""

    @property
    def positions(self) -> list[Position]:
        return [_build_position(self.symbol, "30分钟", 16 * 30)]


class Fixed20_30Strategy(CzscStrategyBase):
    """30 分钟 + 固定持有 20 根 K 线。"""

    @property
    def positions(self) -> list[Position]:
        return [_build_position(self.symbol, "30分钟", 20)]


class ResonanceFixed20Strategy(CzscStrategyBase):
    """30 分钟 + 60 分钟共振，均固定持有 20 根 K 线。"""

    @property
    def positions(self) -> list[Position]:
        return [
            _build_position(self.symbol, "30分钟", 20),
            _build_position(self.symbol, "60分钟", 20),
        ]


def holds_to_weight_df(holds: pd.DataFrame) -> pd.DataFrame:
    df = holds[["dt", "symbol", "pos", "price"]].rename(columns={"pos": "weight"})
    if df.duplicated(subset=["dt", "symbol"]).any():
        df = df.groupby(["dt", "symbol"], as_index=False).agg(
            weight=("weight", "mean"),
            price=("price", "first"),
        )
    return df[["dt", "symbol", "weight", "price"]]


def run_one(tag: str, strategy: CzscStrategyBase, bars: list, sdt_bt: str) -> dict[str, float]:
    print(f"\n=== [{tag}] 开始回测 ===")
    print(f"  base_freq  = {strategy.base_freq} | freqs = {strategy.freqs}")

    res = strategy.backtest(bars, sdt=sdt_bt)
    holds = res.holds_df()
    dfw = holds_to_weight_df(holds)
    wb = WeightBacktest(data=dfw, fee_rate=FEE_RATE, weight_type="ts", yearly_days=252)
    print(f"  [{tag}] 核心绩效指标：")
    for k, v in wb.stats.items():
        print(f"    {k}: {v}")
    return wb.stats


def run_window(symbol: str, sdt_data: str, edt_data: str, sdt_bt: str) -> dict[str, dict[str, float]]:
    print(f"\n数据窗口: {symbol} {sdt_data} ~ {edt_data} | 回测起点: {sdt_bt}")
    bars = get_bars(symbol, sdt_data, edt_data)
    print(f"[数据] {symbol} 30分钟 共 {len(bars)} 根；{bars[0].dt} ~ {bars[-1].dt}")

    stats = {}
    stats["30min_baseline"] = run_one(f"{symbol}_30min_baseline", Baseline30Strategy(symbol=symbol), bars, sdt_bt)
    stats["30min_fixed20"] = run_one(f"{symbol}_30min_fixed20", Fixed20_30Strategy(symbol=symbol), bars, sdt_bt)
    stats["30_60_fixed20"] = run_one(f"{symbol}_30_60_fixed20", ResonanceFixed20Strategy(symbol=symbol), bars, sdt_bt)
    return stats


def main() -> None:
    periods = [
        ("2020-2026H1", "20200101", "20260612", "2020-07-01"),
        ("2025-2026H1", "20240101", "20260612", "2025-01-01"),
    ]

    all_stats: dict[str, dict[str, float]] = {}
    for symbol in SYMBOLS:
        for label, sdt_data, edt_data, sdt_bt in periods:
            stats = run_window(symbol, sdt_data, edt_data, sdt_bt)
            for k, v in stats.items():
                all_stats[f"{symbol}_{k}_{label}"] = v

    print("\n" + "=" * 60)
    print("汇总对比表")
    print("=" * 60)
    df = pd.DataFrame(all_stats)
    print(df.to_string())

    csv_path = OUTPUT_DIR / "stats_table.csv"
    df.to_csv(csv_path)
    print(f"\n[完成] CSV 已保存: {csv_path}")


if __name__ == "__main__":
    main()
