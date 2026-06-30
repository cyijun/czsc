"""BacktestVisualizer：把 ``CzscStrategyBase`` 回测结果一键输出为 HTML 报告 + 交易点位图。

整合 ``/mnt/h/可视化方法`` 中的三个可视化路径：

- 案例：基于 Event 的策略回测 + wbt HTML 报告
  → 用 ``wbt.generate_backtest_report`` 生成绩效报告（净值 / 回撤 / 收益分布）。
- 案例：lightweight_charts 缠论可视化
  → 用 ``czsc.utils.plotting.lightweight`` 绘制多周期 K 线 + 分型 + 笔。
- 案例：把信号函数画到 K 线主图
  → 把回测产出的 ``pairs_df`` 开平仓记录转成 marker 叠加到 K 线主图。

对外只暴露 ``BacktestVisualizer`` 一个类；输入 ``strategy + bars``，输出两个 HTML：

    - ``{tag}_report.html``：wbt 绩效报告
    - ``{tag}_chart.html``：lightweight-charts 交易点位图
"""

from __future__ import annotations

import bisect
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal, cast

import pandas as pd
from wbt import WeightBacktest, generate_backtest_report

from czsc import CzscStrategyBase
from czsc._native import BarGenerator, CzscTrader, RawBar
from czsc.utils.plotting.lightweight import _data, _html_renderer, _signals, _theme

ThemeName = Literal["light", "dark"]

__all__ = ["BacktestVisualizer"]


def _ts(dt: Any) -> int:
    """pd.Timestamp / datetime / ISO str → unix 秒整数。"""
    if not isinstance(dt, pd.Timestamp):
        dt = pd.Timestamp(dt)
    return int(dt.timestamp())


def _align_time_to_candle(ts: int, candle_times: Sequence[int]) -> int | None:
    """把 unix 秒对齐到某周期蜡烛时间序列（取 >= ts 的第一根 candle）。"""
    idx = bisect.bisect_left(candle_times, ts)
    if idx >= len(candle_times):
        return None
    return candle_times[idx]


