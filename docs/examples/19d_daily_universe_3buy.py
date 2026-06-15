"""案例 19d：本地 A 股分钟数据 → 日线三买事件选股 + 截面回测

基于案例 18 的截面模式，改为从本地 parquet 读取日线数据：
- 数据源：czsc.connectors.stock_min_connector
- 日线直接可用（freq='日线'），内部由 1 分钟 resample 而来

运行：
    python docs/examples/19d_daily_universe_3buy.py

产物：
    docs/examples/_output/19d_daily_universe_3buy/
        ├── report_ts.html
        ├── report_cs.html
        └── stats.csv
"""

from __future__ import annotations

import random
from collections.abc import Iterable
from pathlib import Path

import pandas as pd
from tqdm import tqdm
from wbt import generate_backtest_report

from czsc import (
    Event,
    WeightBacktest,
    adjust_holding_weights,
    generate_czsc_signals,
    get_signals_config,
)
from czsc.connectors.stock_min_connector import get_raw_bars, get_symbols

# ============================ 全局参数 ============================ #

OUTPUT_DIR = Path(__file__).resolve().parent / "_output" / "19d_daily_universe_3buy"

BASE_FREQ = "日线"
SDT_DATA = "20200101"
EDT_DATA = "20241231"
SDT_BT = "2020-07-01"
FEE_RATE = 0.0002
HOLD_PERIODS = 5
SYMBOL_LIMIT = 15
SAMPLE_SEED = 42
YEARLY_DAYS = 252

EVENT_SIGNAL = f"{BASE_FREQ}_D1_三买辅助V230228_三买_任意_任意_0"


# ============================ Event 构造 ============================ #


def build_open_event() -> Event:
    return Event.load(
        {
            "name": "日线三买V230228_开多",
            "operate": "开多",
            "signals_all": [EVENT_SIGNAL],
        }
    )


# ============================ 信号 → 权重 ============================ #


def event_matches_to_weight_df(
    bars: list,
    signals_config: list[dict],
    event: Event,
    sdt: str,
) -> pd.DataFrame:
    """对单只股票跑信号 + 事件匹配，返回 (dt, symbol, price, weight) 长表。"""
    sigs = generate_czsc_signals(bars, signals_config, sdt=sdt, df=False)
    if not sigs:
        return pd.DataFrame(columns=["dt", "symbol", "price", "weight"])

    rows = []
    for s in sigs:
        dt = pd.to_datetime(s["dt"])
        if dt.tzinfo is not None:
            dt = dt.tz_localize(None)
        rows.append(
            {
                "dt": dt,
                "symbol": s["symbol"],
                "price": float(s["close"]),
                "weight": 1.0 if event.is_match(s) else 0.0,
            }
        )
    return pd.DataFrame(rows)


def _attach_n1b(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["symbol", "dt"]).reset_index(drop=True)
    df["n1b"] = df.groupby("symbol")["price"].pct_change().shift(-1).fillna(0)
    return df


# ============================ 主流程封装 ============================ #


def run_universe(
    bars_iter: Iterable[tuple[str, list]],
    *,
    sdt_bt: str,
    hold_periods: int,
    output_dir: Path,
    title_prefix: str,
) -> dict[str, dict[str, float]]:
    """跑一遍多 symbol 的事件 → 权重 → 回测 → HTML 报告。"""
    event = build_open_event()
    signals_config = get_signals_config([EVENT_SIGNAL])
    print(f"[config] signals_config = {signals_config}")

    pieces: list[pd.DataFrame] = []
    matched_total = 0
    for _label, bars in bars_iter:
        if not bars:
            continue
        df = event_matches_to_weight_df(bars, signals_config, event, sdt_bt)
        if df.empty:
            continue
        matched_total += int((df["weight"] == 1.0).sum())
        pieces.append(df)

    if not pieces:
        raise RuntimeError("所有 symbol 都没产生权重数据；检查数据源 / 信号配置")

    dfw = pd.concat(pieces, ignore_index=True)
    dfw = _attach_n1b(dfw)
    print(f"[event] 共 {len(pieces)} 只 symbol 入库；权重表 shape = {dfw.shape}；三买触发 {matched_total} 次")

    adj = adjust_holding_weights(dfw, hold_periods=hold_periods)
    adj = adj.merge(dfw[["dt", "symbol", "price"]], on=["dt", "symbol"], how="left")
    wb_df = adj[["dt", "symbol", "weight", "price"]].copy()
    print(f"[hold] 扩展为 {hold_periods} 日持仓后；非零权重 bar 数 = {int((wb_df['weight'] > 0).sum())}")

    results = {}
    for wt in ("ts", "cs"):
        wb = WeightBacktest(
            data=wb_df,
            fee_rate=FEE_RATE,
            weight_type=wt,
            yearly_days=YEARLY_DAYS,
        )
        print(f"[backtest] weight_type={wt} 核心绩效指标：")
        for k, v in wb.stats.items():
            print(f"    {k}: {v}")
        results[wt] = dict(wb.stats)

        out_html = output_dir / f"report_{wt}.html"
        generate_backtest_report(
            df=wb_df,
            output_path=str(out_html),
            title=f"{title_prefix} ({wt}, hold={hold_periods}d)",
            fee_rate=FEE_RATE,
            weight_type=wt,
            yearly_days=YEARLY_DAYS,
        )
        print(f"[report] HTML 报告: {out_html} (size={out_html.stat().st_size:,} bytes)")

    return results


