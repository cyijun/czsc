"""QMT 交易接口抽象与 Mock 实现。

> 本模块不依赖真实的 XtQuant 库，而是定义一个与 QMT XtQuant API 结构相似的
> 抽象接口 ``QmtBroker``，并提供 ``MockQmtBroker`` 用于本地模拟盘验证。
>
> 当真实 QMT 申请下来后，只需实现 ``QmtBroker`` 的子类（封装 XtQuant 调用），
> 即可无缝替换 Mock，无需改动策略适配层。

QMT XtQuant 核心概念映射：
- ``subscribe`` / ``unsubscribe``：订阅/取消订阅标的行情
- ``place_order``：下单（对应 XtQuant 的 order_stock）
- ``cancel_order``：撤单
- ``query_asset``：查询账户资金
- ``query_positions``：查询持仓
- ``query_orders``：查询委托
- ``query_trades``：查询成交
- ``set_callbacks``：设置行情/订单/成交回调
- ``run``：启动事件循环
"""

from __future__ import annotations

import bisect
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Callable

import pandas as pd


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    LIMIT = "limit"
    MARKET = "market"


class OrderStatus(Enum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass
class Order:
    """模拟委托单。"""

    order_id: str
    symbol: str
    side: OrderSide
    volume: int
    price: float
    order_type: OrderType
    status: OrderStatus = OrderStatus.PENDING
    filled_volume: int = 0
    create_time: datetime | None = None
    update_time: datetime | None = None


@dataclass
class Trade:
    """模拟成交记录。"""

    trade_id: str
    order_id: str
    symbol: str
    side: OrderSide
    volume: int
    price: float
    trade_time: datetime


@dataclass
class Position:
    """模拟持仓。"""

    symbol: str
    volume: int
    avg_price: float
    available_volume: int = 0


@dataclass
class Asset:
    """模拟账户资产。"""

    total_asset: float = 0.0
    cash: float = 0.0
    market_value: float = 0.0


class QmtBroker(ABC):
    """QMT  broker 抽象基类。

    子类需要实现与 QMT XtQuant 的对接，接口签名保持与 Mock 一致，
    方便 ``CzscQmtAdapter`` 在不感知底层实现的情况下运行。
    """

    @abstractmethod
    def connect(self) -> None:
        """建立与 QMT / XtQuant 的连接。"""

    @abstractmethod
    def disconnect(self) -> None:
        """断开连接。"""

    @abstractmethod
    def subscribe(self, symbols: list[str]) -> None:
        """订阅行情。"""

    @abstractmethod
    def unsubscribe(self, symbols: list[str]) -> None:
        """取消订阅。"""

    @abstractmethod
    def place_order(
        self,
        symbol: str,
        side: OrderSide,
        volume: int,
        price: float,
        order_type: OrderType = OrderType.LIMIT,
    ) -> str:
        """下单，返回 order_id。"""

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """撤单，返回是否成功。"""

    @abstractmethod
    def query_asset(self) -> Asset:
        """查询账户资产。"""

    @abstractmethod
    def query_positions(self) -> list[Position]:
        """查询持仓。"""

    @abstractmethod
    def query_orders(self) -> list[Order]:
        """查询委托。"""

    @abstractmethod
    def query_trades(self) -> list[Trade]:
        """查询成交。"""

    @abstractmethod
    def set_callbacks(
        self,
        on_bar: Callable | None = None,
        on_tick: Callable | None = None,
        on_order: Callable | None = None,
        on_trade: Callable | None = None,
    ) -> None:
        """设置回调函数。"""

    @abstractmethod
    def run(self) -> None:
        """启动事件循环（阻塞）。"""


class MockQmtBroker(QmtBroker):
    """基于本地历史 K 线的 QMT Mock 模拟盘。

    特性：
    - 用本地分钟/日线数据回放行情
    - 支持限价单、市价单模拟撮合
    - 维护资金、持仓、委托、成交状态
    - T+1 规则：买入的份额下一个 bar 才可用（与 A 股一致）
    - 触发 on_bar 回调，供上层策略决策

    限制：
    - 暂不支持部分成交、滑点、涨跌停限制
    - 市价单按当前 bar close 价成交
    """

    def __init__(
        self,
        initial_cash: float = 1_000_000.0,
        data: dict[str, pd.DataFrame] | None = None,
        trade_date_range: tuple[str, str] | None = None,
        sleep_seconds: float = 0.0,
    ):
        """
        Args:
            initial_cash: 初始资金
            data: 行情数据，key=symbol, value=DataFrame(columns=[dt, open, high, low, close, vol, amount])
            trade_date_range: 交易回放起止 ("20240101", "20241231")
            sleep_seconds: 每根 bar 回放间隔（秒），0 表示最快速度
        """
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.positions: dict[str, Position] = {}
        self.orders: dict[str, Order] = {}
        self.trades: list[Trade] = []
        self.data = data or {}
        self.trade_date_range = trade_date_range
        self.sleep_seconds = sleep_seconds

        self._on_bar: Callable | None = None
        self._on_tick: Callable | None = None
        self._on_order: Callable | None = None
        self._on_trade: Callable | None = None

        self._subscribed: set[str] = set()
        self._running = False
        self._order_counter = 0
        self._trade_counter = 0

    # ---------- 抽象接口实现 ----------

    def connect(self) -> None:
        print(f"[MockQmt] 模拟连接成功，初始资金: {self.initial_cash:,.2f}")

    def disconnect(self) -> None:
        self._running = False
        print("[MockQmt] 模拟连接已断开")

    def subscribe(self, symbols: list[str]) -> None:
        for s in symbols:
            if s not in self.data:
                raise ValueError(f"MockQmt 未提供 {s} 的行情数据")
        self._subscribed.update(symbols)
        print(f"[MockQmt] 订阅: {symbols}")

    def unsubscribe(self, symbols: list[str]) -> None:
        self._subscribed.difference_update(symbols)

    def place_order(
        self,
        symbol: str,
        side: OrderSide,
        volume: int,
        price: float,
        order_type: OrderType = OrderType.LIMIT,
    ) -> str:
        self._order_counter += 1
        order_id = f"MO{self._order_counter:06d}"
        now = datetime.now()
        order = Order(
            order_id=order_id,
            symbol=symbol,
            side=side,
            volume=volume,
            price=price,
            order_type=order_type,
            create_time=now,
            update_time=now,
        )
        self.orders[order_id] = order
        if self._on_order:
            self._on_order(order)
        return order_id

    def cancel_order(self, order_id: str) -> bool:
        order = self.orders.get(order_id)
        if order and order.status == OrderStatus.PENDING:
            order.status = OrderStatus.CANCELLED
            order.update_time = datetime.now()
            if self._on_order:
                self._on_order(order)
            return True
        return False

    def query_asset(self) -> Asset:
        market_value = sum(
            pos.volume * pos.avg_price for pos in self.positions.values()
        )
        return Asset(total_asset=self.cash + market_value, cash=self.cash, market_value=market_value)

    def query_positions(self) -> list[Position]:
        return list(self.positions.values())

    def query_orders(self) -> list[Order]:
        return list(self.orders.values())

    def query_trades(self) -> list[Trade]:
        return self.trades

    def set_callbacks(
        self,
        on_bar: Callable | None = None,
        on_tick: Callable | None = None,
        on_order: Callable | None = None,
        on_trade: Callable | None = None,
    ) -> None:
        self._on_bar = on_bar
        self._on_tick = on_tick
        self._on_order = on_order
        self._on_trade = on_trade

    def run(self) -> None:
        """按时间对齐所有订阅标的的 bar，逐个触发 on_bar。"""
        self._running = True
        merged = self._merge_bars()
        if merged.empty:
            print("[MockQmt] 无可用行情数据，退出事件循环")
            return

        print(f"[MockQmt] 开始回放: {merged.index.min()} ~ {merged.index.max()}, 共 {len(merged)} 根 bar")
        for dt, row in merged.iterrows():
            if not self._running:
                break
            bar = {"dt": dt, "prices": row.to_dict()}
            self._match_orders(dt, bar["prices"])
            if self._on_bar:
                self._on_bar(bar)
            if self.sleep_seconds:
                time.sleep(self.sleep_seconds)

        print("[MockQmt] 回放结束")

    # ---------- 内部工具 ----------

    def _merge_bars(self) -> pd.DataFrame:
        """把多标的 close 价格按 dt 合并成宽表。"""
        frames = []
        for symbol in self._subscribed:
            df = self.data[symbol].copy()
            df["dt"] = pd.to_datetime(df["dt"])
            df = df.set_index("dt").sort_index()
            if self.trade_date_range:
                sdt, edt = self.trade_date_range
                df = df.loc[sdt:edt]
            frames.append(df[["close"]].rename(columns={"close": symbol}))

        if not frames:
            return pd.DataFrame()
        merged = frames[0]
        for f in frames[1:]:
            merged = merged.join(f, how="outer")
        return merged.sort_index().ffill()

    def _match_orders(self, dt: datetime, prices: dict[str, float]) -> None:
        """ simplistic 撮合：用当前 bar close 撮合所有未成交委托。"""
        for order in self.orders.values():
            if order.status not in (OrderStatus.PENDING, OrderStatus.PARTIAL):
                continue
            price = prices.get(order.symbol)
            if price is None or price <= 0:
                continue

            if order.order_type == OrderType.MARKET:
                fill_price = price
            elif order.side == OrderSide.BUY and price <= order.price:
                fill_price = order.price
            elif order.side == OrderSide.SELL and price >= order.price:
                fill_price = order.price
            else:
                continue

            fill_volume = order.volume - order.filled_volume
            self._execute_trade(dt, order, fill_volume, fill_price)

    def _execute_trade(self, dt: datetime, order: Order, volume: int, price: float) -> None:
        """更新订单、持仓、资金。"""
        amount = volume * price
        fee = amount * 0.0002  # 假设手续费 0.02%

        if order.side == OrderSide.BUY:
            if self.cash < amount + fee:
                order.status = OrderStatus.REJECTED
                order.update_time = dt
                if self._on_order:
                    self._on_order(order)
                return
            self.cash -= amount + fee
            pos = self.positions.get(order.symbol)
            if pos is None:
                self.positions[order.symbol] = Position(
                    symbol=order.symbol,
                    volume=volume,
                    avg_price=price,
                    available_volume=0,  # T+1
                )
            else:
                total_cost = pos.volume * pos.avg_price + amount
                pos.volume += volume
                pos.avg_price = total_cost / pos.volume
        else:  # SELL
            pos = self.positions.get(order.symbol)
            if pos is None or pos.available_volume < volume:
                order.status = OrderStatus.REJECTED
                order.update_time = dt
                if self._on_order:
                    self._on_order(order)
                return
            self.cash += amount - fee
            pos.volume -= volume
            pos.available_volume -= volume
            if pos.volume == 0:
                del self.positions[order.symbol]

        order.filled_volume += volume
        order.status = OrderStatus.FILLED if order.filled_volume >= order.volume else OrderStatus.PARTIAL
        order.update_time = dt

        self._trade_counter += 1
        trade = Trade(
            trade_id=f"MT{self._trade_counter:06d}",
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            volume=volume,
            price=price,
            trade_time=dt,
        )
        self.trades.append(trade)

        if self._on_trade:
            self._on_trade(trade)
        if self._on_order:
            self._on_order(order)

    def _apply_t1(self, dt: datetime) -> None:
        """每日开盘前把昨日买入变成可用。这里简化：每个 bar 都刷新可用。"""
        for pos in self.positions.values():
            pos.available_volume = pos.volume
