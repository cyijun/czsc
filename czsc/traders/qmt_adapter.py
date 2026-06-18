"""czsc 策略与 QMT 模拟盘/实盘之间的适配器。

设计目标：
- 策略层只输出``目标权重``（target_weights: dict[symbol, weight]）
- 适配器负责把目标权重翻译成 QMT 委托单
- 支持 ``MockQmtBroker`` 本地模拟，也支持未来替换为真实 QMT broker

适配逻辑：
1. 每根 bar 收盘后，调用 ``strategy.backtest_step(bars)`` 或直接用 ``CzscStrategyBase``
   维护的内部状态计算目标权重。
2. 对比当前持仓市值与目标权重，计算每个 symbol 的``目标市值``。
3. 目标市值 - 当前市值 = 需买入/卖出的金额。
4. 金额 / 当前价格 = 目标股数（向下取整到 100 的整数倍，A 股一手 100 股）。
5. 调用 ``broker.place_order`` 下限价单。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from czsc.strategies import CzscStrategyBase

from czsc.traders.qmt_broker import OrderSide, OrderType, QmtBroker


@dataclass
class TargetWeight:
    """单标的的目标权重。"""

    symbol: str
    weight: float  # [-1, 1]，正为多头，负为空头


class CzscQmtAdapter:
    """czsc 策略 → QMT broker 的适配器。"""

    def __init__(
        self,
        strategy: CzscStrategyBase,
        broker: QmtBroker,
        symbols: list[str],
        lot_size: int = 100,
        price_tick: dict[str, float] | None = None,
        verbose: bool = True,
    ):
        """
        Args:
            strategy: czsc 策略实例（已实现 positions 属性）
            broker: QMT broker 实例（Mock 或真实 XtQuant）
            symbols: 交易标的列表
            lot_size: 最小交易单位，A 股默认 100 股
            price_tick: 每个 symbol 的价格最小变动单位，用于挂限价单
            verbose: 是否打印调仓日志
        """
        self.strategy = strategy
        self.broker = broker
        self.symbols = symbols
        self.lot_size = lot_size
        self.price_tick = price_tick or {}
        self.verbose = verbose

        # 缓存每个 symbol 最近一次收到的 bar 价格
        self._latest_prices: dict[str, float] = {}
        # 缓存每个 symbol 上一次的目标持仓股数，避免每个 bar 都发单
        self._last_target_volume: dict[str, int] = {}

    def on_bar(self, bar: dict) -> None:
        """行情回调入口。

        bar 格式：
            {"dt": datetime, "prices": {"510300.SH": 3.574, ...}}
        """
        dt = bar["dt"]
        prices = bar["prices"]
        self._latest_prices.update(prices)

        # 1. 把当前 bar 喂给 strategy，获取目标权重
        target_weights = self._compute_target_weights(bar)

        # 2. 获取当前账户资产与持仓
        asset = self.broker.query_asset()
        positions = {p.symbol: p for p in self.broker.query_positions()}

        # 3. 按目标权重调仓（仅在目标股数变化时下单）
        for symbol, target_weight in target_weights.items():
            price = prices.get(symbol)
            if price is None or price <= 0:
                continue

            current_pos = positions.get(symbol)
            current_volume = current_pos.volume if current_pos else 0
            available_volume = current_pos.available_volume if current_pos else 0

            # 目标股数
            target_volume = self._weight_to_volume(target_weight, asset.total_asset, price, symbol)

            # 最小调仓阈值：一手
            delta = target_volume - current_volume
            if abs(delta) < self.lot_size:
                continue

            order_price = self._round_price(price, symbol)

            # 买入
            if delta > 0:
                side = OrderSide.BUY
                max_buy_volume = int(asset.cash / order_price) // self.lot_size * self.lot_size
                volume = min(delta, max_buy_volume)
            # 卖出
            else:
                side = OrderSide.SELL
                volume = min(-delta, available_volume)

            if volume <= 0:
                continue

            order_id = self.broker.place_order(
                symbol=symbol,
                side=side,
                volume=volume,
                price=order_price,
                order_type=OrderType.LIMIT,
            )
            self._last_target_volume[symbol] = target_volume
            if self.verbose:
                target_mv = target_volume * price
                current_mv = current_volume * price
                print(
                    f"[{dt}] {symbol} 调仓: {side.value} {volume}股 @ {order_price:.3f}, "
                    f"目标持仓={target_volume}股, 当前持仓={current_volume}股, "
                    f"目标市值={target_mv:,.2f}, 当前市值={current_mv:,.2f}"
                )

    def _compute_target_weights(self, bar: dict) -> dict[str, float]:
        """基于 strategy 计算目标权重。

        当前实现采用简单约定：若 strategy 有 ``on_bar`` 方法则调用它，
        否则返回等权配置（placeholder）。真实场景中可扩展为：
        - 调用 strategy.backtest_step
        - 从 strategy 的 positions 状态推导权重
        """
        if hasattr(self.strategy, "on_bar"):
            return self.strategy.on_bar(bar)

        # 默认等权；子类可覆盖此逻辑
        n = len(self.symbols)
        return {s: 1.0 / n for s in self.symbols}

    def _weight_to_volume(self, weight: float, total_asset: float, price: float, symbol: str) -> int:
        """目标权重 → 目标股数，按 lot_size 取整。"""
        if price <= 0:
            return 0
        target_amount = total_asset * weight
        raw = int(target_amount / price)
        lot = self.lot_size
        return (raw // lot) * lot

    def _round_price(self, price: float, symbol: str) -> float:
        """把价格按 price_tick 向下取整，挂限价单。"""
        tick = self.price_tick.get(symbol, 0.001)
        return math.floor(price / tick) * tick
