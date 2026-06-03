#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd


TARGETS = {
    "GMEC-Tide": 1.5,
    "GMEC-Ariel": 1.5,
    "GMEC-Tide-L": 2.5,
    "GMEC-Ariel-L": 2.5,
    "GMEC-Downy": 3.0,
}

ACCOUNT_ORDER = [
    "GMEC-Tide-L",
    "GMEC-Ariel-L",
    "GMEC-Tide",
    "GMEC-Ariel",
    "GMEC-Downy",
]

GENERIC_PLAN_SUFFIXES = {
    "洗衣液",
    "洗衣粉",
    "留香珠",
    "柔顺剂",
    "洗衣凝珠",
    "凝珠",
}

ACCOUNT_SUFFIXES = {
    "Ariel",
    "Tide",
    "Downy",
    "Ariel-L",
    "Tide-L",
    "Downy-L",
    "DOWNY",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate the JingZhunTong monitoring report from the latest Fabric CSV."
    )
    parser.add_argument(
        "--data-dir",
        default="/Users/sevenyip/Library/CloudStorage/OneDrive-insidemedia.net/LDY/rawdata/Fabric",
        help="Directory containing synced Fabric CSV files.",
    )
    parser.add_argument(
        "--xbook-dir",
        default="/Users/sevenyip/Library/Mobile Documents/iCloud~md~obsidian/Documents/Xbook/京准通数据分析报告",
        help="Directory for persisted daily Xbook reports.",
    )
    parser.add_argument(
        "--save-xbook",
        action="store_true",
        help="Write the generated report to the daily Xbook markdown file.",
    )
    parser.add_argument(
        "--format",
        choices=("discord", "full"),
        default="discord",
        help="Report format for stdout. Use 'discord' for chat-friendly output and 'full' for archive-style tables.",
    )
    parser.add_argument(
        "--output-dir",
        help="Optional runtime artifact directory. When provided, the script writes discord/full/meta artifacts for handoff.",
    )
    parser.add_argument(
        "--slot-label",
        help="Time slot label such as 0930 or 2015. Used for runtime artifact file names.",
    )
    parser.add_argument(
        "--report-date",
        help="Override report date (YYYY-MM-DD) for runtime artifact file names. Defaults to local today.",
    )
    return parser.parse_args()


def load_latest_csv(data_dir: Path) -> tuple[Path, pd.DataFrame]:
    candidates = sorted(data_dir.glob("*.csv"), key=lambda p: p.stat().st_mtime)
    if not candidates:
        raise FileNotFoundError(f"No CSV files found in {data_dir}")
    latest = candidates[-1]
    encodings = ("utf-8-sig", "utf-8", "gbk")
    last_error = None
    for encoding in encodings:
        try:
            return latest, pd.read_csv(latest, encoding=encoding)
        except Exception as exc:  # pragma: no cover - best effort fallback
            last_error = exc
    raise RuntimeError(f"Failed to load {latest}: {last_error}")


def classify_plan(plan: str) -> str:
    if "全店推广" in plan:
        return "HT"
    if "BI" in plan:
        return "Paid BI"
    if ("爆款推广" in plan) or ("新客" in plan):
        return "JST"
    return "SEM"