class BacktestVisualizer:
    """CzscStrategyBase 回测可视化器。

    用法示例::

        from czsc import CzscStrategyBase
        from czsc.utils.plotting.backtest_visualizer import BacktestVisualizer

        viz = BacktestVisualizer(output_dir="_output/my_backtest")
        result = viz.run("single_event", strategy, bars, sdt="2020-06-01")
        print(result["outputs"])

    参数说明：
        - ``fee_rate`` / ``weight_type`` / ``yearly_days``：透传给 ``WeightBacktest`` 与 wbt 报告。
        - ``output_dir``：HTML 产物目录；默认 ``_output/backtest_visualizer``。
        - ``theme`` / ``show_sma`` / ``tail_bars``：控制 LWC 图表样式。
    """

    def __init__(
        self,
        *,
        fee_rate: float = 0.0002,
        weight_type: str = "ts",
        yearly_days: int = 252,
        output_dir: str | Path = "_output/backtest_visualizer",
        theme: ThemeName = "light",
        show_sma: Sequence[int] = (5, 20),
        tail_bars: int | None = None,
    ) -> None:
        self.fee_rate = fee_rate
        self.weight_type = weight_type
        self.yearly_days = yearly_days
        self.output_dir = Path(output_dir)
        self.theme: ThemeName = theme
        self.show_sma: tuple[int, ...] = tuple(show_sma)
        self.tail_bars = tail_bars

    @staticmethod
    def holds_to_weight_df(holds: pd.DataFrame) -> pd.DataFrame:
        """把 ``ResearchResult.holds_df()`` 转成 wbt 期望的 ``[dt, symbol, weight, price]`` 表。

        - ``pos`` 直接 rename 为 ``weight``；
        - 多 Position / 多周期共振时，同 ``(dt, symbol)`` 可能出现多行，按 ``groupby`` 求平均。
        """
        df = cast(pd.DataFrame, holds[["dt", "symbol", "pos", "price"]].copy())
        df.columns = ["dt", "symbol", "weight", "price"]
        if df.duplicated(["dt", "symbol"]).any():
            df = cast(
                pd.DataFrame,
                df.groupby(["dt", "symbol"], as_index=False).agg(
                    weight=("weight", "mean"),
                    price=("price", "first"),
                ),
            )
        df["weight"] = df["weight"].astype("float64")
        df["price"] = df["price"].astype("float64")
        return cast(pd.DataFrame, df[["dt", "symbol", "weight", "price"]])

    def _build_trader(self, bars: Sequence[RawBar], strategy: CzscStrategyBase) -> CzscTrader:
        """用 bars 构造一个只用于可视化的 CzscTrader（不带 Position / signals_config）。"""
        base_freq = strategy.base_freq
        freqs = list(getattr(strategy, "freqs", []) or [base_freq])
        if base_freq not in freqs:
            freqs = [base_freq, *freqs]

        bg = BarGenerator(base_freq=base_freq, freqs=freqs, max_count=max(10000, len(bars)))
        for bar in bars:
            bg.update(bar)
        return CzscTrader(bg, positions=[], signals_config=[])

    @staticmethod
    def _build_trade_marker_series(
        pairs: pd.DataFrame,
        base_pane: _data.FreqPayload,
    ) -> list[_signals.SignalSeries]:
        """把 ``pairs_df`` 的开平仓记录转成可叠加到 base freq pane 的 SignalSeries。"""
        if pairs.empty:
            return []

        candle_times = sorted(c["time"] for c in base_pane.main.candles)
        if not candle_times:
            return []

        # 开仓：arrowUp；平仓：arrowDown
        open_markers: list[_signals.SignalMarker] = []
        close_markers: list[_signals.SignalMarker] = []

        for idx, row in pairs.iterrows():
            direction = str(row["交易方向"])
            is_long = "多" in direction or "long" in direction.lower()

            open_ts = _align_time_to_candle(_ts(row["开仓时间"]), candle_times)
            close_ts = _align_time_to_candle(_ts(row["平仓时间"]), candle_times)
            if open_ts is None or close_ts is None:
                continue

            open_price = float(row["开仓价格"])
            close_price = float(row["平仓价格"])
            pnl = float(row["盈亏比例"])

            # 开仓方向：多 = up（红 / aboveBar），空 = down（绿 / belowBar）
            open_dir = "up" if is_long else "down"
            open_markers.append(
                _signals.SignalMarker(
                    time=open_ts,
                    value=f"开仓 {open_price:.3f} ({direction})",
                    v1="开仓",
                    color=_theme.direction_color(open_dir),
                    direction=open_dir,
                    vnum=cast(int, idx) + 1,
                )
            )

            # 平仓方向与开仓相反：多 → down，空 → up
            close_dir = "down" if is_long else "up"
            close_markers.append(
                _signals.SignalMarker(
                    time=close_ts,
                    value=f"平仓 {close_price:.3f} ({direction}) 盈亏 {pnl:+.2f}BP",
                    v1="平仓",
                    color=_theme.direction_color(close_dir),
                    direction=close_dir,
                    vnum=cast(int, idx) + 1,
                )
            )

        series_list: list[_signals.SignalSeries] = []
        if open_markers:
            series_list.append(
                _signals.SignalSeries(
                    key="开仓",
                    short_label="开仓",
                    color=_theme.MARKER_COLOR_UP,
                    shape="arrowUp",
                    position="aboveBar",
                    markers=open_markers,
                    value_index={},
                )
            )
        if close_markers:
            series_list.append(
                _signals.SignalSeries(
                    key="平仓",
                    short_label="平仓",
                    color=_theme.MARKER_COLOR_DOWN,
                    shape="arrowDown",
                    position="belowBar",
                    markers=close_markers,
                    value_index={},
                )
            )
        return series_list

    def _write_report(self, tag: str, dfw: pd.DataFrame) -> Path:
        """生成 wbt HTML 绩效报告并落盘。"""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / f"{tag}_report.html"
        generate_backtest_report(
            df=dfw,
            output_path=str(path),
            title=f"{tag} 回测绩效报告",
            fee_rate=self.fee_rate,
            weight_type=self.weight_type,
            yearly_days=self.yearly_days,
        )
        return path

    def _write_chart(
        self,
        tag: str,
        strategy: CzscStrategyBase,
        bars: Sequence[RawBar],
        pairs: pd.DataFrame,
    ) -> Path:
        """生成 lightweight-charts 交易点位图并落盘。"""
        ct = self._build_trader(bars, strategy)
        theme_cols = _theme.get_theme(self.theme)
        title = f"{ct.symbol} · {tag} 交易点位"

        payload = _data.build_from_trader(
            ct,
            theme=theme_cols,
            show_sma=self.show_sma,
            tail_bars=self.tail_bars,
            title=title,
        )

        # 把开平仓 marker 注入到 base freq pane
        base_freq = strategy.base_freq
        base_pane: _data.FreqPayload | None = None
        for pane in payload.panes:
            if pane.freq_label == base_freq:
                base_pane = pane
                break
        if base_pane is None and payload.panes:
            base_pane = payload.panes[-1]

        if base_pane is not None:
            base_pane.signals.extend(self._build_trade_marker_series(pairs, base_pane))

        html = _html_renderer.render(payload)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / f"{tag}_chart.html"
        path.write_text(html, encoding="utf-8")
        return path

    def run(
        self,
        tag: str,
        strategy: CzscStrategyBase,
        bars: Sequence[RawBar],
        *,
        sdt: str | None = None,
        html_report: bool = True,
        lwc_chart: bool = True,
    ) -> dict[str, Any]:
        """跑回测并产出可视化产物。

        :param tag: 本次回测标识，用于 HTML 文件名和标题。
        :param strategy: ``CzscStrategyBase`` 子类实例。
        :param bars: 基础周期 K 线列表（``RawBar``）。
        :param sdt: 回测开始日期，透传给 ``strategy.backtest``；为 ``None`` 时从第一根 K 线开始。
        :param html_report: 是否生成 wbt HTML 绩效报告。
        :param lwc_chart: 是否生成 lightweight-charts 交易点位图。
        :return: 包含 ``stats`` / ``weight_df`` / ``pairs`` / ``holds`` / ``signals`` /
            ``outputs`` 的字典。
        """
        if not bars:
            raise ValueError("bars 不能为空")

        res = strategy.backtest(bars, sdt=sdt) if sdt else strategy.backtest(bars)
        dfw = self.holds_to_weight_df(res.holds_df())
        wb = WeightBacktest(
            data=dfw,
            fee_rate=self.fee_rate,
            weight_type=self.weight_type,
            yearly_days=self.yearly_days,
        )

        result: dict[str, Any] = {
            "tag": tag,
            "stats": dict(wb.stats),
            "weight_df": dfw,
            "pairs": res.pairs_df(),
            "holds": res.holds_df(),
            "signals": res.signals_df(),
            "outputs": {},
        }

        if html_report:
            result["outputs"]["report_html"] = self._write_report(tag, dfw)
        if lwc_chart:
            result["outputs"]["chart_html"] = self._write_chart(tag, strategy, bars, res.pairs_df())

        return result
