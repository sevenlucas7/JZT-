#!/usr/bin/env python3
"""
JZT Feishu Delivery Script (no_agent mode).

Reads computed artifacts, generates:
1. Formatted text report (new compact format + SEM split + suggestions)
2. Apple-inspired HTML dashboard → screenshot image
3. Outputs to stdout for no_agent cron delivery
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────
RUNTIME_DIR = Path("/Users/sevenyip/.openclaw/runtime/jzt_reports")
SCREENSHOT_DIR = Path("/tmp/jzt_dashboards")
TARGETS = {
    "GMEC-Tide": 1.5, "GMEC-Ariel": 1.5,
    "GMEC-Tide-L": 2.5, "GMEC-Ariel-L": 2.5, "GMEC-Downy": 3.0,
}
ACCOUNT_ORDER = ["GMEC-Tide-L", "GMEC-Ariel-L", "GMEC-Tide", "GMEC-Ariel", "GMEC-Downy"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--slot-label", required=True)
    p.add_argument("--report-date", default=datetime.now().strftime("%Y-%m-%d"))
    p.add_argument("--skip-dashboard", action="store_true", help="Skip HTML dashboard generation (testing)")
    return p.parse_args()


def read_artifact(artifact_dir: Path, slot: str, suffix: str) -> str:
    path = artifact_dir / f"{slot}{suffix}"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def read_split_data(artifact_dir: Path, slot: str) -> dict | None:
    path = artifact_dir / f"{slot}_split.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def fmt(v: float) -> str:
    return f"{v:,.0f}" if v >= 0 else "0"


# ── Suggestions Engine ────────────────────────────────────────────────────
def generate_suggestions(skus: list[dict]) -> list[str]:
    suggestions = []
    by_account: dict[str, list[dict]] = {}
    for s in skus:
        by_account.setdefault(s["账户"], []).append(s)

    for account in ACCOUNT_ORDER:
        if account not in by_account:
            continue
        sku_list = by_account[account]
        target = TARGETS.get(account, 2.5)

        # Worst performer in this account
        low_skus = [x for x in sku_list if x["综合ROI(含JST+SEM)"] < target * 0.9]
        if low_skus:
            worst = min(low_skus, key=lambda x: x["综合ROI(含JST+SEM)"])
            wsn = worst.get("SKU简称", worst["SKU名称"])
            suggestions.append(
                f"💡 **{account}** `{wsn}` ROI {worst['综合ROI(含JST+SEM)']:.1f} 未達標（目標 {target}）"
                f"，{'JST' if worst.get('JST花费(SPD)', 0) > worst.get('SEM花费(SPD)', 0) else 'SEM'} 花費佔比較高"
            )

        # SEM inefficiency
        for x in sku_list:
            xn = x.get("SKU简称", x["SKU名称"])
            sem_spend = x.get("SEM花费(SPD)", 0) or 0
            sem_roi = x.get("SEM ROI", 0) or 0
            jst_spend = x.get("JST花费(SPD)", 0) or 0
            jst_roi = x.get("JST ROI", 0) or 0
            if sem_spend > 300 and sem_roi < target * 0.7:
                suggestions.append(f"⚠️ {account}·{xn} SEM ROI {sem_roi:.1f} 偏低，花費 ¥{fmt(sem_spend)}，建議暫停無效詞")
            elif sem_spend > 200 and sem_roi < target * 0.8:
                suggestions.append(f"📉 {account}·{xn} SEM ROI {sem_roi:.1f}（花費 ¥{fmt(sem_spend)}），建議調整出價")
            if jst_spend > 300 and jst_roi < target * 0.7 and jst_spend >= sem_spend * 0.5:
                suggestions.append(f"🔍 {account}·{xn} JST ROI {jst_roi:.1f} 偏低（花費 ¥{fmt(jst_spend)}），建議檢查人群定向")

    # Keep only top 8 most impactful
    return suggestions[:8]


# ── Text Report Builder (NEW FORMAT) ──────────────────────────────────────
def build_text_report(
    discord_body: str,
    split_data: dict | None,
    meta: dict | None,
    slot: str,
    report_date: str,
    suggestions: list[str],
) -> str:
    lines = []

    # Header
    lines.append("📊 京准通数据监控")
    lines.append(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    if meta:
        lines.append(f"数据文件时间：{meta.get('source_file_modified_at', '—')}")
        lines.append(f"文件：{meta.get('source_file_name', '—')}")
    else:
        lines.append(f"文件：—")
    lines.append("口径：排除 Paid BI | 账户总览=JST+SEM+HT | SKU 明细=JST+SEM")
    lines.append("")

    if not split_data or not split_data.get("skus"):
        lines.append("（暫無數據）")
        return "\n".join(lines)

    skus = split_data["skus"]
    ht_data = {h["账户"]: h for h in split_data.get("ht", [])}
    by_account: dict[str, list[dict]] = {}
    for s in skus:
        by_account.setdefault(s["账户"], []).append(s)

    for account in ACCOUNT_ORDER:
        acc_skus = by_account.get(account, [])
        if not acc_skus:
            continue
        target = TARGETS.get(account, 2.5)

        # Account totals: JST+SEM (SKU) + HT
        ht = ht_data.get(account)
        ht_spend = ht["HT花费(SPD)"] if ht else 0
        ht_roi_val = ht["HT ROI"] if ht else 0
        ht_rev = ht_spend * ht_roi_val if ht_spend else 0

        total_spend = sum(s["综合花费(SPD)"] for s in acc_skus) + ht_spend
        total_rev = sum(s["综合花费(SPD)"] * s["综合ROI(含JST+SEM)"] for s in acc_skus) + ht_rev
        total_clicks = sum((s["综合花费(SPD)"] / s["综合CPC"]) if s.get("综合CPC", 0) > 0 else 0 for s in acc_skus)
        total_imps = sum((s["综合花费(SPD)"] / s["综合CPC"] / s["综合CTR"]) if s.get("综合CPC", 0) > 0 and s.get("综合CTR", 0) > 0 else 0 for s in acc_skus)
        total_orders = sum((s["综合花费(SPD)"] / s["综合CPC"] * s["综合CVR"]) if s.get("综合CPC", 0) > 0 else 0 for s in acc_skus)
        avg_roi = total_rev / total_spend if total_spend else 0
        avg_cpc = total_spend / total_clicks if total_clicks else 0
        avg_ctr = total_clicks / total_imps if total_imps else 0
        avg_cvr = total_orders / total_clicks if total_clicks else 0
        on_track = avg_roi >= target

        # Build per-account SKU lines
        sku_lines = []
        for s in sorted(acc_skus, key=lambda x: x["综合花费(SPD)"], reverse=True):
            sn = s.get("SKU简称", s["SKU名称"])
            jst_s = s.get("JST花费(SPD)", 0) or 0
            jst_r = s.get("JST ROI", 0) or 0
            sem_s = s.get("SEM花费(SPD)", 0) or 0
            sem_r = s.get("SEM ROI", 0) or 0
            comb_r = s["综合ROI(含JST+SEM)"]
            comb_s = s["综合花费(SPD)"]
            sn = s.get("SKU简称", s["SKU名称"])
            sid = s.get("SKU ID", "")
            sid_str = f"({sid})" if sid else ""

            sku_status = s["状态"]
            if s["状态"] == "正常":
                sku_status = "✅"

            sku_lines.append(f"🔹 {sn}{sid_str} {sku_status}")
            sku_lines.append(f"  JST+SEM：💰{fmt(comb_s)}  📈 ROI {comb_r:.1f}")
            sku_lines.append(f"  JST：     💰{fmt(jst_s)}  📈 ROI {'—' if jst_s == 0 else f'{jst_r:.1f}'}")
            sku_lines.append(f"  SEM：     💰{fmt(sem_s)}  📈 ROI {'—' if sem_s == 0 else f'{sem_r:.1f}'}")

        status_emoji = "✅" if on_track else "⚠️"
        lines.append(f"{status_emoji} **{account}**")
        lines.append(f"  💰总花费 ¥{fmt(total_spend)}  |  总ROI {avg_roi:.1f}  |  目标ROI {target}")
        lines.append(f"  总CPC ¥{avg_cpc:.2f}  |  总CTR {avg_ctr*100:.1f}%  |  总CVR {avg_cvr*100:.1f}%")
        lines.append("")
        lines.extend(sku_lines)
        lines.append("")

        # HT from split data
        ht = ht_data.get(account)
        if ht:
            lines.append(f"  HT：💰{fmt(ht['HT花费(SPD)'])}  ROI {ht['HT ROI']:.1f}")
        else:
            lines.append(f"  HT：—")
        lines.append("")
        lines.append("—" * 20)
        lines.append("")

    if suggestions:
        lines.append("💡 **建議**")
        for sug in suggestions:
            lines.append(f"· {sug}")
        lines.append("")

    lines.append("—" * 20)
    lines.append("**團隊分工**")
    lines.append("- Hermes：數據读取、筛选、指标计算、报告工件生成、HTML 看板制作、結果校驗、結構整理、最终 Feishu 交付")

    return "\n".join(lines)


# ── HTML Dashboard Builder (Painter Redesign wrapper) ──────────────────────
def build_html_dashboard(skus: list[dict], report_date: str, slot: str, split_data: dict | None = None, meta: dict | None = None) -> str:
    # Keep data computation in this delivery script; delegate only HTML rendering to the
    # Painter redesign renderer so the cron pipeline/data contract stays unchanged.
    from jzt_dashboard_renderer import build_html_dashboard as render_painter_dashboard

    suggestions = generate_suggestions(skus)
    return render_painter_dashboard(skus, report_date, slot, split_data, meta, suggestions)


def screenshot_html(html: str, output_path: Path) -> Path:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1120, "height": 800})
        page.set_content(html, wait_until="networkidle")
        page.wait_for_timeout(1000)
        height = page.evaluate("document.body.scrollHeight")
        page.set_viewport_size({"width": 1120, "height": height})
        page.wait_for_timeout(500)
        page.screenshot(path=str(output_path), full_page=True)
        browser.close()
    return output_path


# ── Main ───────────────────────────────────────────────────────────────────
def main() -> int:
    args = parse_args()
    artifact_dir = RUNTIME_DIR / args.report_date

    required = [
        artifact_dir / f"{args.slot_label}_discord.md",
        artifact_dir / f"{args.slot_label}_meta.json",
        artifact_dir / f"{args.slot_label}_split.json",
    ]
    missing = [str(p) for p in required if not p.exists() or p.stat().st_size == 0]
    if missing:
        print("ERROR: JZT delivery artifacts missing; refusing to send empty report.", file=sys.stderr)
        for p in missing:
            print(f"MISSING: {p}", file=sys.stderr)
        return 1

    discord_body = read_artifact(artifact_dir, args.slot_label, "_discord.md")
    split_data = read_split_data(artifact_dir, args.slot_label)
    meta_raw = read_artifact(artifact_dir, args.slot_label, "_meta.json")
    meta = json.loads(meta_raw) if meta_raw else None

    skus = split_data.get("skus", []) if split_data else []
    if not skus:
        print("ERROR: JZT split artifact has no SKU rows; refusing to send empty report.", file=sys.stderr)
        return 1
    suggestions = generate_suggestions(skus)

    # 1. Text report
    text = build_text_report(discord_body, split_data, meta, args.slot_label, args.report_date, suggestions)
    print(text)

    # 2. HTML dashboard → HTML file + screenshot
    if not args.skip_dashboard and skus:
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        img_path = SCREENSHOT_DIR / f"jzt_dashboard_{args.report_date}_{args.slot_label}.png"
        html_path = SCREENSHOT_DIR / f"jzt_dashboard_{args.report_date}_{args.slot_label}.html"
        html = build_html_dashboard(skus, args.report_date, args.slot_label, split_data, meta)
        html_path.write_text(html, encoding="utf-8")
        screenshot_html(html, img_path)
        print(f"\nMEDIA:{img_path}")
        print(f"MEDIA:{html_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
