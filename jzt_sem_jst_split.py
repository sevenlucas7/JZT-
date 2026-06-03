#!/usr/bin/env python3
"""JZT SEM/JST split computation.

Reads the same Fabric CSV as jzt_report.py and outputs per-SKU SEM and JST
split metrics alongside the combined JST+SEM numbers.

Usage:
    python3 jzt_sem_jst_split.py --output-dir ... --slot-label 0802 --report-date 2026-05-31
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import math
import pandas as pd

TARGETS = {
    "GMEC-Tide": 1.5,
    "GMEC-Ariel": 1.5,
    "GMEC-Tide-L": 2.5,
    "GMEC-Ariel-L": 2.5,
    "GMEC-Downy": 3.0,
}

LEGACY_ACCOUNTS = {"GMEC-Tide", "GMEC-Ariel"}
PWD_ACCOUNTS = {"GMEC-Tide-L", "GMEC-Ariel-L"}

GENERIC_PLAN_SUFFIXES = {
    "洗衣液", "洗衣粉", "留香珠", "柔顺剂", "洗衣凝珠", "凝珠",
}

ACCOUNT_SUFFIXES = {
    "Ariel", "Tide", "Downy", "Ariel-L", "Tide-L", "Downy-L", "DOWNY",
}

ACCOUNT_ORDER = [
    "GMEC-Tide-L", "GMEC-Ariel-L", "GMEC-Tide", "GMEC-Ariel", "GMEC-Downy",
]

DATA_DIR = Path(
    os.environ.get(
        "JZT_DATA_DIR",
        "/Users/sevenyip/Library/CloudStorage/OneDrive-insidemedia.net/LDY/rawdata/Fabric",
    )
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--output-dir", required=True, help="Runtime artifact directory")
    p.add_argument("--slot-label", required=True, help="Time slot label (e.g. 0802)")
    p.add_argument(
        "--report-date",
        default=datetime.now().strftime("%Y-%m-%d"),
        help="Report date YYYY-MM-DD",
    )
    return p.parse_args()


def load_latest_csv(data_dir: Path) -> tuple[Path, pd.DataFrame]:
    candidates = sorted(data_dir.glob("*.csv"), key=lambda p: p.stat().st_mtime)
    if not candidates:
        raise FileNotFoundError(f"No CSV files found in {data_dir}")
    latest = candidates[-1]
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return latest, pd.read_csv(latest, encoding=enc)
        except Exception:
            continue
    raise RuntimeError(f"Failed to load {latest}")


def safe_div(n: float, d: float) -> float:
    return n / d if d else 0.0


def load_previous_split(data_dir: Path, report_date: str, slot_label: str) -> dict | None:
    """Load a previous split.json from the data directory.

    Args:
        data_dir: Path to the data directory (e.g. ~/JZT报数/data)
        report_date: Date string YYYY-MM-DD
        slot_label: Time slot label (e.g. 0702)

    Returns:
        The loaded split.json dict, or None if not found.
    """
    # Try current directory first, then data_dir
    candidates = [
        data_dir / f"{report_date}_{slot_label}_split.json",
        Path("data") / f"{report_date}_{slot_label}_split.json",
    ]
    for path in candidates:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass
    return None


def get_previous_slot_label(current_slot: str) -> tuple[str, str]:
    """Get the 2-hour-ago slot label and yesterday's date.

    Args:
        current_slot: Current slot label (e.g. 0902)

    Returns:
        (previous_slot_label, yesterday_date_str)
    """
    hour = int(current_slot[:2])
    minute = int(current_slot[2:])
    prev_hour = (hour - 2) % 24
    prev_slot = f"{prev_hour:02d}{minute:02d}"

    yesterday = datetime.now() - timedelta(days=1)
    yesterday_str = yesterday.strftime("%Y-%m-%d")

    return prev_slot, yesterday_str


def compute_delta_badge(current: float, previous: float) -> dict:
    """Compute delta between current and previous value.

    Returns:
        dict with keys: diff (absolute), pct (percentage), direction ("up"/"down")
    """
    if previous is None or previous == 0:
        return {"diff": 0, "pct": 0, "direction": "neutral"}
    diff = current - previous
    pct = (diff / abs(previous)) * 100 if previous != 0 else 0
    direction = "up" if diff > 0 else "down" if diff < 0 else "neutral"
    return {"diff": round(diff, 2), "pct": round(pct, 2), "direction": direction}


def build_account_totals(skus: list[dict], ht: list[dict]) -> dict:
    """Build per-account totals for spend and ROI.

    Args:
        skus: List of SKU dicts from split.json
        ht: List of HT dicts from split.json

    Returns:
        dict mapping account name to totals
    """
    totals = {}
    for sku in skus:
        account = sku["账户"]
        if account not in totals:
            totals[account] = {"综合花费": 0, "JST花费": 0, "SEM花费": 0, "总订单金额": 0}
        totals[account]["综合花费"] += sku.get("综合花费(SPD)", 0)
        totals[account]["JST花费"] += sku.get("JST花费(SPD)", 0)
        totals[account]["SEM花费"] += sku.get("SEM花费(SPD)", 0)
        # Compute combined revenue from combined ROI * spend
        totals[account]["总订单金额"] += sku.get("综合ROI(含JST+SEM)", 0) * sku.get("综合花费(SPD)", 0)

    for ht_row in ht:
        account = ht_row["账户"]
        if account not in totals:
            totals[account] = {"综合花费": 0, "JST花费": 0, "SEM花费": 0, "总订单金额": 0}
        totals[account]["综合花费"] += ht_row.get("HT花费(SPD)", 0)

    # Compute ROI
    for account, data in totals.items():
        spend = data["综合花费"]
        revenue = data["总订单金额"]
        data["综合ROI"] = round(safe_div(revenue, spend), 2)
        data["HT花费"] = next((h["HT花费(SPD)"] for h in ht if h["账户"] == account), 0)

    return totals


def compute_deltas(current_data: dict, prev_2h_data: dict | None, prev_day_data: dict | None) -> dict:
    """Compute deltas for overall KPIs vs previous time periods.

    Args:
        current_data: Current split.json dict
        prev_2h_data: split.json from 2 hours ago (or None)
        prev_day_data: split.json from yesterday same time (or None)

    Returns:
        dict with top-level deltas (total_spend, total_roi) and per-account deltas
    """
    current_totals = build_account_totals(current_data.get("skus", []), current_data.get("ht", []))

    # Overall totals (sum across all accounts)
    current_total_spend = sum(t["综合花费"] for t in current_totals.values())
    current_total_revenue = sum(t["总订单金额"] for t in current_totals.values())
    current_total_roi = safe_div(current_total_revenue, current_total_spend)

    deltas = {
        "total_spend": {
            "vs_2h": compute_delta_badge(
                current_total_spend,
                sum(t["综合花费"] for t in build_account_totals(prev_2h_data["skus"], prev_2h_data.get("ht", [])).values()) if prev_2h_data else None
            ),
            "vs_yesterday": compute_delta_badge(
                current_total_spend,
                sum(t["综合花费"] for t in build_account_totals(prev_day_data["skus"], prev_day_data.get("ht", [])).values()) if prev_day_data else None
            ),
        },
        "total_roi": {
            "vs_2h": compute_delta_badge(
                current_total_roi,
                _compute_overall_roi(prev_2h_data) if prev_2h_data else None
            ),
            "vs_yesterday": compute_delta_badge(
                current_total_roi,
                _compute_overall_roi(prev_day_data) if prev_day_data else None
            ),
        },
    }

    # Per-account deltas
    deltas["accounts"] = {}
    for account, ct in current_totals.items():
        prev_2h_acct = build_account_totals(prev_2h_data["skus"], prev_2h_data.get("ht", [])).get(account, {}) if prev_2h_data else {}
        prev_day_acct = build_account_totals(prev_day_data["skus"], prev_day_data.get("ht", [])).get(account, {}) if prev_day_data else {}

        deltas["accounts"][account] = {
            "综合花费": {
                "vs_2h": compute_delta_badge(ct["综合花费"], prev_2h_acct.get("综合花费")),
                "vs_yesterday": compute_delta_badge(ct["综合花费"], prev_day_acct.get("综合花费")),
            },
            "综合ROI": {
                "vs_2h": compute_delta_badge(ct["综合ROI"], prev_2h_acct.get("综合ROI")),
                "vs_yesterday": compute_delta_badge(ct["综合ROI"], prev_day_acct.get("综合ROI")),
            },
        }

    # Per-SKU deltas
    deltas["skus"] = []
    for sku in current_data.get("skus", []):
        sku_key = (sku["账户"], sku["SKU ID"])
        prev_2h_sku = _find_sku(prev_2h_data, sku_key) if prev_2h_data else None
        prev_day_sku = _find_sku(prev_day_data, sku_key) if prev_day_data else None

        sku_deltas = {
            "账户": sku["账户"],
            "SKU ID": sku["SKU ID"],
            "综合花费": {
                "vs_2h": compute_delta_badge(sku["综合花费(SPD)"], prev_2h_sku["综合花费(SPD)"] if prev_2h_sku else None),
                "vs_yesterday": compute_delta_badge(sku["综合花费(SPD)"], prev_day_sku["综合花费(SPD)"] if prev_day_sku else None),
            },
            "综合ROI": {
                "vs_2h": compute_delta_badge(sku["综合ROI(含JST+SEM)"], prev_2h_sku["综合ROI(含JST+SEM)"] if prev_2h_sku else None),
                "vs_yesterday": compute_delta_badge(sku["综合ROI(含JST+SEM)"], prev_day_sku["综合ROI(含JST+SEM)"] if prev_day_sku else None),
            },
        }
        deltas["skus"].append(sku_deltas)

    return deltas


def _compute_overall_roi(split_data: dict) -> float | None:
    """Compute overall ROI across all accounts from a split.json."""
    if not split_data:
        return None
    totals = build_account_totals(split_data.get("skus", []), split_data.get("ht", []))
    total_spend = sum(t["综合花费"] for t in totals.values())
    total_revenue = sum(t["总订单金额"] for t in totals.values())
    return safe_div(total_revenue, total_spend) if total_spend else None


def _find_sku(split_data: dict, sku_key: tuple) -> dict | None:
    """Find a SKU by (account, sku_id) in split.json."""
    if not split_data:
        return None
    for sku in split_data.get("skus", []):
        if (sku["账户"], sku["SKU ID"]) == sku_key:
            return sku
    return None


def contains_any(text: str, keywords: set) -> bool:
    return any(kw in text for kw in keywords)


def normalize_plan_name(plan: str) -> str:
    plan = str(plan).strip()
    for prefix in (
        "爆款推广-", "爆款计划-", "新客计划-", "新客推广-", "新客-",
        "爆款推广", "爆款计划", "新客计划", "新客推广", "新客",
    ):
        if plan.startswith(prefix):
            plan = plan[len(prefix):].lstrip("-").strip()
            break
    return plan


def infer_sku_short_name(plans: list[str], sku_name: str) -> str:
    normalized = [normalize_plan_name(p) for p in plans if str(p).strip()]
    normalized = list(dict.fromkeys(normalized))
    if not normalized:
        return str(sku_name).strip()
    token_lists = [[t for t in name.split("-") if t] for name in normalized]
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


def main() -> None:
    args = parse_args()
    latest, df = load_latest_csv(DATA_DIR)

    for col in ("账户昵称", "推广计划", "推广单元", "跟单SKU名称"):
        df[col] = df[col].fillna("").astype(str).str.strip()
    for col in ("展现数", "点击数", "花费", "总订单行", "总订单金额"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # Classify plan type
    def classify(plan: str) -> str:
        if "全店推广" in plan:
            return "HT"
        if "BI" in plan:
            return "Paid BI"
        return "JST" if ("爆款" in plan or "新客" in plan) else "SEM"

    df["计划类型"] = df["推广计划"].map(classify)

    # Apply same focus_row filtering as jzt_report.py
    def contains_any_text(text: str, keywords: tuple) -> bool:
        return any(kw in text for kw in keywords)

    def focus_row(r):
        account = r["账户昵称"]
        plan = r["推广计划"]
        unit = r["推广单元"]
        plan_type = r["计划类型"]
        if plan_type == "Paid BI":
            return False
        if account == "GMEC-Tide":
            if plan_type in ("JST", "SEM"):
                return contains_any_text(plan, ("免搓粉", "洗衣粉"))
            return plan_type == "HT" and unit == "汰渍（TIDE）-洗衣粉"
        if account == "GMEC-Ariel":
            if plan_type in ("JST", "SEM"):
                return contains_any_text(plan, ("免搓粉", "洗衣粉"))
            return plan_type == "HT" and unit == "碧浪-洗衣粉"
        if account in ("GMEC-Ariel-L", "GMEC-Tide-L"):
            return plan_type in ("JST", "SEM", "HT")
        if account == "GMEC-Downy":
            if plan_type in ("JST", "SEM"):
                return "留香珠" in unit
            return plan_type == "HT" and unit == "当妮（DOWNY）-留香珠"
        return False

    df["_focus"] = df.apply(focus_row, axis=1)
    focused = df[df["_focus"]].copy()
    df = focused  # replace df with filtered version

    # Filter: exclude Paid BI, keep only JST and SEM for SKU split
    sku_df = df[df["计划类型"].isin(["JST", "SEM"])].copy()

    # Build SKU short name map (same logic as jzt_report.py)
    sku_name_map: dict[tuple[str, str], str] = {}
    sku_id_map: dict[tuple[str, str], str] = {}
    for (account, sku_name), group in sku_df.groupby(["账户昵称", "跟单SKU名称"], dropna=False):
        plans = sorted(set(group["推广计划"].astype(str)))
        sku_name_map[(str(account), str(sku_name))] = infer_sku_short_name(plans, str(sku_name))
        # Grab SKU ID from first row of this group
        first_sku_id = str(group["跟单SKU ID"].iloc[0]).strip()
        sku_id_map[(str(account), str(sku_name))] = first_sku_id

    # Per-SKU combined (JST+SEM)
    combined = (
        sku_df.groupby(["账户昵称", "跟单SKU名称"])[["花费", "总订单金额", "展现数", "点击数", "总订单行"]]
        .sum()
        .reset_index()
    )

    # Per-SKU JST only
    jst = (
        sku_df[sku_df["计划类型"] == "JST"]
        .groupby(["账户昵称", "跟单SKU名称"])[["花费", "总订单金额", "展现数", "点击数", "总订单行"]]
        .sum()
        .reset_index()
        .rename(
            columns={
                "花费": "JST花费(SPD)",
                "总订单金额": "JST总订单金额",
                "展现数": "JST展现数",
                "点击数": "JST点击数",
                "总订单行": "JST总订单行",
            }
        )
    )

    # Per-SKU SEM only
    sem = (
        sku_df[sku_df["计划类型"] == "SEM"]
        .groupby(["账户昵称", "跟单SKU名称"])[["花费", "总订单金额", "展现数", "点击数", "总订单行"]]
        .sum()
        .reset_index()
        .rename(
            columns={
                "花费": "SEM花费(SPD)",
                "总订单金额": "SEM总订单金额",
                "展现数": "SEM展现数",
                "点击数": "SEM点击数",
                "总订单行": "SEM总订单行",
            }
        )
    )

    # Merge
    merged = combined.merge(jst, on=["账户昵称", "跟单SKU名称"], how="left").merge(
        sem, on=["账户昵称", "跟单SKU名称"], how="left"
    )

    rows = []
    for _, r in merged.iterrows():
        account = r["账户昵称"]
        sku_name = r["跟单SKU名称"]
        target = TARGETS.get(account, 2.5)

        # Combined
        comb_roi = safe_div(float(r["总订单金额"]), float(r["花费"]))
        comb_cpc = safe_div(float(r["花费"]), float(r["点击数"]))
        comb_ctr = safe_div(float(r["点击数"]), float(r["展现数"]))
        comb_cvr = safe_div(float(r["总订单行"]), float(r["点击数"]))

        # JST
        jst_spend = float(r.get("JST花费(SPD)", 0) if not (isinstance(r.get("JST花费(SPD)"), float) and math.isnan(r.get("JST花费(SPD)"))) else 0)
        jst_roi = safe_div(float(r.get("JST总订单金额", 0) if not (isinstance(r.get("JST总订单金额"), float) and math.isnan(r.get("JST总订单金额"))) else 0), jst_spend)
        jst_cpc = safe_div(jst_spend, float(r.get("JST点击数", 0) if not (isinstance(r.get("JST点击数"), float) and math.isnan(r.get("JST点击数"))) else 0))

        # SEM
        sem_spend = float(r.get("SEM花费(SPD)", 0) if not (isinstance(r.get("SEM花费(SPD)"), float) and math.isnan(r.get("SEM花费(SPD)"))) else 0)
        sem_roi = safe_div(float(r.get("SEM总订单金额", 0) if not (isinstance(r.get("SEM总订单金额"), float) and math.isnan(r.get("SEM总订单金额"))) else 0), sem_spend)
        sem_cpc = safe_div(sem_spend, float(r.get("SEM点击数", 0) if not (isinstance(r.get("SEM点击数"), float) and math.isnan(r.get("SEM点击数"))) else 0))

        status = "正常"
        if comb_roi < target * 0.9:
            status = "🔻 低于目标10%以上"
        elif comb_roi > target * 1.1:
            status = "🔺 高于目标10%以上"

        rows.append(
            {
                "账户": account,
                "SKU名称": sku_name,
                "SKU简称": sku_name_map.get((account, sku_name), sku_name).lstrip("_").strip(),
                "SKU ID": sku_id_map.get((account, sku_name), ""),
                "综合ROI(含JST+SEM)": round(comb_roi, 2),
                "综合花费(SPD)": round(float(r["花费"]), 2),
                "综合CPC": round(comb_cpc, 2),
                "综合CTR": round(comb_ctr, 4),
                "综合CVR": round(comb_cvr, 4),
                "状态": status,
                "ROI目标": target,
                "JST花费(SPD)": round(jst_spend, 2),
                "JST ROI": round(jst_roi, 2),
                "JST CPC": round(jst_cpc, 4),
                "SEM花费(SPD)": round(sem_spend, 2),
                "SEM ROI": round(sem_roi, 2),
                "SEM CPC": round(sem_cpc, 4),
            }
        )

    output = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_file": latest.name,
        "slot_label": args.slot_label,
        "report_date": args.report_date,
        "sku_count": len(rows),
        "skus": rows,
    }

    # Compute HT totals per account
    ht_source = df[df["计划类型"] == "HT"].copy()
    ht_rows = []
    if not ht_source.empty:
        ht_group = (
            ht_source.groupby("账户昵称", dropna=False)[["花费", "总订单金额"]]
            .sum()
            .reset_index()
        )
        for _, r in ht_group.iterrows():
            ht_spend = float(r["花费"])
            ht_roi = safe_div(float(r["总订单金额"]), ht_spend)
            ht_rows.append({
                "账户": r["账户昵称"],
                "HT花费(SPD)": round(ht_spend, 2),
                "HT ROI": round(ht_roi, 2),
            })
    output["ht"] = ht_rows

    # Build account_totals for current data
    account_totals = build_account_totals(rows, ht_rows)
    output["account_totals"] = {}
    for account, data in account_totals.items():
        output["account_totals"][account] = {
            "综合花费": round(data["综合花费"], 2),
            "综合ROI": data["综合ROI"],
            "JST花费": round(data["JST花费"], 2),
            "SEM花费": round(data["SEM花费"], 2),
            "HT花费": round(data.get("HT花费", 0), 2),
        }

    # Compute deltas: load previous splits (2h ago and yesterday same time)
    prev_slot_label, yesterday_str = get_previous_slot_label(args.slot_label)
    prev_2h_data = load_previous_split(Path(args.output_dir), args.report_date, prev_slot_label)
    prev_day_data = load_previous_split(Path(args.output_dir), yesterday_str, args.slot_label)

    # Also try loading from data/ relative path for git-cloned repos
    if not prev_2h_data:
        prev_2h_data = load_previous_split(Path("data"), args.report_date, prev_slot_label)
    if not prev_day_data:
        prev_day_data = load_previous_split(Path("data"), yesterday_str, args.slot_label)

    deltas = compute_deltas(output, prev_2h_data, prev_day_data)
    output["deltas"] = deltas

    # Save to artifact dir (for Hermes downstream use)
    artifact_dir = Path(args.output_dir) / args.report_date
    artifact_dir.mkdir(parents=True, exist_ok=True)
    out_path = artifact_dir / f"{args.slot_label}_split.json"
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Split data written to {out_path}")

    # Also save to data/ dir (for GitHub sync and historical comparison)
    data_dir = Path(args.output_dir) / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    data_out_path = data_dir / f"{args.report_date}_{args.slot_label}_split.json"
    data_out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Data copy written to {data_out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