def contains_any(text: str, keywords: Iterable[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def normalize_plan_name(plan: str) -> str:
    plan = str(plan).strip()
    for prefix in (
        "爆款推广-",
        "爆款计划-",
        "新客计划-",
        "新客推广-",
        "新客-",
        "爆款推广",
        "爆款计划",
        "新客计划",
        "新客推广",
        "新客",
    ):
        if plan.startswith(prefix):
            plan = plan[len(prefix):].lstrip("-").strip()
            break
    return plan


def infer_sku_short_name(plans: list[str], sku_name: str) -> str:
    normalized = [normalize_plan_name(plan) for plan in plans if str(plan).strip()]
    normalized = list(dict.fromkeys(normalized))
    if not normalized:
        return str(sku_name).strip()

    token_lists = [[token for token in name.split("-") if token] for name in normalized]
    prefix_tokens: list[str] = []
    if len(token_lists) >= 2:
        for token_group in zip(*token_lists):
            if len(set(token_group)) == 1:
                prefix_tokens.append(token_group[0])
            else:
                break

    if prefix_tokens:
        tokens = prefix_tokens
    else:
        shortest = min(token_lists, key=len)
        tokens = shortest[:]

    while tokens and tokens[-1] in ACCOUNT_SUFFIXES:
        tokens.pop()
    while tokens and tokens[-1] in GENERIC_PLAN_SUFFIXES:
        tokens.pop()

    short_name = "-".join(tokens).strip("- ").strip()
    return short_name or str(sku_name).strip()


def focus_row(row: pd.Series) -> bool:
    account = row["账户昵称"]
    plan = row["推广计划"]
    unit = row["推广单元"]
    plan_type = row["计划类型"]

    if plan_type == "Paid BI":
        return False

    if account == "GMEC-Tide":
        if plan_type in ("JST", "SEM"):
            return contains_any(plan, ("免搓粉", "洗衣粉"))
        return plan_type == "HT" and unit == "汰渍（TIDE）-洗衣粉"

    if account == "GMEC-Ariel":
        if plan_type in ("JST", "SEM"):
            return contains_any(plan, ("免搓粉", "洗衣粉"))
        return plan_type == "HT" and unit == "碧浪-洗衣粉"

    if account in ("GMEC-Ariel-L", "GMEC-Tide-L"):
        return plan_type in ("JST", "SEM", "HT")

    if account == "GMEC-Downy":
        if plan_type in ("JST", "SEM"):
            return "留香珠" in unit
        return plan_type == "HT" and unit == "当妮（DOWNY）-留香珠"

    return False


def safe_div(numerator: float, denominator: float) -> float:
    if not denominator:
        return 0.0
    return numerator / denominator


def fmt_money(value: float) -> str:
    return f"{value:.2f}"


def fmt_ratio(value: float) -> str:
    return f"{value:.4f}"


def fmt_roi(value: float) -> str:
    return f"{value:.1f}"


def fmt_percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def account_sort_key(account: str) -> tuple[int, str]:
    try:
        return (ACCOUNT_ORDER.index(account), account)
    except ValueError:
        return (len(ACCOUNT_ORDER), account)


def resolve_report_date(report_date: str | None) -> str:
    return report_date or datetime.now().strftime("%Y-%m-%d")


def write_runtime_artifacts(
    output_dir: Path,
    report_date: str,
    slot_label: str,
    latest: Path,
    discord_report: str,
    full_report: str,
) -> dict[str, str]:
    artifact_dir = output_dir / report_date
    artifact_dir.mkdir(parents=True, exist_ok=True)

    discord_path = artifact_dir / f"{slot_label}_discord.md"
    full_path = artifact_dir / f"{slot_label}_full.md"
    meta_path = artifact_dir / f"{slot_label}_meta.json"

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    modified_at = datetime.fromtimestamp(latest.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    meta = {
        "report_date": report_date,
        "slot_label": slot_label,
        "generated_at": generated_at,
        "source_file_name": latest.name,
        "source_file_path": str(latest),
        "source_file_modified_at": modified_at,
        "discord_path": str(discord_path),
        "full_path": str(full_path),
    }

    discord_path.write_text(discord_report, encoding="utf-8")
    full_path.write_text(full_report, encoding="utf-8")
    meta_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "discord": str(discord_path),
        "full": str(full_path),
        "meta": str(meta_path),
    }


def build_tables(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    account_group = (
        df.groupby("账户昵称", dropna=False)[["花费", "总订单金额", "展现数", "点击数", "总订单行"]]
        .sum()
        .reset_index()
    )
    account_rows = []
    for _, row in account_group.iterrows():
        account = row["账户昵称"]
        spend = float(row["花费"])
        revenue = float(row["总订单金额"])
        impressions = float(row["展现数"])
        clicks = float(row["点击数"])
        orders = float(row["总订单行"])
        roi = safe_div(revenue, spend)
        cpc = safe_div(spend, clicks)
        ctr = safe_div(clicks, impressions)
        cvr = safe_div(orders, clicks)
        target = TARGETS[account]
        account_rows.append(
            {
                "账户": account,
                "总花费(SPD)": spend,
                "总ROI": roi,
                "总CPC": cpc,
                "总CTR": ctr,
                "总CVR": cvr,
                "ROI目标": target,
                "是否达标": "达标" if roi >= target else "未达标",
            }
        )
    account_summary = pd.DataFrame(account_rows)

    sku_source = df[df["计划类型"].isin(["JST", "SEM"])].copy()
    sku_name_map: dict[tuple[str, str], str] = {}
    sku_id_map: dict[tuple[str, str], str] = {}
    for (account, sku_name), group in sku_source.groupby(["账户昵称", "跟单SKU名称"], dropna=False):
        plans = sorted(set(group["推广计划"].astype(str)))
        sku_name_map[(str(account), str(sku_name))] = infer_sku_short_name(plans, str(sku_name))
        first_sku_id = str(group["跟单SKU ID"].iloc[0]).strip()
        sku_id_map[(str(account), str(sku_name))] = first_sku_id

    sku_group = (
        sku_source.groupby(["账户昵称", "跟单SKU名称"], dropna=False)[
            ["花费", "总订单金额", "展现数", "点击数", "总订单行"]
        ]
        .sum()
        .reset_index()
    )
    sku_rows = []
    for _, row in sku_group.iterrows():
        account = row["账户昵称"]
        sku_name = row["跟单SKU名称"]
        spend = float(row["花费"])
        revenue = float(row["总订单金额"])
        impressions = float(row["展现数"])
        clicks = float(row["点击数"])
        orders = float(row["总订单行"])
        roi = safe_div(revenue, spend)
        cpc = safe_div(spend, clicks)
        ctr = safe_div(clicks, impressions)
        cvr = safe_div(orders, clicks)
        target = TARGETS[account]
        status = "正常"
        if roi < target * 0.9:
            status = "🔻 低于目标10%以上"
        elif roi > target * 1.1:
            status = "🔺 高于目标10%以上"
        sku_rows.append(
            {
                "账户": account,
                "SKU简称": sku_name_map.get((account, sku_name), sku_name),
                "跟单SKU ID": sku_id_map.get((account, sku_name), ""),
                "跟单SKU名称": sku_name,
                "JST+SEM花费(SPD)": spend,
                "JST+SEM ROI": roi,
                "JST+SEM CPC": cpc,
                "JST+SEM CTR": ctr,
                "JST+SEM CVR": cvr,
                "ROI目标": target,
                "状态": status,
            }
        )
    sku_summary = pd.DataFrame(sku_rows).sort_values(
        ["账户", "状态", "JST+SEM花费(SPD)"], ascending=[True, True, False]
    )

    ht_source = df[df["计划类型"] == "HT"].copy()
    ht_group = (
        ht_source.groupby("账户昵称", dropna=False)[["花费", "总订单金额"]]
        .sum()
        .reset_index()
    )
    ht_rows = []
    for _, row in ht_group.iterrows():
        spend = float(row["花费"])
        revenue = float(row["总订单金额"])
        ht_rows.append(
            {
                "账户": row["账户昵称"],
                "HT总花费(SPD)": spend,
                "HT总ROI": safe_div(revenue, spend),
            }
        )
    ht_summary = pd.DataFrame(ht_rows)
    return account_summary, sku_summary, ht_summary


def build_full_report(
    latest: Path,
    account_summary: pd.DataFrame,
    sku_summary: pd.DataFrame,
    ht_summary: pd.DataFrame,
) -> str:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    modified_at = datetime.fromtimestamp(latest.stat().st_mtime).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    account_display = account_summary.copy()
    account_display["总花费(SPD)"] = account_display["总花费(SPD)"].map(fmt_money)
    account_display["总ROI"] = account_display["总ROI"].map(fmt_roi)
    account_display["总CPC"] = account_display["总CPC"].map(fmt_money)
    account_display["总CTR"] = account_display["总CTR"].map(fmt_percent)
    account_display["总CVR"] = account_display["总CVR"].map(fmt_percent)
    account_display["ROI目标"] = account_display["ROI目标"].map(fmt_roi)

    sku_display = sku_summary.copy()
    sku_display["JST+SEM花费(SPD)"] = sku_display["JST+SEM花费(SPD)"].map(fmt_money)
    sku_display["JST+SEM ROI"] = sku_display["JST+SEM ROI"].map(fmt_roi)
    sku_display["JST+SEM CPC"] = sku_display["JST+SEM CPC"].map(fmt_money)
    sku_display["JST+SEM CTR"] = sku_display["JST+SEM CTR"].map(fmt_percent)
    sku_display["JST+SEM CVR"] = sku_display["JST+SEM CVR"].map(fmt_percent)
    sku_display["ROI目标"] = sku_display["ROI目标"].map(fmt_roi)
    sku_display = sku_display.drop(columns=["跟单SKU名称"])
    flagged = sku_display[sku_display["状态"] != "正常"].copy()

    ht_display = ht_summary.copy()
    ht_display["HT总花费(SPD)"] = ht_display["HT总花费(SPD)"].map(fmt_money)
    ht_display["HT总ROI"] = ht_display["HT总ROI"].map(fmt_roi)

    sections = [
        "# 京准通数据监控报告",
        "",
        f"- 生成时间：{generated_at}",
        f"- 使用文件：`{latest.name}`",
        f"- 文件最后修改时间：{modified_at}",
        "- 数据口径：排除 `Paid BI`；账户总览包含 `JST + SEM + HT`；SKU 明细只统计 `JST + SEM`",
        "",
        "## 账户汇总",
        "",
        account_display.to_markdown(index=False),
        "",
        "## HT 汇总",
        "",
        ht_display.to_markdown(index=False) if len(ht_display) else "无 HT 数据",
        "",
        "## ROI 偏离目标超过 10% 的 SKU",
        "",
        flagged.to_markdown(index=False) if len(flagged) else "无异常 SKU",
        "",
        "## SKU JST+SEM 明细",
        "",
        sku_display.to_markdown(index=False) if len(sku_display) else "无 SKU 明细",
        "",
    ]
    return "\n".join(sections)


def build_discord_report(
    latest: Path,
    account_summary: pd.DataFrame,
    sku_summary: pd.DataFrame,
    ht_summary: pd.DataFrame,
) -> str:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    modified_at = datetime.fromtimestamp(latest.stat().st_mtime).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    ht_map = {
        row["账户"]: row for _, row in ht_summary.iterrows()
    }

    def build_conclusion(account: str, account_row: pd.Series, account_skus: pd.DataFrame) -> str:
        target = float(account_row["ROI目标"])
        account_roi = float(account_row["总ROI"])
        ht_row = ht_map.get(account)
        low_rows = account_skus[account_skus["状态"].astype(str).str.contains("低于目标", na=False)]

        if account_row["是否达标"] != "达标":
            if not low_rows.empty:
                drag = low_rows.sort_values("JST+SEM花费(SPD)", ascending=False).iloc[0]
                return f"结论：未达标，主要拖累 SKU 为 {drag['SKU简称']}。"
            return "结论：未达标，需要继续压低低效流量。"

        if ht_row is not None and float(ht_row["HT总ROI"]) < target:
            return "结论：达标，但 HT ROI 偏低。"

        if account_roi >= target:
            return "结论：达标，当前整体表现稳定。"

        return "结论：表现需继续观察。"

    sections = [
        "# 京准通数据监控",
        "",
        f"- 生成时间：{generated_at}",
        f"- 数据文件：`{latest.name}`",
        f"- 数据更新时间：{modified_at}",
        "- 口径：排除 `Paid BI`；账户总览=`JST+SEM+HT`；SKU 明细=`JST+SEM`",
        "",
    ]

    ordered_accounts = sorted(account_summary["账户"].tolist(), key=account_sort_key)

    for account in ordered_accounts:
        row = account_summary[account_summary["账户"] == account].iloc[0]
        account = row["账户"]
        status_icon = "✅" if row["是否达标"] == "达标" else "⚠️"
        ht_row = ht_map.get(account)
        account_skus = sku_summary[sku_summary["账户"] == account].copy()
        abnormal_skus = account_skus[account_skus["状态"] != "正常"].copy()
        normal_skus = account_skus[account_skus["状态"] == "正常"].copy()
        abnormal_skus = abnormal_skus.sort_values("JST+SEM花费(SPD)", ascending=False)
        normal_skus = normal_skus.sort_values("JST+SEM花费(SPD)", ascending=False)
        sections.extend(
            [
                f"## {status_icon} 账户：{account}",
                build_conclusion(account, row, account_skus),
                f"总花费 {fmt_money(float(row['总花费(SPD)']))} | 总ROI {fmt_roi(float(row['总ROI']))} | 总CPC {fmt_money(float(row['总CPC']))} | 总CTR {fmt_percent(float(row['总CTR']))} | 总CVR {fmt_percent(float(row['总CVR']))} | 目标 {fmt_roi(float(row['ROI目标']))}",
                "",
                "异常 SKU：JST+SEM",
            ]
        )

        if abnormal_skus.empty:
            sections.append("- 无异常 SKU")
        else:
            for _, sku_row in abnormal_skus.iterrows():
                status = str(sku_row["状态"])
                sku_id = str(sku_row.get("跟单SKU ID", ""))
                sid_str = f"({sku_id})" if sku_id else ""
                title = str(sku_row["SKU简称"])
                if status != "正常":
                    title = f"{title} {status}"
                sections.append(f"- {title}{sid_str}")
                sections.append(
                    f"  花费 {fmt_money(float(sku_row['JST+SEM花费(SPD)']))} | "
                    f"ROI {fmt_roi(float(sku_row['JST+SEM ROI']))} | "
                    f"CPC {fmt_money(float(sku_row['JST+SEM CPC']))} | "
                    f"CTR {fmt_percent(float(sku_row['JST+SEM CTR']))} | "
                    f"CVR {fmt_percent(float(sku_row['JST+SEM CVR']))}"
                )

        sections.extend(["", "正常 SKU：JST+SEM"])
        if normal_skus.empty:
            sections.append("- 无正常 SKU")
        else:
            for _, sku_row in normal_skus.iterrows():
                sku_id = str(sku_row.get("跟单SKU ID", ""))
                sid_str = f"({sku_id})" if sku_id else ""
                sections.append(
                    f"- {sku_row['SKU简称']}{sid_str} | 花费 {fmt_money(float(sku_row['JST+SEM花费(SPD)']))} | ROI {fmt_roi(float(sku_row['JST+SEM ROI']))}"
                )

        sections.extend(["", "HT"])
        if ht_row is None:
            sections.append("- 无 HT 数据")
        else:
            sections.append(
                f"- 花费 {fmt_money(float(ht_row['HT总花费(SPD)']))} | ROI {fmt_roi(float(ht_row['HT总ROI']))}"
            )
        sections.extend(["", "---", ""])

    sections.extend(
        [
            "## 说明",
            "",
            "- 如需完整 SKU 表格，查看 Xbook 归档版日报",
            "- 如需投放解释或策略建议，再交由 Luvian 补充分析",
            "",
        ]
    )
    return "\n".join(sections)


def main() -> None:
    args = parse_args()
    data_dir = Path(args.data_dir)
    xbook_dir = Path(args.xbook_dir)

    latest, df = load_latest_csv(data_dir)
    for column in ("账户昵称", "推广计划", "推广单元", "跟单SKU名称"):
        df[column] = df[column].fillna("").astype(str).str.strip()
    for column in ("展现数", "点击数", "花费", "总订单行", "总订单金额"):
        df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0)

    df["计划类型"] = df["推广计划"].map(classify_plan)
    focused = df[df.apply(focus_row, axis=1)].copy()

    account_summary, sku_summary, ht_summary = build_tables(focused)
    report = build_discord_report(latest, account_summary, sku_summary, ht_summary)
    full_report = build_full_report(latest, account_summary, sku_summary, ht_summary)
    artifact_paths: dict[str, str] | None = None

    if args.output_dir:
        slot_label = (args.slot_label or datetime.now().strftime("%H%M")).strip()
        report_date = resolve_report_date(args.report_date)
        artifact_paths = write_runtime_artifacts(
            Path(args.output_dir),
            report_date,
            slot_label,
            latest,
            report,
            full_report,
        )

    if args.save_xbook:
        xbook_dir.mkdir(parents=True, exist_ok=True)
        daily_name = f"京准通数据日报_{datetime.now().strftime('%Y-%m-%d')}.md"
        output_path = xbook_dir / daily_name
        output_path.write_text(full_report, encoding="utf-8")
        report += f"\n已写入 Xbook：`{output_path}`\n"

    if artifact_paths:
        report += (
            "\n工件已写入："
            f"\n- Discord：`{artifact_paths['discord']}`"
            f"\n- Full：`{artifact_paths['full']}`"
            f"\n- Meta：`{artifact_paths['meta']}`\n"
        )

    print(full_report if args.format == "full" else report)


if __name__ == "__main__":
    main()
