"""案例 20：用 Mock QMT 跑 czsc 策略模拟盘

本案例演示：
1. 从本地 parquet 读取 510300.SH 的 30 分钟数据
2. 用 ``MockQmtBroker`` 回放行情
3. 用 ``CzscQmtAdapter`` 把 czsc 策略信号转成 QMT 委托
4. 打印账户资产、持仓、成交记录

当真实 QMT 申请下来后，只需要：
- 实现 ``QmtBroker`` 的子类，封装 XtQuant API
- 把 ``broker = MockQmtBroker(...)`` 替换为真实 broker
- ``CzscQmtAdapter`` 和策略逻辑无需改动

运行：
    python docs/examples/20_qmt_mock_paper_trading.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from czsc import CzscStrategyBase, Event, Position
from czsc.connectors.etf_min_connector import get_raw_bars as get_etf_bars
from czsc.traders.qmt_adapter import CzscQmtAdapter
from czsc.traders.qmt_broker import MockQmtBroker

OUTPUT_DIR = Path(__file__).resolve().parent / "_output" / "20_qmt_mock_paper_trading"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

SYMBOL = "510300.SH"
INITIAL_CASH = 1_000_000.0


def build_position(symbol: str) -> Position:
    """构造 30 分钟三买 + 固定持仓 20 根 K 线的 Position。"""
    open_event = Event.load(
        {
            "name": "30分钟_三买V230228_开多",
            "operate": "开多",
            "signals_all": ["30分钟_D1_三买辅助V230228_三买_任意_任意_0"],
            "signals_not": ["30分钟_D1_涨跌停V230331_涨停_任意_任意_0"],
        }
    )
    return Position(
        name="30min_fixed20",
        symbol=symbol,
        opens=[open_event],
        exits=[],
        interval=3600 * 4,
        timeout=20,
        stop_loss=300,
        t0=False,
    )


class Fixed20Strategy(CzscStrategyBase):
    """本示例只交易单标的，返回固定持仓 20K 的 Position。"""

    @property
    def positions(self) -> list[Position]:
        return [build_position(self.symbol)]


def prepare_data(symbol: str, sdt: str, edt: str) -> pd.DataFrame:
    """读取本地 ETF 分钟数据并转成 MockQmtBroker 需要的 DataFrame 格式。"""
    bars = get_etf_bars(symbol, "30分钟", sdt, edt, raw_bars=False)
    if isinstance(bars, list):
        # 兼容 raw_bars=True 的情况
        df = pd.DataFrame(
            [
                {
                    "dt": b.dt,
                    "open": b.open,
                    "high": b.high,
                    "low": b.low,
                    "close": b.close,
                    "vol": b.vol,
                    "amount": b.amount,
                }
                for b in bars
            ]
        )
    else:
        df = bars.copy()
    df["dt"] = pd.to_datetime(df["dt"])
    return df[["dt", "open", "high", "low", "close", "vol", "amount"]]


def simple_on_bar(strategy: Fixed20Strategy):
    """根据 strategy 的 backtest holds 状态生成目标权重。

    为简化示例，这里在回放前先用 backtest 跑一遍，得到每个 dt 的目标 pos，
    然后在 on_bar 中查表返回。真实场景应在 on_bar 里实时更新 CZSC 状态。
    """
    sdt_bt = "2025-01-01"
    bars = get_etf_bars(strategy.symbol, "30分钟", "20240101", "20260612", raw_bars=True)
    res = strategy.backtest(bars, sdt=sdt_bt)
    holds = res.holds_df()
    holds["dt"] = pd.to_datetime(holds["dt"])
    weight_by_dt = dict(zip(holds["dt"], holds["pos"]))

    def _on_bar(bar: dict) -> dict[str, float]:
        w = weight_by_dt.get(bar["dt"], 0.0)
        return {strategy.symbol: float(w)}

    return _on_bar


def main() -> None:
    symbol = SYMBOL
    df = prepare_data(symbol, "20240101", "20260612")

    # 1. 构造 Mock broker
    broker = MockQmtBroker(
        initial_cash=INITIAL_CASH,
        data={symbol: df},
        trade_date_range=("20250101", "20260611"),
        sleep_seconds=0.0,
    )

    # 2. 构造 czsc 策略
    strategy = Fixed20Strategy(symbol=symbol)
    strategy.on_bar = simple_on_bar(strategy)

    # 3. 构造适配器
    adapter = CzscQmtAdapter(
        strategy=strategy,
        broker=broker,
        symbols=[symbol],
        lot_size=100,
        price_tick={symbol: 0.001},
        fixed_capital=INITIAL_CASH,  # 0/1 权重策略用固定本金，避免每个 bar 都微调
        verbose=True,
    )

    # 4. 连接并订阅
    broker.connect()
    broker.subscribe([symbol])
    broker.set_callbacks(on_bar=adapter.on_bar)

    # 5. 启动回放
    broker.run()

    # 6. 打印结果
    print("\n" + "=" * 60)
    print("模拟盘结果")
    print("=" * 60)
    asset = broker.query_asset()
    print(f"总资产: {asset.total_asset:,.2f}")
    print(f"现金:   {asset.cash:,.2f}")
    print(f"市值:   {asset.market_value:,.2f}")
    print(f"收益率: {(asset.total_asset / INITIAL_CASH - 1) * 100:.2f}%")

    print("\n当前持仓:")
    for pos in broker.query_positions():
        print(f"  {pos.symbol}: {pos.volume}股, 均价 {pos.avg_price:.3f}, 可用 {pos.available_volume}")

    print(f"\n委托记录: {len(broker.query_orders())} 条")
    print(f"成交记录: {len(broker.query_trades())} 条")

    # 7. 保存成交记录到 CSV
    trades_df = pd.DataFrame(
        [
            {
                "trade_id": t.trade_id,
                "order_id": t.order_id,
                "symbol": t.symbol,
                "side": t.side.value,
                "volume": t.volume,
                "price": t.price,
                "trade_time": t.trade_time,
            }
            for t in broker.query_trades()
        ]
    )
    trades_path = OUTPUT_DIR / "trades.csv"
    trades_df.to_csv(trades_path, index=False)
    print(f"\n成交记录已保存: {trades_path}")

    broker.disconnect()


if __name__ == "__main__":
    main()
