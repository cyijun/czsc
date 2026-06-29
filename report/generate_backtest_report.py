"""生成 CZSC 板块回测 PDF 报告

读取 docs/examples/_output/19f_sector_scanner/ 与 19e_combined_resonance_fixed20/
的 CSV 结果，汇总后输出 PDF 报告到 report/ 目录。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

REPORT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = REPORT_DIR.parent
SECTOR_DIR = PROJECT_ROOT / "docs" / "examples" / "_output" / "19f_sector_scanner"
FOCUS_FILE = PROJECT_ROOT / "docs" / "examples" / "_output" / "19e_combined_resonance_fixed20" / "stats_table.csv"

SECTOR_FILES = {
    "半导体": "半导体_stats.csv",
    "科技": "科技_stats.csv",
    "能源": "能源_stats.csv",
    "金融": "金融_stats.csv",
    "医药": "医药_stats.csv",
    "消费": "消费_stats.csv",
}
METRICS = ["annual", "sharpe", "calmar", "max_dd", "win_rate", "trades"]


def register_chinese_font() -> None:
    """注册文泉驿微米黑，确保 PDF 中文字符正常显示。"""
    font_path = "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"
    pdfmetrics.registerFont(TTFont("WQY", font_path))


def load_sectors() -> pd.DataFrame:
    dfs = []
    for sector, filename in SECTOR_FILES.items():
        path = SECTOR_DIR / filename
        df = pd.read_csv(path)
        df["sector"] = sector
        dfs.append(df)
    return pd.concat(dfs, ignore_index=True)


def sector_summary(df: pd.DataFrame) -> pd.DataFrame:
    filtered = df[df["period"] == "2025-2026H1"].copy()
    grouped = filtered.groupby(["sector", "strategy"])[METRICS].mean().reset_index()
    grouped["trades"] = grouped["trades"].round().astype(int)
    return grouped


def best_per_sector(df: pd.DataFrame, metric: str = "sharpe") -> pd.DataFrame:
    filtered = df[(df["period"] == "2025-2026H1") & (df["strategy"] == "combined")].copy()
    idx = filtered.groupby("sector")[metric].idxmax()
    best = filtered.loc[idx, ["sector", "symbol"] + METRICS].reset_index(drop=True)
    best["trades"] = best["trades"].round().astype(int)
    return best


def load_focus() -> pd.DataFrame:
    df = pd.read_csv(FOCUS_FILE, index_col=0).T.reset_index()
    df = df.rename(
        columns={
            "index": "col",
            "年化收益": "annual",
            "夏普比率": "sharpe",
            "卡玛比率": "calmar",
            "最大回撤": "max_dd",
        }
    )
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


def make_styles():
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="ChineseTitle",
            fontName="WQY",
            fontSize=20,
            leading=26,
            alignment=1,
            spaceAfter=18,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ChineseHeading",
            fontName="WQY",
            fontSize=14,
            leading=20,
            spaceBefore=16,
            spaceAfter=10,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ChineseBody",
            fontName="WQY",
            fontSize=10,
            leading=15,
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ChineseSmall",
            fontName="WQY",
            fontSize=8,
            leading=12,
        )
    )
    return styles


def df_to_table(df: pd.DataFrame, col_names: list[str] | None = None) -> Table:
    """将 DataFrame 转换为 reportlab Table，支持自定义列名（中文）。"""
    data = [col_names or df.columns.tolist()]
    for _, row in df.iterrows():
        formatted = []
        for col, v in zip(df.columns, row.values, strict=True):
            if col == "trades":
                formatted.append(str(int(round(v))))
            elif isinstance(v, float):
                formatted.append(f"{v:.4f}")
            else:
                formatted.append(str(v))
        data.append(formatted)
    table = Table(data, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "WQY"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4F81BD")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F2F2")]),
            ]
        )
    )
    return table


def build_pdf(output_path: Path) -> None:
    register_chinese_font()
    styles = make_styles()

    df_sectors = load_sectors()
    summary = sector_summary(df_sectors)
    best = best_per_sector(df_sectors, metric="sharpe")
    focus = load_focus()

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )
    story: list = []

    # 封面
    story.append(Paragraph("CZSC 板块三买策略回测报告", styles["ChineseTitle"]))
    story.append(Paragraph("回测区间：2025-01-01 ~ 2026-06-12", styles["ChineseBody"]))
    story.append(Paragraph("策略说明：30 分钟三买开多 + 30/60 分钟共振过滤 + 固定持仓 20 根 K 线", styles["ChineseBody"]))
    story.append(Paragraph("手续费：万分之二（0.0002）", styles["ChineseBody"]))
    story.append(Spacer(1, 1 * cm))

    # 板块平均表现
    story.append(Paragraph("一、板块平均表现（2025-2026H1）", styles["ChineseHeading"]))
    story.append(
        Paragraph(
            "下表汇总了六个板块在 baseline（30min 笔向下平仓）与 combined（30+60min 共振 + fixed20）策略下的平均表现。",
            styles["ChineseBody"],
        )
    )
    summary_display = summary.copy()
    summary_display.columns = ["板块", "策略", "年化收益", "夏普", "卡玛", "最大回撤", "胜率", "交易次数"]
    story.append(df_to_table(summary_display.round(4)))
    story.append(Spacer(1, 0.5 * cm))

    # 板块最优品种
    story.append(Paragraph("二、各板块 combined 策略最优品种", styles["ChineseHeading"]))
    story.append(
        Paragraph(
            "按 combined 策略夏普比率排序，列出每个板块表现最好的标的。",
            styles["ChineseBody"],
        )
    )
    best_display = best.copy()
    best_display.columns = ["板块", "品种", "年化收益", "夏普", "卡玛", "最大回撤", "胜率", "交易次数"]
    story.append(df_to_table(best_display.round(4)))
    story.append(Spacer(1, 0.5 * cm))

    # 重点关注标的
    story.append(Paragraph("三、重点关注标的对比（19e）", styles["ChineseHeading"]))
    story.append(
        Paragraph(
            "包含沪深 300 ETF（510300.SH）、隆基绿能（601012.SH）与澜起科技（688008.SH）三种策略变体的表现。",
            styles["ChineseBody"],
        )
    )
    focus_display = focus.copy()
    focus_display.columns = ["品种", "策略", "年化收益", "夏普", "卡玛", "最大回撤"]
    story.append(df_to_table(focus_display.round(4)))

    story.append(PageBreak())

    # 结论与建议
    story.append(Paragraph("四、结论与建议", styles["ChineseHeading"]))
    conclusions = [
        "1. combined 策略在成长板块效果显著：半导体板块平均年化从 14.60% 提升至 32.98%，夏普从 0.64 提升至 1.25；科技板块年化从 1.03% 提升至 13.23%，夏普从 0.17 提升至 0.72。",
        "2. 板块 ETF 普遍优于板块内个股：除金融板块外，其余板块 combined 策略夏普最优品种均为 ETF，说明该策略更适合 Beta 清晰、流动性好的指数标的。",
        "3. 全场最佳标的为半导体 ETF（159995.SZ）：combined 策略下年化收益 46.97%、夏普 2.43、卡玛 6.15、胜率 72.73%，回撤仅 7.63%。",
        "4. 澜起科技（688008.SH）是个股中的佼佼者：30_60_fixed20 策略年化 63.79%、夏普 1.73、卡玛 5.02，表现甚至优于多数 ETF。",
        "5. 医药与消费板块在当前窗口表现不佳：combined 策略未能扭转亏损，建议暂时规避或改用其他信号体系。",
        "6. 隆基绿能（601012.SH）较弱：仅 30_60_fixed20 微盈（年化 4.24%，夏普 0.24），不建议作为该策略的重点标的。",
        "7. 沪深 300 ETF（510300.SH）表现稳健：fixed20 与 30_60_fixed20 均取得正收益，夏普分别为 0.75 与 0.64，适合作为低风险底仓。",
    ]
    for text in conclusions:
        story.append(Paragraph(text, styles["ChineseBody"]))

    story.append(Spacer(1, 1 * cm))
    story.append(Paragraph("免责声明：本报告仅供策略研究参考，不构成投资建议。", styles["ChineseSmall"]))

    doc.build(story)
    print(f"[完成] PDF 报告已生成: {output_path}")


def main() -> None:
    output_path = REPORT_DIR / "czsc_sector_backtest_report.pdf"
    build_pdf(output_path)


if __name__ == "__main__":
    main()