def _buy_and_hold_stats(dfw: pd.DataFrame) -> dict[str, float]:
    """等权买入并持有同一组合（以各 symbol 首次出现日期为起点，简化处理）。"""
    df = dfw.sort_values(["symbol", "dt"]).copy()
    first = df.groupby("symbol")[["dt", "price"]].first().reset_index()
    first = first.rename(columns={"price": "entry_price"})
    df = df.merge(first[["symbol", "entry_price"]], on="symbol", how="left")
    df["n1b"] = df.groupby("symbol")["price"].pct_change().shift(-1).fillna(0)
    # 等权日收益 = 各 symbol 当日收益均值
    daily = df.groupby("dt").agg(n1b=("n1b", "mean")).reset_index().sort_values("dt")
    daily["cum"] = (1 + daily["n1b"]).cumprod()
    total_ret = float(daily["cum"].iloc[-1] - 1)
    # 近似年化：按实际交易日数
    n_days = len(daily)
    ann_ret = (1 + total_ret) ** (YEARLY_DAYS / n_days) - 1 if n_days > 0 else 0.0
    return {
        "total_return": total_ret,
        "annual_return": ann_ret,
        "trading_days": n_days,
    }


def main() -> None:
    symbols = get_symbols("sz")
    rng = random.Random(SAMPLE_SEED)
    sampled = rng.sample(symbols, min(SYMBOL_LIMIT, len(symbols)))
    print(f"[universe] 标的池共 {len(symbols)} 只，抽样 {len(sampled)} 只 (seed={SAMPLE_SEED})")

    bars_iter: list[tuple[str, list]] = []
    for sym in tqdm(sampled, desc="拉日线"):
        try:
            bars = get_raw_bars(
                symbol=sym,
                freq=BASE_FREQ,
                sdt=SDT_DATA,
                edt=EDT_DATA,
                raw_bars=True,
            )
            if bars:
                bars_iter.append((sym, bars))
        except Exception as e:
            tqdm.write(f"[warn] {sym} 拉取失败：{e}")

    if not bars_iter:
        raise SystemExit("没有任何股票拉到数据，请检查本地 parquet 路径")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stats = run_universe(
        bars_iter=bars_iter,
        sdt_bt=SDT_BT,
        hold_periods=HOLD_PERIODS,
        output_dir=OUTPUT_DIR,
        title_prefix="案例 19d - 日线三买事件选股 (local minute)",
    )

    # buy-and-hold 对比
    pieces_bh = []
    for _, bars in bars_iter:
        sigs = generate_czsc_signals(bars, get_signals_config([EVENT_SIGNAL]), sdt=SDT_BT, df=False)
        if sigs:
            for s in sigs:
                dt = pd.to_datetime(s["dt"])
                if dt.tzinfo is not None:
                    dt = dt.tz_localize(None)
                pieces_bh.append({"dt": dt, "symbol": s["symbol"], "price": float(s["close"])})
    if pieces_bh:
        df_bh = pd.DataFrame(pieces_bh)
        bh = _buy_and_hold_stats(df_bh)
        print(f"\n[buy&hold] 等权买入持有对比:")
        for k, v in bh.items():
            print(f"    {k}: {v}")
        stats["buy_and_hold"] = bh

    stats_df = pd.DataFrame(stats)
    stats_df.to_csv(OUTPUT_DIR / "stats.csv")
    print(f"\n[done] stats 已保存到 {OUTPUT_DIR / 'stats.csv'}")
    print("\n=== 绩效对比 ===")
    print(stats_df.to_string())


if __name__ == "__main__":
    main()
