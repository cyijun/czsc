"""案例 19g：板块扫描结果汇总报告

汇总 19f_sector_scanner 产出的六个板块 CSV 与 19e 的个股/ETF 组合结果，
输出 2025-2026H1 期间各板块 baseline/combined 的平均表现、板块最优品种，
以及重点关注标的对比。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

OUTPUT_DIR = Path(__file__).resolve().parent / "_output" / "19g_sector_report"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

SECTOR_DIR = Path(__file__).resolve().parent / "_output" / "19f_sector_scanner"
SECTOR_FILES = {
    "半导体": "半导体_stats.csv",
    "科技": "科技_stats.csv",
    "能源": "能源_stats.csv",
    "金融": "金融_stats.csv",
    "医药": "医药_stats.csv",
    "消费": "消费_stats.csv",
}

FOCUS_FILE = Path(__file__).resolve().parent / "_output" / "19e_combined_resonance_fixed20" / "stats_table.csv"

METRICS = ["annual", "sharpe", "calmar", "max_dd", "win_rate", "trades"]


def load_sectors() -> pd.DataFrame:
    dfs = []
    for sector, filename in SECTOR_FILES.items():
        path = SECTOR_DIR / filename
        df = pd.read_csv(path)
        df["sector"] = sector
        dfs.append(df)
    return pd.concat(dfs, ignore_index=True)


def sector_summary(df: pd.DataFrame) -> pd.DataFrame:
    """按板块、策略汇总 2025-2026H1 的平均指标。"""
    filtered = df[df["period"] == "2025-2026H1"].copy()
    grouped = filtered.groupby(["sector", "strategy"])[METRICS].mean().reset_index()
    return grouped


def best_per_sector(df: pd.DataFrame, metric: str = "sharpe") -> pd.DataFrame:
    """每个板块 combined 策略下指定指标最优的品种。"""
    filtered = df[(df["period"] == "2025-2026H1") & (df["strategy"] == "combined")].copy()
    idx = filtered.groupby("sector")[metric].idxmax()
    return filtered.loc[idx, ["sector", "symbol", "strategy"] + METRICS].reset_index(drop=True)


def load_focus() -> pd.DataFrame:
    """加载 19e 的 510300.SH / 601012.SH / 688008.SH 的 2025-2026H1 结果。"""
    df = pd.read_csv(FOCUS_FILE, index_col=0).T.reset_index()
    df = df.rename(columns={"index": "col", "年化收益": "annual", "夏普比率": "sharpe", "卡玛比率": "calmar", "最大回撤": "max_dd"})

    rows = []
    for _, row in df.iterrows():
        col = row["col"]
        if "2025-2026H1" not in col:
            continue
        parts = col.split("_")
        symbol = parts[0]
        strategy = "_".join(parts[1:-1])
        rows.append(
            {
                "symbol": symbol,
                "strategy": strategy,
                "annual": float(row["annual"]),
                "sharpe": float(row["sharpe"]),
                "calmar": float(row["calmar"]),
                "max_dd": float(row["max_dd"]),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    df_sectors = load_sectors()

    summary = sector_summary(df_sectors)
    best = best_per_sector(df_sectors, metric="sharpe")

    print("=" * 70)
    print("2025-2026H1 板块平均表现")
    print("=" * 70)
    print(summary.round(4).to_string(index=False))

    print("\n" + "=" * 70)
    print("2025-2026H1 各板块 combined 夏普最优品种")
    print("=" * 70)
    print(best.round(4).to_string(index=False))

    focus = load_focus()
    print("\n" + "=" * 70)
    print("重点关注标的 2025-2026H1 表现（19e）")
    print("=" * 70)
    print(focus.round(4).to_string(index=False))

    summary_path = OUTPUT_DIR / "sector_summary_2025_2026H1.csv"
    summary.to_csv(summary_path, index=False)

    best_path = OUTPUT_DIR / "best_per_sector_2025_2026H1.csv"
    best.to_csv(best_path, index=False)

    focus_path = OUTPUT_DIR / "focus_symbols_2025_2026H1.csv"
    focus.to_csv(focus_path, index=False)

    print(f"\n[完成] 报告已保存至: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
