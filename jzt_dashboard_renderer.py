#!/usr/bin/env python3
"""Painter redesign HTML renderer for JZT Feishu dashboard.

Keeps the existing JZT delivery data contract:
- account totals = JST + SEM + HT
- SKU detail = JST + SEM only
- HT shown as one account-level row
- SKU ID is rendered under SKU name
"""
from __future__ import annotations

import html as html_lib
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

TARGETS = {
    "GMEC-Tide": 1.5,
    "GMEC-Ariel": 1.5,
    "GMEC-Tide-L": 2.5,
    "GMEC-Ariel-L": 2.5,
    "GMEC-Downy": 3.0,
}
# Legacy = L 系列（旧包装，洗衣液）: GMEC-Tide-L + GMEC-Ariel-L
# PWD = PWD 粉洗（洗衣粉）: GMEC-Tide + GMEC-Ariel
LEGACY_ACCOUNTS = {"GMEC-Tide-L", "GMEC-Ariel-L"}
PWD_ACCOUNTS = {"GMEC-Tide", "GMEC-Ariel"}
ACCOUNT_ORDER = ["GMEC-Tide-L", "GMEC-Ariel-L", "GMEC-Tide", "GMEC-Ariel", "GMEC-Downy"]
TEMPLATE_PATH = Path(__file__).with_name("jzt_dashboard_redesign_template.html")


def esc(v: Any) -> str:
    return html_lib.escape(str(v if v is not None else ""), quote=True)


def safe_float(v: Any) -> float:
    try:
        x = float(v or 0)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if math.isnan(x) else x


def fmt_num(v: float, decimals: int = 0) -> str:
    v = safe_float(v)
    return f"{v:,.{decimals}f}" if decimals else f"{v:,.0f}"


def money(v: float) -> str:
    return f"¥{fmt_num(v)}"


def short_money(v: float) -> str:
    v = safe_float(v)
    if abs(v) >= 1_000_000:
        return f"¥{v / 1_000_000:.1f}M"
    if abs(v) >= 1_000:
        return f"¥{v / 1_000:.1f}K"
    return money(v)


def roi_txt(v: float) -> str:
    return f"{safe_float(v):.2f}"


def status_class(value: float, target: float) -> str:
    value = safe_float(value)
    target = safe_float(target)
    if target <= 0:
        return "neutral"
    if value < target * 0.9:
        return "bad"
    if value < target:
        return "warn"
    if value >= target * 1.1:
        return "ok"
    return "neutral"


def roi_chip(value: float, target: float, spend: float | None = None) -> str:
    if spend is not None and safe_float(spend) <= 0:
        return '<span class="roi-chip neutral">—</span>'
    cls = status_class(value, target)
    return f'<span class="roi-chip {cls}">{roi_txt(value)}</span>'


def delta_badge(diff: float, pct: float, direction: str) -> str:
    """Build an index badge: current / previous * 100."""
    if pct == 0:
        return '<span class="delta-badge neutral">—</span>'
    cls = "up" if direction == "up" else "down" if direction == "down" else "neutral"
    return f'<span class="delta-badge {cls}" title="新数据 / 旧数据 × 100">{pct:.0f}%</span>'


def delta_badge_small(diff: float, pct: float, direction: str) -> str:
    """Build a small inline index badge: current / previous * 100."""
    if pct == 0:
        return ""
    cls = "up" if direction == "up" else "down" if direction == "down" else "neutral"
    return f'<span class="delta-inline {cls}" title="新数据 / 旧数据 × 100">{pct:.0f}%</span>'


def sku_delta_chip(diff: float, pct: float, direction: str) -> str:
    """SKU-level latest-vs-previous index chip.

    Shows Boss' requested formula: current / previous * 100.
    """
    if pct == 0:
        return '<span class="sku-delta-slot" title="新数据 / 旧数据 × 100">—</span>'
    cls = "up" if direction == "up" else "down" if direction == "down" else "neutral"
    return f'<span class="delta-inline {cls} sku-delta-slot" title="新数据 / 旧数据 × 100">{pct:.0f}%</span>'


def get_account_deltas(split_data: dict | None, account: str) -> tuple[dict, dict]:
    """Get spend and ROI deltas for an account from split_data."""
    if not split_data or "deltas" not in split_data:
        return {}, {}
    acc_deltas = split_data.get("deltas", {}).get("accounts", {}).get(account, {})
    spend_d = acc_deltas.get("综合花费", {})
    roi_d = acc_deltas.get("综合ROI", {})
    return spend_d, roi_d


def get_sku_deltas(split_data: dict | None, account: str, sku_id: str) -> tuple[dict, dict]:
    """Get spend and ROI deltas for a specific SKU from split_data."""
    if not split_data or "deltas" not in split_data:
        return {}, {}
    for sd in split_data.get("deltas", {}).get("skus", []):
        if sd.get("账户") == account and sd.get("SKU ID") == sku_id:
            return sd.get("综合花费", {}), sd.get("综合ROI", {})
    return {}, {}


def get_sku_metric_delta(split_data: dict | None, account: str, sku_id: str, metric: str) -> dict:
    """Get a named SKU metric delta dict, e.g. JST花费 / JST ROI / SEM花费 / SEM ROI."""
    if not split_data or "deltas" not in split_data:
        return {}
    for sd in split_data.get("deltas", {}).get("skus", []):
        if sd.get("账户") == account and sd.get("SKU ID") == sku_id:
            return sd.get(metric, {})
    return {}


