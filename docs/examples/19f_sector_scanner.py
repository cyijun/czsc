"""案例 19f：按板块扫描 baseline / 组合 三买 策略

用法：
    python docs/examples/19f_sector_scanner.py --sector 半导体 \
        --symbols 512480.SH,159995.SZ,603501.SH,002371.SZ,603986.SH

会自动判断 symbol 属于 ETF 还是 A 股，并选用对应连接器。
产物：docs/examples/_output/19f_sector_scanner/{sector}_stats.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from wbt import WeightBacktest

from czsc import CzscStrategyBase, Event, Position
from czsc.connectors.etf_min_connector import get_raw_bars as get_etf_bars
from czsc.connectors.etf_min_connector import get_symbols as get_etf_symbols
from czsc.connectors.stock_min_connector import get_raw_bars as get_stock_bars

OUTPUT_DIR = Path(__file__).resolve().parent / "_output" / "19f_sector_scanner"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

FEE_RATE = 0.0002
YEARLY_DAYS = 252


def _build_position(symbol: str, base_freq: str, timeout: int) -> Position:
    """构造 三买 仓位；timeout == 16*30 表示用笔向下信号平仓。"""
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


class BaselineStrategy(CzscStrategyBase):
    """30 分钟 baseline：笔向下平仓。"""

    @property
    def positions(self) -> list[Position]:
        return [_build_position(self.symbol, "30分钟", 16 * 30)]


class CombinedStrategy(CzscStrategyBase):
    """30 + 60 分钟共振，均固定持有 20 根 K 线。"""

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


def run_strategy(strategy: CzscStrategyBase, bars: list, sdt_bt: str) -> dict[str, float]:
    res = strategy.backtest(bars, sdt=sdt_bt)
    dfw = holds_to_weight_df(res.holds_df())
    wb = WeightBacktest(data=dfw, fee_rate=FEE_RATE, weight_type="ts", yearly_days=YEARLY_DAYS)
    return dict(wb.stats)


def get_bars(symbol: str, sdt: str, edt: str) -> list:
    etf_set = set(get_etf_symbols())
    if symbol in etf_set:
        return get_etf_bars(symbol, "30分钟", sdt, edt, raw_bars=True)
    return get_stock_bars(symbol, "30分钟", sdt, edt, raw_bars=True)


def scan_sector(sector: str, symbols: list[str]) -> pd.DataFrame:
    records = []
    periods = [
        ("2020-2026H1", "20200101", "20260612", "2020-07-01"),
        ("2025-2026H1", "20240101", "20260612", "2025-01-01"),
    ]
    for symbol in symbols:
        print(f"\n[{sector}] 读取 {symbol} ...")
        try:
            bars = get_bars(symbol, "20200101", "20260612")
        except Exception as e:
            print(f"  [skip] {symbol} 读取失败: {e}")
            continue
        if not bars:
            print(f"  [skip] {symbol} 无数据")
            continue
        print(f"  {symbol}: {len(bars)} 根 {bars[0].dt} ~ {bars[-1].dt}")

        for period_label, sdt_data, edt_data, sdt_bt in periods:
            # 按窗口截断 bars
            from datetime import datetime

            sdt_dt = datetime.strptime(sdt_data, "%Y%m%d")
            edt_dt = datetime.strptime(edt_data, "%Y%m%d")
            window = [b for b in bars if sdt_dt <= b.dt <= edt_dt]
            if len(window) < 100:
                continue

            baseline_stats = run_strategy(BaselineStrategy(symbol=symbol), window, sdt_bt)
            combined_stats = run_strategy(CombinedStrategy(symbol=symbol), window, sdt_bt)

            for name, stats in [("baseline", baseline_stats), ("combined", combined_stats)]:
                records.append(
                    {
                        "sector": sector,
                        "symbol": symbol,
                        "period": period_label,
                        "strategy": name,
                        "annual": stats.get("年化收益"),
                        "sharpe": stats.get("夏普比率"),
                        "calmar": stats.get("卡玛比率"),
                        "max_dd": stats.get("最大回撤"),
                        "win_rate": stats.get("交易胜率"),
                        "trades": stats.get("交易次数"),
                    }
                )

    df = pd.DataFrame(records)
    if not df.empty:
        csv_path = OUTPUT_DIR / f"{sector}_stats.csv"
        df.to_csv(csv_path, index=False)
        print(f"\n[{sector}] 结果已保存: {csv_path}")
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description="板块 三买 策略扫描")
    parser.add_argument("--sector", required=True, help="板块名称，如 半导体")
    parser.add_argument("--symbols", required=True, help="逗号分隔的代码列表")
    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    df = scan_sector(args.sector, symbols)
    print("\n汇总表：")
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
