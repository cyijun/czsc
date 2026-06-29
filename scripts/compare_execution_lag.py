"""对比同 bar close 成交 vs 延后一根 K 线成交的绩效差异。

这是一个轻量级诊断脚本，不需要修改 Rust 引擎。
它用 Python 层 post-processing 的方式，把 `holds_df` 中的成交价
替换为下一根 K 线的 open/close，然后重新跑 `WeightBacktest`，
从而量化未来函数/执行延迟对回测结果的影响。

用法：
    uv run --no-sync python scripts/compare_execution_lag.py

依赖：
- 本地需要有 ETF/股票分钟数据（czsc.connectors.etf_min_connector）。
- 若数据缺失，脚本会提示并退出。
"""

from __future__ import annotations

import bisect

import pandas as pd
from wbt import WeightBacktest

from czsc import CzscStrategyBase, Event, Position
from czsc.connectors.etf_min_connector import get_raw_bars as get_etf_bars

FEE_RATE = 0.0002
YEARLY_DAYS = 252


# ============================ 策略定义（内联，避免路径依赖） ============================


def _build_position(symbol: str, base_freq: str, timeout: int) -> Position:
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


class CombinedStrategy(CzscStrategyBase):
    """30 分钟 + 60 分钟共振，均固定持有 20 根 K 线。"""

    @property
    def positions(self) -> list[Position]:
        return [
            _build_position(self.symbol, "30分钟", 20),
            _build_position(self.symbol, "60分钟", 20),
        ]


# ============================ 执行延迟工具函数 ============================


def holds_to_weight_df(holds: pd.DataFrame) -> pd.DataFrame:
    """把 ResearchResult.holds_df() 转成 wbt 期望的权重表。"""
    df = holds[["dt", "symbol", "pos", "price"]].rename(columns={"pos": "weight"})
    if df.duplicated(subset=["dt", "symbol"]).any():
        df = df.groupby(["dt", "symbol"], as_index=False).agg(
            weight=("weight", "mean"),
            price=("price", "first"),
        )
    return df[["dt", "symbol", "weight", "price"]]


def apply_execution_lag(
    holds: pd.DataFrame,
    bars: list,
    lag_price: str = "open",
) -> pd.DataFrame:
    """把 holds 中的成交价整体延后一根 K 线。

    Args:
        holds: ResearchResult.holds_df() 输出。
        bars: 原始 RawBar 列表，按 dt 排序。
        lag_price: "open" 或 "close"，用下一根 bar 的哪个价格作为成交价。

    Returns:
        调整后的 holds DataFrame，列名与输入一致。
    """
    # 按 symbol 预排序 bars 和 dt 列表，便于二分查找下一根 bar
    bars_by_symbol: dict[str, list] = {}
    dts_by_symbol: dict[str, list] = {}
    for b in bars:
        bars_by_symbol.setdefault(b.symbol, []).append(b)
        dts_by_symbol.setdefault(b.symbol, []).append(b.dt)

    out_rows = []
    for _, row in holds.iterrows():
        symbol = row["symbol"]
        dt = row["dt"]
        sym_bars = bars_by_symbol.get(symbol, [])
        sym_dts = dts_by_symbol.get(symbol, [])

        new_row = row.to_dict()
        if not sym_dts:
            out_rows.append(new_row)
            continue

        # 找到当前 dt 之后的第一根 bar
        idx = bisect.bisect_right(sym_dts, dt)
        if idx < len(sym_bars):
            next_bar = sym_bars[idx]
            new_row["price"] = float(next_bar.open if lag_price == "open" else next_bar.close)
        # 否则是最后一根 bar，保留原价格
        out_rows.append(new_row)

    return pd.DataFrame(out_rows)[holds.columns]


def run_comparison(
    strategy: CzscStrategyBase,
    bars: list,
    sdt_bt: str,
    fee_rate: float = FEE_RATE,
) -> pd.DataFrame:
    """跑同一策略的三种执行方式并返回对比表。"""
    res = strategy.backtest(bars, sdt=sdt_bt)
    holds = res.holds_df()

    records = []
    for label, price_col in [
        ("同 bar close", None),
        ("延后 1 根 open", "open"),
        ("延后 1 根 close", "close"),
    ]:
        adjusted_holds = (
            holds if price_col is None else apply_execution_lag(holds, bars, lag_price=price_col)
        )

        dfw = holds_to_weight_df(adjusted_holds)
        wb = WeightBacktest(
            data=dfw,
            fee_rate=fee_rate,
            weight_type="ts",
            yearly_days=YEARLY_DAYS,
        )
        records.append(
            {
                "执行方式": label,
                "年化收益": wb.stats.get("年化收益"),
                "夏普比率": wb.stats.get("夏普比率"),
                "卡玛比率": wb.stats.get("卡玛比率"),
                "最大回撤": wb.stats.get("最大回撤"),
                "交易胜率": wb.stats.get("交易胜率"),
                "交易次数": wb.stats.get("交易次数"),
            }
        )

    return pd.DataFrame(records)


# ============================ 主流程 ============================


def main() -> None:
    symbol = "510300.SH"
    sdt_data, edt_data, sdt_bt = "20240101", "20260612", "2025-01-01"

    print(f"[数据] 读取 {symbol} 30分钟数据 {sdt_data} ~ {edt_data} ...")
    try:
        bars = get_etf_bars(symbol, "30分钟", sdt_data, edt_data, raw_bars=True)
    except Exception as e:
        print(f"[错误] 读取数据失败：{e}")
        return

    if not bars:
        print("[错误] 没有拉取到数据，请检查本地 parquet 路径。")
        return

    print(f"[数据] 共 {len(bars)} 根；{bars[0].dt} ~ {bars[-1].dt}")

    for StrategyCls, name in [
        (Baseline30Strategy, "30min_baseline"),
        (Fixed20_30Strategy, "30min_fixed20"),
        (CombinedStrategy, "30_60_fixed20"),
    ]:
        print(f"\n=== {name} ===")
        strategy = StrategyCls(symbol=symbol)
        df_cmp = run_comparison(strategy, bars, sdt_bt)
        print(df_cmp.to_string(index=False))

    print("\n[完成] 对比结束。若'延后'行与'同 bar close'行差异显著，说明未来函数影响较大。")


if __name__ == "__main__":
    main()