def get_overall_deltas(split_data: dict | None) -> tuple[dict, dict]:
    """Get overall total_spend and total_roi deltas."""
    if not split_data or "deltas" not in split_data:
        return {}, {}
    deltas = split_data.get("deltas", {})
    return deltas.get("total_spend", {}), deltas.get("total_roi", {})


def get_format_deltas(split_data: dict | None, format_name: str) -> tuple[dict, dict]:
    """Get spend and ROI index deltas for JST / SEM / HT."""
    if not split_data or "deltas" not in split_data:
        return {}, {}
    fd = split_data.get("deltas", {}).get("formats", {}).get(format_name, {})
    return fd.get("花费", {}), fd.get("ROI", {})


def get_ht_deltas(split_data: dict | None, account: str) -> tuple[dict, dict]:
    """Get account-level HT spend and ROI deltas."""
    if not split_data or "deltas" not in split_data:
        return {}, {}
    hd = split_data.get("deltas", {}).get("ht", {}).get(account, {})
    return hd.get("HT花费", {}), hd.get("HT ROI", {})


def pct_value(part: float, total: float) -> float:
    total = safe_float(total)
    return safe_float(part) / total * 100 if total > 0 else 0.0


def markdown_to_plain(s: str) -> str:
    return re.sub(r"(\*\*|`)", "", str(s or ""))


def default_head() -> str:
    return """<head><meta charset=\"UTF-8\"><meta name=\"viewport\" content=\"width=1280\"><title>京准通数据看板 · JZT Dashboard</title><style>
body{font-family:-apple-system,BlinkMacSystemFont,'SF Pro Display','Noto Sans SC',sans-serif;background:#fafaf8;color:#1f1f1e;padding:32px;min-width:1280px}.account-detail-card,.acct-card,.kpi-card,.side-panel,.insights-section{background:white;border:1px solid rgba(0,0,0,.08);border-radius:12px;padding:16px;margin:12px 0}.num{font-family:monospace}.roi-chip{padding:2px 7px;border-radius:4px}.ok{color:#1aae39}.warn{color:#dd5b00}.bad{color:#c13515}.neutral{color:#5a5a58}
</style></head>"""


