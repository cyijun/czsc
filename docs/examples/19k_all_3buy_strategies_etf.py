"""案例 19k：对 ETF 筛选报告标的跑全量三买策略回测

整合 examples/19 系列中各种三买策略变体，统一对
/mnt/h/ETF量化标的筛选报告.md 中的 8 个 ETF 标的跑回测：

1. baseline              : 30min 三买 + 笔向下平仓
2. trend_filtered        : 30min 三买 + 笔向上趋势过滤 + 笔向下平仓
3. fixed_10              : 30min 三买 + 固定持仓 10 根 K 线
4. fixed_20              : 30min 三买 + 固定持仓 20 根 K 线
5. stop_150              : 30min 三买 + 止损 150 + 笔向下平仓
6. stop_300              : 30min 三买 + 止损 300 + 笔向下平仓
7. 30_60_resonance_baseline : 30min + 60min 共振 + 笔向下平仓
8. 30_60_resonance_fixed20  : 30min + 60min 共振 + 固定持仓 20 根 K 线

运行：
    uv run --no-sync python docs/examples/19k_all_3buy_strategies_etf.py

产物：
    docs/examples/_output/19k_all_3buy_strategies_etf/
        ├── stats.csv
        └── best_per_symbol.csv
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from wbt import WeightBacktest

from czsc import CzscStrategyBase, Event, Position
from czsc.connectors.etf_min_connector import get_raw_bars as get_etf_bars

OUTPUT_DIR = Path(__file__).resolve().parent / "_output" / "19k_all_3buy_strategies_etf"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

BASE_FREQ = "30分钟"
SDT_DATA = "20240101"
EDT_DATA = "20260630"
SDT_BT = "2025-07-01"
FEE_RATE = 0.0002
YEARLY_DAYS = 252

SYMBOLS = [
    "588200.SH", "512480.SH",  # 核心
    "515880.SH", "159819.SZ", "159363.SZ",  # 卫星
    "515050.SH", "159995.SZ", "562500.SH",  # 观察备选
]

_OPEN_EVENT = f"{BASE_FREQ}_D1_三买辅助V230228_三买_任意_任意_0"
_NOT_ZT = f"{BASE_FREQ}_D1_涨跌停V230331_涨停_任意_任意_0"
_EXIT_BI_DOWN = f"{BASE_FREQ}_D1_表里关系V230101_向下_任意_任意_0"
_SIG_BI_UP = f"{BASE_FREQ}_D1_表里关系V230101_向上_任意_任意_0"


def _build_position(
    symbol: str,
    *,
    base_freq: str = "30分钟",
    trend_filtered: bool = False,
    timeout: int = 16 * 30,
    stop_loss: float = 300.0,
    use_exit: bool = True,
) -> Position:
    """通用三买 Position 构造器。"""
    signals_all = [_OPEN_EVENT]
    name_parts = [base_freq, "三买"]
    if trend_filtered:
        signals_all.append(_SIG_BI_UP)
        name_parts.append("趋势过滤")

    open_event = Event.load(
        {
            "name": "_".join(name_parts + ["开多"]),
            "operate": "开多",
            "signals_all": signals_all,
            "signals_not": [_NOT_ZT],
        }
    )

    exits: list[Event] = []
    if use_exit:
        exit_event = Event.load(
            {
                "name": f"{base_freq}_笔向下_平多",
                "operate": "平多",
                "signals_all": [_EXIT_BI_DOWN],
            }
        )
        exits.append(exit_event)

    if timeout != 16 * 30:
        name_parts.append(f"fixed{timeout}")
    if stop_loss != 300.0:
        name_parts.append(f"stop{int(stop_loss)}")
    if trend_filtered:
        name_parts.append("趋势过滤")

    return Position(
        name="_".join(name_parts),
        symbol=symbol,
        opens=[open_event],
        exits=exits,
        interval=3600 * 4,
        timeout=timeout,
        stop_loss=stop_loss,
        t0=False,
    )


class StrategyBaseline(CzscStrategyBase):
    @property
    def positions(self) -> list[Position]:
        return [_build_position(self.symbol)]


class StrategyTrendFiltered(CzscStrategyBase):
    @property
    def positions(self) -> list[Position]:
        return [_build_position(self.symbol, trend_filtered=True)]


class StrategyFixed10(CzscStrategyBase):
    @property
    def positions(self) -> list[Position]:
        return [_build_position(self.symbol, timeout=10, use_exit=False)]


class StrategyFixed20(CzscStrategyBase):
    @property
    def positions(self) -> list[Position]:
        return [_build_position(self.symbol, timeout=20, use_exit=False)]


class StrategyStop150(CzscStrategyBase):
    @property
    def positions(self) -> list[Position]:
        return [_build_position(self.symbol, stop_loss=150.0)]


class StrategyStop300(CzscStrategyBase):
    @property
    def positions(self) -> list[Position]:
        return [_build_position(self.symbol, stop_loss=300.0)]


class Strategy30_60_Baseline(CzscStrategyBase):
    @property
    def positions(self) -> list[Position]:
        return [
            _build_position(self.symbol, base_freq="30分钟"),
            _build_position(self.symbol, base_freq="60分钟"),
        ]


class Strategy30_60_Fixed20(CzscStrategyBase):
    @property
    def positions(self) -> list[Position]:
        return [
            _build_position(self.symbol, base_freq="30分钟", timeout=20, use_exit=False),
            _build_position(self.symbol, base_freq="60分钟", timeout=20, use_exit=False),
        ]


STRATEGIES: list[tuple[str, type[CzscStrategyBase]]] = [
    ("baseline", StrategyBaseline),
    ("trend_filtered", StrategyTrendFiltered),
    ("fixed_10", StrategyFixed10),
    ("fixed_20", StrategyFixed20),
    ("stop_150", StrategyStop150),
    ("stop_300", StrategyStop300),
    ("30_60_resonance_baseline", Strategy30_60_Baseline),
    ("30_60_resonance_fixed20", Strategy30_60_Fixed20),
]


def holds_to_weight_df(holds: pd.DataFrame) -> pd.DataFrame:
    df = holds[["dt", "symbol", "pos", "price"]].rename(columns={"pos": "weight"})
    if df.duplicated(subset=["dt", "symbol"]).any():
        df = df.groupby(["dt", "symbol"], as_index=False).agg(
            weight=("weight", "mean"),
            price=("price", "first"),
        )
    df["weight"] = df["weight"].astype("float64")
    df["price"] = df["price"].astype("float64")
    return df[["dt", "symbol", "weight", "price"]]


def run_strategy(tag: str, strategy: CzscStrategyBase, bars: list) -> dict[str, float]:
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
    return dict(wb.stats)


def run_symbol(symbol: str) -> dict[str, dict[str, float]] | None:
    print(f"\n{'='*60}")
    print(f"标的: {symbol}")
    print(f"{'='*60}")

    try:
        bars = get_etf_bars(symbol, BASE_FREQ, SDT_DATA, EDT_DATA, raw_bars=True)
    except Exception as e:
        print(f"[warn] {symbol} 读取失败：{e}")
        return None
    if not bars:
        print(f"[warn] {symbol} 无数据")
        return None
    print(f"[数据] {bars[0].symbol} {bars[0].freq} 共 {len(bars)} 根；{bars[0].dt} ~ {bars[-1].dt}")

    stats = {}
    for name, StrategyCls in STRATEGIES:
        tag = f"{symbol}_{name}"
        strategy = StrategyCls(symbol=symbol)
        stats[name] = run_strategy(tag, strategy, bars)
    return stats


def main() -> None:
    all_stats: dict[str, dict[str, dict[str, float]]] = {}
    for symbol in SYMBOLS:
        s = run_symbol(symbol)
        if s:
            all_stats[symbol] = s

    if not all_stats:
        raise SystemExit("没有任何标的回测成功")

    rows = []
    for symbol, stats in all_stats.items():
        for strategy_name, metrics in stats.items():
            row = {"symbol": symbol, "strategy": strategy_name}
            row.update(metrics)
            rows.append(row)
    summary_df = pd.DataFrame(rows)
    summary_csv = OUTPUT_DIR / "stats.csv"
    summary_df.to_csv(summary_csv, index=False, float_format="%.6f")
    print(f"\n[汇总] 全量绩效表已保存: {summary_csv}")

    # 每只标的最优策略（按夏普比率）
    best_idx = summary_df.groupby("symbol")["夏普比率"].idxmax()
    best_df = summary_df.loc[best_idx][["symbol", "strategy", "年化收益", "夏普比率", "卡玛比率", "最大回撤", "交易胜率"]]
    best_csv = OUTPUT_DIR / "best_per_symbol.csv"
    best_df.to_csv(best_csv, index=False, float_format="%.6f")
    print(f"\n[汇总] 每只标的最优策略: {best_csv}")
    print(best_df.to_string(index=False))

    # 全局 Top10 策略-标的组合
    top10 = summary_df.nlargest(10, "夏普比率")[["symbol", "strategy", "年化收益", "夏普比率", "卡玛比率", "最大回撤", "交易胜率"]]
    print("\n[汇总] 全局夏普比率 Top10:")
    print(top10.to_string(index=False))


if __name__ == "__main__":
    main()
