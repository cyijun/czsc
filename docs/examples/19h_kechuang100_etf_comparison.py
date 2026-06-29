"""案例 19h：科创100ETF（华夏 vs 易方达）回测对比

对比两只科创100ETF在同样三买策略下的表现：
- 588800.SH  科创100ETF华夏
- 588210.SH  科创100ETF易方达

策略：
1. 30min_baseline     : 笔向下平仓
2. 30min_fixed20      : 固定持有 20 根 30 分钟 K 线
3. 30_60_fixed20      : 30 分钟 + 60 分钟共振，均 fixed20

产物：
    docs/examples/_output/19h_kechuang100_etf_comparison/*.html
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from wbt import WeightBacktest, generate_backtest_report

from czsc import CzscStrategyBase, Event, Position
from czsc.connectors.etf_min_connector import get_raw_bars as get_etf_bars

OUTPUT_DIR = Path(__file__).resolve().parent / "_output" / "19h_kechuang100_etf_comparison"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

FEE_RATE = 0.0002
YEARLY_DAYS = 252
SYMBOLS = ["588800.SH", "588210.SH"]


def _build_position(symbol: str, base_freq: str, timeout: int) -> Position:
    """构造三买开多 Position；timeout == 16*30 表示用笔向下信号平仓。"""
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
    use_timeout = timeout != 16 * 30
    return Position(
        name=f"{base_freq}_{'fixed' + str(timeout) if use_timeout else 'baseline'}",
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
    print(f"  symbol     = {strategy.symbol}")
    print(f"  base_freq  = {strategy.base_freq} | freqs = {strategy.freqs}")

    res = strategy.backtest(bars, sdt=sdt_bt)
    pairs = res.pairs_df()
    holds = res.holds_df()
    print(f"  bars={len(bars)} pairs.shape={pairs.shape} holds.shape={holds.shape}")

    dfw = holds_to_weight_df(holds)
    wb = WeightBacktest(data=dfw, fee_rate=FEE_RATE, weight_type="ts", yearly_days=YEARLY_DAYS)
    print(f"  [{tag}] 核心绩效指标：")
    for k, v in wb.stats.items():
        print(f"    {k}: {v}")

    out_html = OUTPUT_DIR / f"{tag}.html"
    generate_backtest_report(
        df=dfw,
        output_path=str(out_html),
        title=f"案例 19h - {tag} 回测报告",
        fee_rate=FEE_RATE,
        weight_type="ts",
        yearly_days=YEARLY_DAYS,
    )
    print(f"  [{tag}] HTML 报告: {out_html}  (size={out_html.stat().st_size:,} bytes)")
    return dict(wb.stats)


def run_symbol(symbol: str, sdt_data: str, edt_data: str, sdt_bt: str) -> pd.DataFrame:
    print(f"\n{'='*60}")
    print(f"[数据] {symbol} 30分钟 {sdt_data}~{edt_data}  backtest_sdt={sdt_bt}")
    bars = get_etf_bars(symbol, "30分钟", sdt_data, edt_data, raw_bars=True)
    print(f"[数据] 共 {len(bars)} 根；{bars[0].dt} ~ {bars[-1].dt}")

    stats_map: dict[str, dict[str, float]] = {}
    for StrategyCls, name in [
        (Baseline30Strategy, "30min_baseline"),
        (Fixed20_30Strategy, "30min_fixed20"),
        (ResonanceFixed20Strategy, "30_60_fixed20"),
    ]:
        tag = f"{symbol.replace('.', '_')}_{name}"
        strategy = StrategyCls(symbol=symbol)
        stats_map[name] = run_one(tag, strategy, bars, sdt_bt)

    df = pd.DataFrame(stats_map)
    df.index.name = "指标"
    return df


def main() -> None:
    sdt_data, edt_data, sdt_bt = "20240101", "20260612", "2025-01-01"

    all_stats: dict[str, pd.DataFrame] = {}
    for symbol in SYMBOLS:
        all_stats[symbol] = run_symbol(symbol, sdt_data, edt_data, sdt_bt)

    print("\n" + "=" * 80)
    for symbol, df in all_stats.items():
        print(f"\n=== {symbol} 策略对比 ===")
        print(df.round(4).to_string())

    csv_path = OUTPUT_DIR / "stats_table.csv"
    combined = pd.concat(
        [df.add_suffix(f"_{symbol.replace('.', '_')}") for symbol, df in all_stats.items()],
        axis=1,
    )
    combined.to_csv(csv_path)
    print(f"\n[完成] CSV 已保存: {csv_path}")
    print(f"[完成] HTML 报告目录: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