def load_painter_head() -> str:
    extra_css = """
  /* —— DELTA BADGES —— */
  .delta-badge {
    display: inline-flex; align-items: center; gap: 3px;
    padding: 2px 8px; border-radius: 9999px;
    font-size: 10.5px; font-weight: 600;
    font-family: 'JetBrains Mono', monospace;
    margin-left: 6px;
  }
  .delta-badge.up { background: rgba(26,174,57,0.12); color: var(--ok); }
  .delta-badge.down { background: rgba(193,53,21,0.12); color: var(--bad); }
  .delta-badge.neutral { background: rgba(0,0,0,0.06); color: var(--ink-2); }
  .delta-inline {
    display: inline-block; margin-left: 4px;
    font-size: 10px; font-weight: 600;
    font-family: 'JetBrains Mono', monospace;
  }
  .delta-inline.up { color: var(--ok); }
  .delta-inline.down { color: var(--bad); }
  .kpi-deltas { margin-top: 6px; display: flex; gap: 6px; flex-wrap: wrap; }
  .delta-row { display: flex; gap: 4px; margin-top: 2px; }
  .delta-label { font-size: 9.5px; color: var(--ink-3); font-weight: 500; }

  /* —— SERIES CARDS (Legacy / PWD summary) —— */
  .series-grid {
    display: grid; grid-template-columns: 1fr 1fr; gap: 14px;
    margin-bottom: 28px;
  }
  .series-card {
    background: var(--bg-card);
    border: 1px solid var(--rule);
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 1px 2px var(--shadow-blue-2);
    display: flex; flex-direction: column;
  }
  .series-card .series-bar {
    height: 3px; background: var(--series-color, var(--brand)); width: 100%;
  }
  .series-card .series-body { padding: 14px 18px 16px; }
  .series-card .series-name {
    font-size: 14px; font-weight: 600; color: var(--ink-1);
    margin-bottom: 10px; display: flex; align-items: center; gap: 8px;
  }
  .series-card .series-count {
    font-size: 10.5px; color: var(--ink-3); font-weight: 500;
    font-family: 'JetBrains Mono', monospace;
  }
  .series-card .kpi-row {
    display: grid; grid-template-columns: 1fr 1fr; gap: 10px;
    margin-bottom: 10px;
  }
  .series-card .kpi-cell {
    background: var(--bg-soft); border-radius: 8px; padding: 10px 12px;
  }
  .series-card .kpi-cell .v {
    font-size: 20px; font-weight: 600; letter-spacing: -0.025em;
    color: var(--ink-1); line-height: 1.1;
  }
  .series-card .kpi-cell .l {
    font-size: 10.5px; color: var(--ink-2); font-weight: 500; margin-top: 3px;
  }
  .series-deltas {
    display: flex; flex-wrap: wrap; gap: 6px; align-items: center;
    font-size: 10.5px; color: var(--ink-2);
  }
  .series-deltas .delta-badge { margin-left: 0; }

  /* —— FORMAT CARDS (JST / SEM / HT latest-vs-previous index) —— */
  .format-grid {
    display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px;
    margin: -12px 0 24px;
  }
  .format-card {
    background: var(--bg-card); border: 1px solid var(--rule);
    border-radius: 12px; padding: 14px 16px;
    box-shadow: 0 1px 2px var(--shadow-blue-2);
    border-top: 3px solid var(--fmt-color);
  }
  .fmt-top { display:flex; align-items:center; gap:8px; margin-bottom:10px; }
  .fmt-dot { width:8px; height:8px; border-radius:99px; background:var(--fmt-color); }
  .fmt-name { font-size:14px; font-weight:700; color:var(--ink-1); }
  .fmt-tag { margin-left:auto; font-size:10px; color:var(--ink-3); font-family:'JetBrains Mono', monospace; }
  .fmt-grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
  .fmt-value { font-size:18px; font-weight:650; color:var(--ink-1); font-family:'JetBrains Mono', monospace; }
  .fmt-label { margin-top:3px; font-size:10.5px; color:var(--ink-2); }

  /* —— ACCOUNT CARD DELTA ADJUSTMENTS —— */
  .acct-card .kpi-cell .delta-row { font-size: 9.5px; }
  .acct-card .kpi-cell .delta-inline { margin-left: 2px; }

  /* —— HOVER ANIMATION —— */
  .kpi-card, .acct-card, .series-card, .account-detail-card {
    transition: transform 0.2s ease, box-shadow 0.2s ease;
  }
  .kpi-card:hover, .acct-card:hover, .series-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 16px -4px var(--shadow-blue);
  }
  .account-detail-card:hover {
    box-shadow: 0 2px 8px -2px var(--shadow-blue);
  }

  /* —— ENTRANCE ANIMATION —— */
  @keyframes fadeInUp {
    from { opacity: 0; transform: translateY(12px); }
    to { opacity: 1; transform: translateY(0); }
  }

  /* —— SKU-LEVEL vs 2H DELTA SLOT —— */
  .sku-delta-slot {
    display: inline-block;
    margin-left: 4px;
    font-size: 9.5px;
    font-weight: 600;
    font-family: 'JetBrains Mono', monospace;
    color: var(--ink-4);
    vertical-align: 1px;
  }
  .sku-delta-slot.delta-inline.up   { color: var(--ok); }
  .sku-delta-slot.delta-inline.down { color: var(--bad); }
  .sku-table thead th .th-suffix {
    display: inline-block;
    margin-left: 4px;
    padding: 1px 5px;
    border-radius: 9999px;
    background: rgba(0,117,222,0.10);
    color: #0075de;
    font-size: 8.5px;
    font-weight: 600;
    font-family: 'JetBrains Mono', monospace;
    letter-spacing: 0.02em;
    vertical-align: 1px;
  }
  .kpi-strip .kpi-card { animation: fadeInUp 0.4s ease both; }
  .kpi-strip .kpi-card:nth-child(1) { animation-delay: 0.05s; }
  .kpi-strip .kpi-card:nth-child(2) { animation-delay: 0.10s; }
  .kpi-strip .kpi-card:nth-child(3) { animation-delay: 0.15s; }
  .kpi-strip .kpi-card:nth-child(4) { animation-delay: 0.20s; }
  .series-grid .series-card { animation: fadeInUp 0.4s ease both; }
  .series-grid .series-card:nth-child(1) { animation-delay: 0.15s; }
  .series-grid .series-card:nth-child(2) { animation-delay: 0.20s; }
  .accounts-grid .acct-card { animation: fadeInUp 0.4s ease both; }
  .accounts-grid .acct-card:nth-child(1) { animation-delay: 0.20s; }
  .accounts-grid .acct-card:nth-child(2) { animation-delay: 0.25s; }
  .accounts-grid .acct-card:nth-child(3) { animation-delay: 0.30s; }
  .accounts-grid .acct-card:nth-child(4) { animation-delay: 0.35s; }
  .accounts-grid .acct-card:nth-child(5) { animation-delay: 0.40s; }
"""
    if TEMPLATE_PATH.exists():
        template = TEMPLATE_PATH.read_text(encoding="utf-8")
        if "</head>" in template:
            head = template.split("</head>", 1)[0]
            # Insert extra CSS before </style> in the head
            if "</style>" in head:
                head = head.replace("</style>", extra_css + "\n  </style>", 1)
            return head + "</head>"
    return default_head() + f"<style>{extra_css}</style>"


def build_account_stats(skus: list[dict], split_data: dict | None) -> list[dict]:
    by_account: dict[str, list[dict]] = {}
    for s in skus:
        by_account.setdefault(s.get("账户", ""), []).append(s)
    ht_map = {h.get("账户"): h for h in (split_data or {}).get("ht", [])}

    stats = []
    for account in ACCOUNT_ORDER:
        acc_skus = by_account.get(account, [])
        if not acc_skus:
            continue
        target = TARGETS.get(account, 2.5)
        ht_row = ht_map.get(account) or {}
        ht_spend = safe_float(ht_row.get("HT花费(SPD)", 0))
        ht_roi_val = safe_float(ht_row.get("HT ROI", 0))
        sku_spend = sum(safe_float(s.get("综合花费(SPD)", 0)) for s in acc_skus)
        sku_rev = sum(safe_float(s.get("综合花费(SPD)", 0)) * safe_float(s.get("综合ROI(含JST+SEM)", 0)) for s in acc_skus)
        ht_rev = ht_spend * ht_roi_val
        total_spend = sku_spend + ht_spend
        total_rev = sku_rev + ht_rev
        jst_spend = sum(safe_float(s.get("JST花费(SPD)", 0)) for s in acc_skus)
        sem_spend = sum(safe_float(s.get("SEM花费(SPD)", 0)) for s in acc_skus)
        stats.append({
            "account": account,
            "skus": acc_skus,
            "target": target,
            "total_spend": total_spend,
            "total_rev": total_rev,
            "avg_roi": total_rev / total_spend if total_spend else 0.0,
            "ht_spend": ht_spend,
            "ht_roi": ht_roi_val,
            "jst_spend": jst_spend,
            "sem_spend": sem_spend,
        })
    return stats


