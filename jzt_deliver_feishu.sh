#!/bin/bash
# jzt_deliver_feishu.sh — JZT Feishu delivery no_agent script
# Hermes cron no_agent mode: runs the Python delivery script with args
#
# Usage: jzt_deliver_feishu.sh <slot_label> [--skip-dashboard]

set -euo pipefail

# Auto-detect slot label from current time if not provided (cron no_agent mode)
# Cron runs: HH:02 → HH02 (e.g. 08:02→0802), 23:57→2357
SLOT_LABEL="${1:-${JZT_SLOT_LABEL:-}}"
if [ -z "$SLOT_LABEL" ]; then
    HOUR="$(date +%H)"
    MINUTE="$(date +%M)"
    if [ "$HOUR" = "23" ] && [ "$MINUTE" -ge 57 ]; then
        SLOT_LABEL="2357"
    else
        SLOT_LABEL="${HOUR}02"
    fi
fi
shift || true

REPORT_DATE="${JZT_REPORT_DATE:-$(date +%F)}"
SCRIPT="/Users/sevenyip/.hermes/scripts/jingzhuntong/jzt_deliver_feishu.py"
PYTHON_BIN="/Users/sevenyip/.hermes/hermes-agent/venv/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
    PYTHON_BIN="python3"
fi

echo "[$(date '+%H:%M:%S')] JZT Delivery: slot=$SLOT_LABEL date=$REPORT_DATE"

ARTIFACT_DIR="/Users/sevenyip/.openclaw/runtime/jzt_reports/$REPORT_DATE"
SPLIT_FILE="$ARTIFACT_DIR/${SLOT_LABEL}_split.json"
META_FILE="$ARTIFACT_DIR/${SLOT_LABEL}_meta.json"
DISCORD_FILE="$ARTIFACT_DIR/${SLOT_LABEL}_discord.md"
COMPUTE_SCRIPT="/Users/sevenyip/.hermes/scripts/jingzhuntong/jzt_pipi_compute.sh"

# If pre-compute failed or artifacts are missing, try once here instead of
# delivering a misleading empty report. If compute still fails, no_agent cron
# reports an error rather than sending "暫無數據" as if it succeeded.
if [ ! -s "$SPLIT_FILE" ] || [ ! -s "$META_FILE" ] || [ ! -s "$DISCORD_FILE" ]; then
    echo "WARN: missing JZT artifacts for slot=$SLOT_LABEL; running compute before delivery"
    JZT_SLOT_LABEL="$SLOT_LABEL" JZT_REPORT_DATE="$REPORT_DATE" bash "$COMPUTE_SCRIPT"
fi

"$PYTHON_BIN" "$SCRIPT" \
    --slot-label "$SLOT_LABEL" \
    --report-date "$REPORT_DATE" \
    "$@" \
    2>&1

echo "[$(date '+%H:%M:%S')] ✅ JZT Delivery complete: slot=$SLOT_LABEL date=$REPORT_DATE"
