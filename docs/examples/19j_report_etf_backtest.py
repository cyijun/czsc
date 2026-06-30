"""案例 19j：对 ETF 量化筛选报告推荐标的做本地 parquet 回测

基于案例 19b 的多周期共振思路，对 /mnt/h/ETF量化标的筛选报告.md 中的
核心 + 卫星 + 观察备选 ETF 标的分别跑：
- 30 分钟单周期三买
- 30 分钟 + 60 分钟多周期共振

数据：本地 ETF 分钟 parquet（czsc.connectors.etf_min_connector）

运行：
    uv run --no-sync python docs/examples/19j_report_etf_backtest.py

产物：
    docs/examples/_output/19j_report_etf_backtest/
        ├── stats.csv              # 各标的 × 各策略绩效指标
        └── comparison.html        # wbt 汇总回测报告（等权合成所有标的信号）
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from wbt import WeightBacktest, generate_backtest_report

from czsc import CzscStrategyBase, Event, Position
from czsc.connectors.etf_min_connector import get_raw_bars as get_etf_bars

OUTPUT_DIR = Path(__file__).resolve().parent / "_output" / "19j_report_etf_backtest"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

BASE_FREQ = "30分钟"
SDT_DATA = "20240101"
EDT_DATA = "20260630"
SDT_BT = "2025-07-01"
FEE_RATE = 0.0002
YEARLY_DAYS = 252

# /mnt/h/ETF量化标的筛选报告.md 中的标的
SYMBOLS = [
    # 核心仓位
    "588200.SH",
    "512480.SH",
    # 卫星仓位
    "515880.SH",
    "159819.SZ",
    "159363.SZ",
    # 观察备选
    "515050.SH",
    "159995.SZ",
    "562500.SH",
]


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


def run_one(tag: str, strategy: CzscStrategyBase, bars: list) -> tuple[pd.DataFrame, dict[str, float]]:
    """跑一遍 backtest -> wbt，返回权重表和 stats。"""
    print(f"\n=== [{tag}] 开始回测 ===")
    print(f"  symbol     = {strategy.symbol}")
    print(f"  base_freq  = {strategy.base_freq} | freqs = {strategy.freqs}")

    res = strategy.backtest(bars, sdt=SDT_BT)
    pairs = res.pairs_df()
    holds = res.holds_df()
    print(f"  bars={len(bars)} pairs.shape={pairs.shape} holds.shape={holds.shape}")

    dfw = holds_to_weight_df(holds)
    wb = WeightBacktest(data=dfw, fee_rate=FEE_RATE, weight_type="ts", yearly_days=YEARLY_DAYS)
    print(f"  [{tag}] 核心绩效指标：")
    for k, v in wb.stats.items():
        print(f"    {k}: {v}")

    return dfw, dict(wb.stats)


def run_symbol(symbol: str) -> dict[str, dict[str, float]] | None:
    """读取单个 ETF 数据并跑两个策略。"""
    print(f"\n{'='*60}")
    print(f"标的: {symbol}")
    print(f"{'='*60}")

    try:
        bars = get_etf_bars(
            symbol=symbol,
            freq=BASE_FREQ,
            sdt=SDT_DATA,
            edt=EDT_DATA,
            raw_bars=True,
        )
    except Exception as e:
        print(f"[warn] {symbol} 读取数据失败：{e}")
        return None

    if not bars:
        print(f"[warn] {symbol} 无数据")
        return None

    print(f"[数据] {bars[0].symbol} {bars[0].freq} 共 {len(bars)} 根；{bars[0].dt} ~ {bars[-1].dt}")

    stats = {}
    _, stats["30min_only"] = run_one(
        f"{symbol}_30min_only", SingleFreqStrategy(symbol=symbol), bars
    )
    _, stats["30min_60min_resonance"] = run_one(
        f"{symbol}_30min_60min_resonance", MultiFreqResonanceStrategy(symbol=symbol), bars
    )
    return stats


def main() -> None:
    all_stats: dict[str, dict[str, dict[str, float]]] = {}
    all_weight_dfs: list[pd.DataFrame] = []

    for symbol in SYMBOLS:
        stats = run_symbol(symbol)
        if stats is None:
            continue
        all_stats[symbol] = stats

        # 把多周期共振权重收集起来，合成等权组合报告
        bars = get_etf_bars(
            symbol=symbol,
            freq=BASE_FREQ,
            sdt=SDT_DATA,
            edt=EDT_DATA,
            raw_bars=True,
        )
        strategy = MultiFreqResonanceStrategy(symbol=symbol)
        res = strategy.backtest(bars, sdt=SDT_BT)
        dfw = holds_to_weight_df(res.holds_df())
        all_weight_dfs.append(dfw)

    if not all_stats:
        raise SystemExit("没有任何标的回测成功")

    # 汇总表：symbol × strategy
    rows = []
    for symbol, stats in all_stats.items():
        for strategy_name, metrics in stats.items():
            row = {"symbol": symbol, "strategy": strategy_name}
            row.update(metrics)
            rows.append(row)
    summary_df = pd.DataFrame(rows)
    summary_csv = OUTPUT_DIR / "stats.csv"
    summary_df.to_csv(summary_csv, index=False, float_format="%.6f")
    print(f"\n[汇总] 绩效表已保存: {summary_csv}")
    print(summary_df.to_string(index=False))

    # 等权合成所有标的的多周期共振信号，生成汇总 HTML 报告
    if all_weight_dfs:
        combined = pd.concat(all_weight_dfs, ignore_index=True)
        # 同一时间点多个标的等权分配：先按 symbol 归一化，再按 dt 等权
        combined = combined.sort_values(["dt", "symbol"]).reset_index(drop=True)
        # 单日多标的时，每个标的权重 1/n；后续 wbt 内部会再做组合处理
        combined["daily_weight_sum"] = combined.groupby("dt")["weight"].transform(lambda x: x.abs().sum())
        combined["daily_weight_sum"] = combined["daily_weight_sum"].replace(0, 1.0)
        combined["weight"] = combined["weight"] / combined["daily_weight_sum"]
        combined = combined.drop(columns=["daily_weight_sum"])

        out_html = OUTPUT_DIR / "comparison.html"
        generate_backtest_report(
            df=combined,
            output_path=str(out_html),
            title=f"案例 19j - ETF 筛选标的等权组合回测 ({SDT_BT} ~ {EDT_DATA})",
            fee_rate=FEE_RATE,
            weight_type="ts",
            yearly_days=YEARLY_DAYS,
        )
        print(f"\n[报告] 等权组合 HTML: {out_html} (size={out_html.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