def build_html_dashboard(
    skus: list[dict],
    split_data: dict | None = None,
    meta: dict | None = None,
    suggestions: list[str] | None = None,
) -> str:
    """Build the painter redesign HTML dashboard.

    Args:
        skus: List of SKU dicts (the ``skus`` array of split.json).
        split_data: Full split.json dict (must contain ``ht``, ``deltas``, etc.).
        meta: Report meta info (source file name, modified time, etc.).
        suggestions: Optional list of insight strings.
    """
    account_visuals = {
        "GMEC-Tide-L": {"class": "tidel", "badge": "tidel", "brand": "Tide", "color": "var(--c-tidel)", "id": "#01"},
        "GMEC-Ariel-L": {"class": "ariell", "badge": "ariell", "brand": "Ariel", "color": "var(--c-ariell)", "id": "#02"},
        "GMEC-Tide": {"class": "tide", "badge": "tide", "brand": "Tide", "color": "var(--c-tide)", "id": "#03"},
        "GMEC-Ariel": {"class": "ariel", "badge": "ariel", "brand": "Ariel", "color": "var(--c-ariel)", "id": "#04"},
        "GMEC-Downy": {"class": "downy", "badge": "downy", "brand": "Downy", "color": "var(--c-downy)", "id": "#05"},
    }

    account_stats = build_account_stats(skus, split_data)
    total_all_spend = sum(a["total_spend"] for a in account_stats)
    total_all_rev = sum(a["total_rev"] for a in account_stats)
    total_jst = sum(a["jst_spend"] for a in account_stats)
    total_sem = sum(a["sem_spend"] for a in account_stats)
    total_ht = sum(a["ht_spend"] for a in account_stats)
    max_spend = max((a["total_spend"] for a in account_stats), default=1)
    weighted_roi = total_all_rev / total_all_spend if total_all_spend else 0
    low_accounts = sum(1 for a in account_stats if a["avg_roi"] < a["target"])
    sku_count = sum(len(a["skus"]) for a in account_stats)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    source_name = (meta or {}).get("source_file_name", "—")
    source_time = (meta or {}).get("source_file_modified_at", "—")
    suggestions = suggestions or []

    # Get overall deltas from split_data
    overall_spend_delta, overall_roi_delta = get_overall_deltas(split_data)
    spend_2h = overall_spend_delta.get("vs_2h", {})
    spend_yd = overall_spend_delta.get("vs_yesterday", {})
    roi_2h = overall_roi_delta.get("vs_2h", {})
    roi_yd = overall_roi_delta.get("vs_yesterday", {})

    # Build Legacy / PWD series summaries
    legacy_stats = [a for a in account_stats if a["account"] in LEGACY_ACCOUNTS]
    pwd_stats = [a for a in account_stats if a["account"] in PWD_ACCOUNTS]
    downy_stats = [a for a in account_stats if a["account"] == "GMEC-Downy"]

    def series_card(series_name: str, stats: list[dict], color: str) -> str:
        if not stats:
            return ""
        total_spend = sum(a["total_spend"] for a in stats)
        total_rev = sum(a["total_rev"] for a in stats)
        roi = total_rev / total_spend if total_spend else 0
        # Get combined deltas for this series
        series_deltas_spend_2h, series_deltas_spend_yd = [], []
        series_deltas_roi_2h, series_deltas_roi_yd = [], []
        for a in stats:
            sd, rd = get_account_deltas(split_data, a["account"])
            series_deltas_spend_2h.append(sd.get("vs_2h", {}))
            series_deltas_spend_yd.append(sd.get("vs_yesterday", {}))
            series_deltas_roi_2h.append(rd.get("vs_2h", {}))
            series_deltas_roi_yd.append(rd.get("vs_yesterday", {}))
        # Aggregate account-level deltas using the same JST+SEM+HT account total
        #口径 as the visible series total. Each account delta is current - previous,
        # so previous = current_account_total - diff.
        total_prev_spend_2h = sum(
            a["total_spend"] - safe_float(d.get("diff", 0))
            for a, d in zip(stats, series_deltas_spend_2h)
            if d
        )
        total_prev_spend_yd = sum(
            a["total_spend"] - safe_float(d.get("diff", 0))
            for a, d in zip(stats, series_deltas_spend_yd)
            if d
        )
        agg_spend_2h = compute_series_delta(total_spend, total_prev_spend_2h)
        agg_spend_yd = compute_series_delta(total_spend, total_prev_spend_yd)
        badge_2h = delta_badge(agg_spend_2h["diff"], agg_spend_2h["index_pct"], agg_spend_2h["direction"])
        badge_yd = delta_badge(agg_spend_yd["diff"], agg_spend_yd["index_pct"], agg_spend_yd["direction"])
        badge_2h_roi = delta_badge_small(roi_2h.get("diff", 0), roi_2h.get("index_pct", 0), roi_2h.get("direction", "neutral"))
        badge_yd_roi = delta_badge_small(roi_yd.get("diff", 0), roi_yd.get("index_pct", 0), roi_yd.get("direction", "neutral"))
        return f'''
  <div class="series-card" style="--series-color:{color}">
    <div class="series-bar"></div>
    <div class="series-body">
      <div class="series-name">{series_name} <span class="series-count">{len(stats)}账户</span></div>
      <div class="kpi-row">
        <div class="kpi-cell"><div class="v">{money(total_spend)}</div><div class="l">总花费</div></div>
        <div class="kpi-cell"><div class="v">{roi_txt(roi)}</div><div class="l">综合 ROI</div></div>
      </div>
      <div class="series-deltas">
        <span class="delta-label">vs 2h ago</span> {badge_2h}
        <span class="delta-label">vs yesterday</span> {badge_yd}
      </div>
    </div>
  </div>'''

    def compute_series_delta(current: float, previous: float) -> dict:
        if not previous or previous == 0:
            return {"diff": 0, "pct": 0, "index_pct": 0, "direction": "neutral"}
        diff = current - previous
        pct = (diff / abs(previous)) * 100 if previous != 0 else 0
        index_pct = (current / previous) * 100 if previous != 0 else 0
        direction = "up" if diff > 0 else "down" if diff < 0 else "neutral"
        return {"diff": round(diff, 2), "pct": round(pct, 2), "index_pct": round(index_pct, 2), "direction": direction}

    account_cards: list[str] = []
    detail_cards: list[str] = []
    heat_rows: list[str] = []

    for idx, a in enumerate(account_stats, start=1):
        account = a["account"]
        v = account_visuals.get(account, {"class": "", "badge": "", "brand": account, "color": "var(--brand)", "id": f"#{idx:02d}"})
        st = status_class(a["avg_roi"], a["target"])
        ok_text = "OK" if a["avg_roi"] >= a["target"] else "LOW"
        spend_pct = min(100, round(a["total_spend"] / max_spend * 100)) if max_spend else 0
        jst_sem_total_acc = a["jst_spend"] + a["sem_spend"]
        jst_pct = pct_value(a["jst_spend"], jst_sem_total_acc)
        sem_pct = pct_value(a["sem_spend"], jst_sem_total_acc)
        jst_label = f"{jst_pct:.0f}%" if jst_pct >= 8 else ""
        sem_label = f"{sem_pct:.0f}%" if sem_pct >= 8 else ""
        cmp = "≥" if a["avg_roi"] >= a["target"] else "<"

        # Get per-account deltas
        spend_d, roi_d = get_account_deltas(split_data, account)
        spend_2h = spend_d.get("vs_2h", {})
        spend_yd = spend_d.get("vs_yesterday", {})
        roi_2h = roi_d.get("vs_2h", {})
        roi_yd = roi_d.get("vs_yesterday", {})
        spend_badge_2h = delta_badge_small(spend_2h.get("diff", 0), spend_2h.get("index_pct", 0), spend_2h.get("direction", "neutral"))
        spend_badge_yd = delta_badge_small(spend_yd.get("diff", 0), spend_yd.get("index_pct", 0), spend_yd.get("direction", "neutral"))
        roi_badge_2h = delta_badge_small(roi_2h.get("diff", 0), roi_2h.get("index_pct", 0), roi_2h.get("direction", "neutral"))
        roi_badge_yd = delta_badge_small(roi_yd.get("diff", 0), roi_yd.get("index_pct", 0), roi_yd.get("direction", "neutral"))

        account_cards.append(f'''
  <div class="acct-card {v['class']}">
    <div class="bar"></div>
    <div class="body">
      <div class="name"><span class="dot"></span>{esc(account)} <span class="id">{esc(v['id'])}</span></div>
      <div class="kpi-row">
        <div class="kpi-cell"><div class="v">{money(a['total_spend'])}</div><div class="l">综合花费</div><div class="delta-row">{spend_badge_2h} {spend_badge_yd}</div></div>
        <div class="kpi-cell"><div class="v">{roi_txt(a['avg_roi'])}</div><div class="l">综合 ROI</div><div class="delta-row">{roi_badge_2h} {roi_badge_yd}</div></div>
      </div>
      <div class="spend-bar"><span style="width:{spend_pct}%"></span></div>
      <div><span class="roas-chip {st}"><span class="dot"></span>ROI {roi_txt(a['avg_roi'])} {cmp} {a['target']:.1f} {ok_text}</span></div>
      <div class="stack-bar" title="JST {money(a['jst_spend'])} ({jst_pct:.1f}%) · SEM {money(a['sem_spend'])} ({sem_pct:.1f}%)">
        <div class="seg jst" style="width:{jst_pct:.1f}%">{jst_label}</div>
        <div class="seg sem" style="width:{sem_pct:.1f}%">{sem_label}</div>
      </div>
      <div class="stack-legend"><span class="l"><span class="sq jst"></span>JST <span style="color:var(--ink-1);font-weight:600;font-family:'JetBrains Mono',monospace;">{money(a['jst_spend'])}</span> <span style="color:var(--ink-3);">· {jst_pct:.0f}%</span></span><span class="l"><span class="sq sem"></span>SEM <span style="color:var(--ink-1);font-weight:600;font-family:'JetBrains Mono',monospace;">{money(a['sem_spend'])}</span></span></div>
      <div class="divider"></div><div class="ht-row"><span class="badge">HT</span><span class="v">{money(a['ht_spend'])}</span><span class="sep">·</span><span class="v">ROI {roi_txt(a['ht_roi'])}</span></div>
    </div>
  </div>''')

        rows = []
        for s in sorted(a["skus"], key=lambda x: safe_float(x.get("综合花费(SPD)", 0)), reverse=True):
            sn = esc(s.get("SKU简称", s.get("SKU名称", "—")))
            sid = esc(s.get("SKU ID", "") or "—")
            comb_s = safe_float(s.get("综合花费(SPD)", 0)); comb_r = safe_float(s.get("综合ROI(含JST+SEM)", 0))
            jst_s = safe_float(s.get("JST花费(SPD)", 0)); jst_r = safe_float(s.get("JST ROI", 0))
            sem_s = safe_float(s.get("SEM花费(SPD)", 0)); sem_r = safe_float(s.get("SEM ROI", 0))
            # SKU deltas
            sku_spend_d, sku_roi_d = get_sku_deltas(split_data, account, s.get("SKU ID", ""))
            sku_spend_2h = sku_spend_d.get("vs_2h", {})
            sku_spend_yd = sku_spend_d.get("vs_yesterday", {})
            sku_roi_2h = sku_roi_d.get("vs_2h", {})
            sku_roi_yd = sku_roi_d.get("vs_yesterday", {})
            sku_spend_badge = sku_delta_chip(sku_spend_2h.get("diff", 0), sku_spend_2h.get("index_pct", 0), sku_spend_2h.get("direction", "neutral"))
            sku_roi_badge = sku_delta_chip(sku_roi_2h.get("diff", 0), sku_roi_2h.get("index_pct", 0), sku_roi_2h.get("direction", "neutral"))
            jst_spend_2h = get_sku_metric_delta(split_data, account, s.get("SKU ID", ""), "JST花费").get("vs_2h", {})
            jst_roi_2h = get_sku_metric_delta(split_data, account, s.get("SKU ID", ""), "JST ROI").get("vs_2h", {})
            sem_spend_2h = get_sku_metric_delta(split_data, account, s.get("SKU ID", ""), "SEM花费").get("vs_2h", {})
            sem_roi_2h = get_sku_metric_delta(split_data, account, s.get("SKU ID", ""), "SEM ROI").get("vs_2h", {})
            jst_spend_badge = sku_delta_chip(jst_spend_2h.get("diff", 0), jst_spend_2h.get("index_pct", 0), jst_spend_2h.get("direction", "neutral"))
            jst_roi_badge = sku_delta_chip(jst_roi_2h.get("diff", 0), jst_roi_2h.get("index_pct", 0), jst_roi_2h.get("direction", "neutral"))
            sem_spend_badge = sku_delta_chip(sem_spend_2h.get("diff", 0), sem_spend_2h.get("index_pct", 0), sem_spend_2h.get("direction", "neutral"))
            sem_roi_badge = sku_delta_chip(sem_roi_2h.get("diff", 0), sem_roi_2h.get("index_pct", 0), sem_roi_2h.get("direction", "neutral"))
            rows.append(f'''<tr><td><div class="sku-name">{sn}</div><div class="sku-id">{sid}</div></td><td class="num">{money(comb_s)} {sku_spend_badge}</td><td class="num">{roi_chip(comb_r, a['target'])} {sku_roi_badge}</td><td class="num">{money(jst_s)} {jst_spend_badge}</td><td class="num">{roi_chip(jst_r, a['target'], jst_s)} {jst_roi_badge}</td><td class="num">{money(sem_s)} {sem_spend_badge}</td><td class="num">{roi_chip(sem_r, a['target'], sem_s)} {sem_roi_badge}</td></tr>''')
        ht_spend_d, ht_roi_d = get_ht_deltas(split_data, account)
        ht_spend_2h = ht_spend_d.get("vs_2h", {})
        ht_roi_2h = ht_roi_d.get("vs_2h", {})
        ht_spend_badge = sku_delta_chip(ht_spend_2h.get("diff", 0), ht_spend_2h.get("index_pct", 0), ht_spend_2h.get("direction", "neutral"))
        ht_roi_badge = sku_delta_chip(ht_roi_2h.get("diff", 0), ht_roi_2h.get("index_pct", 0), ht_roi_2h.get("direction", "neutral"))
        rows.append(f'''<tr class="ht-row"><td><span class="ht-label">HT</span>黑盒整体</td><td class="num">{money(a['ht_spend'])} {ht_spend_badge}</td><td class="num">{roi_chip(a['ht_roi'], a['target'], a['ht_spend'])} {ht_roi_badge}</td><td class="num em-dash">—</td><td class="num em-dash">—</td><td class="num em-dash">—</td><td class="num em-dash">—</td></tr>''')
        detail_cards.append(f'''
    <div class="account-detail-card"><div class="account-detail-header"><h3><span class="dot" style="background:{v['color']}"></span>{esc(account)}</h3><span class="account-badge {v['badge']}">{esc(v['brand'])} · {len(a['skus'])} SKUs</span></div><div class="sku-table-wrap"><table class="sku-table"><thead><tr><th>SKU 名称 (跟单SKU ID)</th><th>综合花费<span class="th-suffix">新/旧</span></th><th>综合 ROI<span class="th-suffix">新/旧</span></th><th>JST 花费<span class="th-suffix">新/旧</span></th><th>JST ROI<span class="th-suffix">新/旧</span></th><th>SEM 花费<span class="th-suffix">新/旧</span></th><th>SEM ROI<span class="th-suffix">新/旧</span></th></tr></thead><tbody>{''.join(rows)}</tbody></table></div></div>''')
        heat_rows.append(f'<div class="heat-row"><div class="l"><span class="dot {st}"></span><span class="name">{esc(account)}</span></div><span class="badge {st}">{roi_txt(a["avg_roi"])} {ok_text}</span></div>')

    ht_rank_rows = []
    ranked = sorted(account_stats, key=lambda x: x["ht_roi"], reverse=True)
    for i, a in enumerate(ranked, start=1):
        cls = "ok" if i <= 2 else ("warn" if i == len(ranked) else "neutral")
        bg = "rgba(26,174,57,0.10)" if cls == "ok" else "rgba(221,91,0,0.10)" if cls == "warn" else "rgba(0,0,0,0.06)"
        color = "var(--ok)" if cls == "ok" else "var(--warn)" if cls == "warn" else "var(--ink-2)"
        ht_rank_rows.append(f'<div class="kpi-mini" style="padding:7px 0;{ "border-bottom:none;" if i == len(ranked) else "" }"><div class="ic" style="background:{bg};color:{color};font-family:\'JetBrains Mono\',monospace;font-size:11px;">{i}</div><div class="body"><div class="v" style="font-size:13px;letter-spacing:-0.01em;">{esc(a["account"])}</div><div class="l" style="font-family:\'JetBrains Mono\',monospace;font-size:10.5px;">HT {money(a["ht_spend"])} <span style="color:{color};font-weight:600;">HT·{roi_txt(a["ht_roi"])}</span></div></div></div>')

    jst_sem_total = total_jst + total_sem
    jst_pct_i = round(pct_value(total_jst, jst_sem_total))
    sem_pct_i = 100 - jst_pct_i if jst_sem_total else 0
    circ = 276.46
    jst_dash = circ * jst_pct_i / 100
    sem_dash = circ - jst_dash
    sem_offset = -69 - jst_dash

    insight_rows = []
    if suggestions:
        for s in suggestions[:8]:
            plain = markdown_to_plain(s)
            icon, cls = ("⚠️", "amber") if ("⚠️" in plain or "未達" in plain or "偏低" in plain) else (("🔍", "blue") if "檢查" in plain or "检查" in plain else ("✅", "green"))
            insight_rows.append(f'<div class="insight-item"><div class="ic {cls}">{icon}</div><div>{esc(plain)}</div></div>')
    else:
        insight_rows.append('<div class="insight-item"><div class="ic green">✅</div><div>暂无明显异常，当前账户整体 ROI 表现稳定。</div></div>')

    spend_badge_2h = delta_badge(spend_2h.get("diff", 0), spend_2h.get("index_pct", 0), spend_2h.get("direction", "neutral"))
    spend_badge_yd = delta_badge(spend_yd.get("diff", 0), spend_yd.get("index_pct", 0), spend_yd.get("direction", "neutral"))
    roi_badge_2h = delta_badge(roi_2h.get("diff", 0), roi_2h.get("index_pct", 0), roi_2h.get("direction", "neutral"))
    roi_badge_yd = delta_badge(roi_yd.get("diff", 0), roi_yd.get("index_pct", 0), roi_yd.get("direction", "neutral"))

    def format_card(name: str, spend: float, roi: float, color: str) -> str:
        fd_spend, fd_roi = get_format_deltas(split_data, name)
        s2 = fd_spend.get("vs_2h", {})
        r2 = fd_roi.get("vs_2h", {})
        spend_badge = delta_badge_small(s2.get("diff", 0), s2.get("index_pct", 0), s2.get("direction", "neutral"))
        roi_badge = delta_badge_small(r2.get("diff", 0), r2.get("index_pct", 0), r2.get("direction", "neutral"))
        return f'''<div class="format-card" style="--fmt-color:{color}"><div class="fmt-top"><span class="fmt-dot"></span><span class="fmt-name">{name}</span><span class="fmt-tag">新/旧</span></div><div class="fmt-grid"><div><div class="fmt-value">{money(spend)} {spend_badge}</div><div class="fmt-label">花费指数</div></div><div><div class="fmt-value">{roi_txt(roi)} {roi_badge}</div><div class="fmt-label">ROI 指数</div></div></div></div>'''

    total_jst_rev = sum(safe_float(s.get("JST花费(SPD)", 0)) * safe_float(s.get("JST ROI", 0)) for s in skus)
    total_sem_rev = sum(safe_float(s.get("SEM花费(SPD)", 0)) * safe_float(s.get("SEM ROI", 0)) for s in skus)
    total_ht_rev = sum(a["ht_spend"] * a["ht_roi"] for a in account_stats)
    format_cards_html = '<div class="format-grid">' + ''.join([
        format_card("JST", total_jst, total_jst_rev / total_jst if total_jst else 0, "#0075de"),
        format_card("SEM", total_sem, total_sem_rev / total_sem if total_sem else 0, "#e07a2c"),
        format_card("HT", total_ht, total_ht_rev / total_ht if total_ht else 0, "#d24a4a"),
    ]) + '</div>'

    # Build series cards
    legacy_card = series_card("Legacy", legacy_stats, "var(--c-tide)")
    pwd_card = series_card("PWD", pwd_stats, "var(--c-tidel)")
    series_cards_html = f'<div class="series-grid">{legacy_card}{pwd_card}</div>'

    head = load_painter_head()
    body = f'''
<body>
<div class="header"><div class="header-left"><div class="logo-mark">JZT</div><div><h1>京准通数据看板</h1><div class="header-sub">JD Marketing Intelligence · Real-time Performance Dashboard</div></div></div><div class="header-right"><span class="live-pill"><span class="live-dot"></span>Live · {generated_at}</span></div></div>
<div class="meta-bar"><div class="meta-item"><span class="ic">⏱</span><span>生成时间</span><span class="v">{generated_at}</span></div><div class="meta-item"><span class="ic">📁</span><span>数据文件</span><span class="v">{esc(source_name)}</span></div><div class="meta-item"><span class="ic">📅</span><span>数据时间</span><span class="v">{esc(source_time)}</span></div><div class="meta-item"><span class="ic">🎯</span><span>口径</span><span class="v">排除 Paid BI · JST+SEM+HT</span></div><div class="meta-item warn"><span class="ic">⚠️</span><span>最新有效基线</span></div></div>
<div class="kpi-strip"><div class="kpi-card b-blue"><div class="label">💰 总花费</div><div class="value"><span class="unit">¥</span>{fmt_num(total_all_spend)}</div><div class="sub"><span class="delta">JST+SEM+HT</span>跨 {len(account_stats)} 账户</div><div class="kpi-deltas">{spend_badge_2h} {spend_badge_yd}</div></div><div class="kpi-card b-green"><div class="label">📈 加权平均 ROI</div><div class="value">{roi_txt(weighted_roi)}</div><div class="sub"><span class="delta">{'全目标达成' if low_accounts == 0 else '存在异常'}</span>{low_accounts} 账户未达标</div><div class="kpi-deltas">{roi_badge_2h} {roi_badge_yd}</div></div><div class="kpi-card b-purple"><div class="label">🎯 分账户 ROI 目标</div><div class="value" style="font-size:22px">1.5 / 2.5 / 3.0</div><div class="sub">Tide/Ariel / L 系列 / Downy 阶梯</div></div><div class="kpi-card b-red"><div class="label">⚠️ 低于目标账户</div><div class="value">{low_accounts}</div><div class="sub">{len(suggestions)} 条 SKU 级预警 → 详见洞察</div></div></div>
{series_cards_html}
{format_cards_html}
<div class="accounts-grid">{''.join(account_cards)}</div>
<div class="section-title">SKU 明细 · JST + SEM 分拆数据 <span class="meta">（口径：排除 Paid BI · JST+SEM+HT）</span><span class="badge-count">{sku_count} SKUs</span></div>
<div class="dashboard-layout"><div class="main-col">{''.join(detail_cards)}</div><div class="side-col"><div class="side-panel"><div class="side-title">HT 渠道效率排行</div>{''.join(ht_rank_rows)}</div><div class="side-panel"><div class="side-title">JST vs SEM 花费构成</div><div class="donut-wrap"><div class="donut-svg"><svg width="110" height="110" viewBox="0 0 110 110"><circle cx="55" cy="55" r="44" fill="none" stroke="#f0f0ec" stroke-width="16"/><circle cx="55" cy="55" r="44" fill="none" stroke="#0075de" stroke-width="16" stroke-dasharray="{jst_dash:.1f} {circ:.0f}" stroke-dashoffset="-69" stroke-linecap="round"/><circle cx="55" cy="55" r="44" fill="none" stroke="#e07a2c" stroke-width="16" stroke-dasharray="{sem_dash:.1f} {circ:.0f}" stroke-dashoffset="{sem_offset:.1f}" stroke-linecap="round"/></svg><div class="donut-center"><div class="v">{short_money(jst_sem_total)}</div><div class="l">JST+SEM</div></div></div><div class="donut-legend"><div class="row"><span class="dot" style="background:#0075de"></span><span class="name">JST</span><span class="pct">{jst_pct_i}%</span></div><div class="row"><span class="dot" style="background:#e07a2c"></span><span class="name">SEM</span><span class="pct">{sem_pct_i}%</span></div><div class="row"><span class="dot" style="background:#d24a4a"></span><span class="name">HT</span><span class="pct">{money(total_ht)}</span></div></div></div></div><div class="side-panel"><div class="side-title">各账户综合 ROI 状态</div>{''.join(heat_rows)}</div></div></div>
<div class="insights-section"><div class="section-title">📊 建议与洞察</div><div class="insight-list">{''.join(insight_rows)}</div></div>
<div class="footer"><span>数据来源：Fabric CSV · 口径：排除 Paid BI · JST+SEM+HT</span><span class="brand-mark"><span class="ico"></span>Hermes Atelier</span></div>
</body>
</html>'''
    return "<!doctype html>\n<html lang=\"zh-CN\">\n" + head + body
