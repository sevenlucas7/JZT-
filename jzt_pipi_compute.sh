#!/bin/bash
# jzt_pipi_compute.sh — JZT 預計算 no_agent script
# Hermes cron no_agent 模式：stdout verbatim deliver
# 非空 stdout → 發送；空 stdout → 靜默
#
# Usage (by Hermes cron): this script is called with slot_label and report_date
# The cron job sets JZT_SLOT_LABEL env var, or we can pass as first argument

set -euo pipefail

# Auto-detect slot label from current time if not provided (cron no_agent mode)
# Cron runs: HH:00 → HH02 (e.g. 08:00→0802), 23:55→2357
SLOT_LABEL="${1:-${JZT_SLOT_LABEL:-}}"
if [ -z "$SLOT_LABEL" ]; then
    HOUR="$(date +%H)"
    MINUTE="$(date +%M)"
    if [ "$HOUR" = "23" ] && [ "$MINUTE" -ge 55 ]; then
        SLOT_LABEL="2357"
    else
        SLOT_LABEL="${HOUR}02"
    fi
fi

REPORT_DATE="${JZT_REPORT_DATE:-$(date +%F)}"

JZT_VENV="python3"
JZT_SCRIPT="/Users/sevenyip/.hermes/scripts/jingzhuntong/jzt_report.py"
OUTPUT_DIR="/Users/sevenyip/.openclaw/runtime/jzt_reports"
SPLIT_SCRIPT="/Users/sevenyip/.hermes/scripts/jingzhuntong/jzt_sem_jst_split.py"
PRIMARY_DATA_DIR="/Users/sevenyip/Library/CloudStorage/OneDrive-insidemedia.net/LDY/rawdata/Fabric"
FALLBACK_DATA_DIR="/Users/sevenyip/Library/Group Containers/UBF8T346G9.OneDriveStandaloneSuite/OneDrive - insidemedia.net.noindex/OneDrive - insidemedia.net/LDY/rawdata/Fabric"
DATA_DIR="${JZT_DATA_DIR:-}"
if [ -z "$DATA_DIR" ]; then
    DATA_DIR="$(python3 - "$PRIMARY_DATA_DIR" "$FALLBACK_DATA_DIR" <<'PY'
from pathlib import Path
import sys
for d in map(Path, sys.argv[1:]):
    try:
        files = sorted(d.glob('*.csv'), key=lambda p: p.stat().st_mtime)
        if not files:
            continue
        with files[-1].open('rb') as f:
            f.read(1)
        print(d)
        raise SystemExit(0)
    except Exception as e:
        print(f"WARN: data dir unreadable: {d} ({type(e).__name__}: {e})", file=sys.stderr)
        continue
# No readable CSV in either configured source. Print nothing so the shell can
# fail fast instead of retrying jzt_report.py for 120+ seconds and timing out.
PY
)"
fi
if [ -z "$DATA_DIR" ]; then
    echo "ERROR: No readable CSV files found in JZT data sources"
    echo "PRIMARY: $PRIMARY_DATA_DIR"
    echo "FALLBACK: $FALLBACK_DATA_DIR"
    exit 1
fi
export JZT_DATA_DIR="$DATA_DIR"

echo "[$(date '+%H:%M:%S')] JZT Compute: slot=$SLOT_LABEL date=$REPORT_DATE data_dir=$DATA_DIR"

run_report() {
    "$JZT_VENV" "$JZT_SCRIPT" \
        --data-dir "$DATA_DIR" \
        --output-dir "$OUTPUT_DIR" \
        --slot-label "$SLOT_LABEL" \
        --report-date "$REPORT_DATE" \
        2>&1
}

# Step 1: Run main jzt_report.py with retries.
# OneDrive/FileProvider can temporarily leave the latest CSV dataless and raise
# Errno 11 (Resource deadlock avoided). Do not let set -e abort before retrying.
JZT_EC=0
for attempt in 1 2 3 4 5; do
    set +e
    run_report
    JZT_EC=$?
    set -e
    if [ $JZT_EC -eq 0 ]; then
        break
    fi
    if [ $attempt -lt 5 ]; then
        echo "WARN: jzt_report.py failed with exit code $JZT_EC; retry $attempt/4 after 30s"
        sleep 30
    fi
done
if [ $JZT_EC -ne 0 ]; then
    echo "ERROR: jzt_report.py failed after retries with exit code $JZT_EC"
    exit $JZT_EC
fi

# Step 2: Validate artifacts exist and are non-empty
ARTIFACT_DIR="$OUTPUT_DIR/$REPORT_DATE"
for f in "${SLOT_LABEL}_discord.md" "${SLOT_LABEL}_full.md" "${SLOT_LABEL}_meta.json"; do
    if [ ! -s "$ARTIFACT_DIR/$f" ]; then
        echo "ERROR: Artifact missing or empty: $ARTIFACT_DIR/$f"
        # Retry once
        sleep 60
        run_report
        if [ ! -s "$ARTIFACT_DIR/$f" ]; then
            echo "ERROR (retry failed): Artifact still missing: $ARTIFACT_DIR/$f"
            exit 1
        fi
    fi
done

# Step 3: Validate meta.json has required fields
META_FILE="$ARTIFACT_DIR/${SLOT_LABEL}_meta.json"
python3 -c "
import json
with open('$META_FILE') as f:
    d = json.load(f)
assert d.get('source_file_name'), 'MISSING source_file_name'
assert d.get('source_file_modified_at'), 'MISSING source_file_modified_at'
print('Meta validation OK')
" 2>&1

# Step 4: Run SEM/JST split computation
python3 "$SPLIT_SCRIPT" \
    --output-dir "$OUTPUT_DIR" \
    --slot-label "$SLOT_LABEL" \
    --report-date "$REPORT_DATE" \
    2>&1

echo "[$(date '+%H:%M:%S')] ✅ JZT Compute complete: slot=$SLOT_LABEL date=$REPORT_DATE"

# Step 5: Git push to GitHub for GitHub Pages hosting
# Requires GITHUB_TOKEN env var and JZT_REPO_DIR env var
JZT_REPO_DIR="${JZT_REPO_DIR:-}"
GITHUB_TOKEN="${GITHUB_TOKEN:-}"
GITHUB_REMOTE="${GITHUB_REMOTE:-origin}"
GITHUB_BRANCH="${GITHUB_BRANCH:-main}"

if [ -z "$JZT_REPO_DIR" ] || [ -z "$GITHUB_TOKEN" ]; then
    echo "[$(date '+%H:%M:%S')] SKIP git push: JZT_REPO_DIR or GITHUB_TOKEN not set"
else
    cd "$JZT_REPO_DIR"
    # Set git credentials for push
    git remote set-url "$GITHUB_REMOTE" "https://sevenlucas7:${GITHUB_TOKEN}@github.com/sevenlucas7/JZT-.git" 2>/dev/null || true

    # Stage data files (split.json history) and any updated content
    if [ -d "$JZT_REPO_DIR/data" ]; then
        git add data/*.json 2>/dev/null || true
    fi

    # Check if there are changes to commit
    if git diff --cached --quiet 2>/dev/null; then
        echo "[$(date '+%H:%M:%S')] Git: no changes to push"
    else
        COMMIT_MSG="Auto-update $(date '+%Y-%m-%d %H:%M:%S') - slot=$SLOT_LABEL date=$REPORT_DATE"
        git commit -m "$COMMIT_MSG" 2>&1 || true
        echo "[$(date '+%H:%M:%S')] Git: committing changes..."
        # Push to GitHub
        GIT_SSH_COMMAND="ssh -o StrictHostKeyChecking=no" git push "$GITHUB_REMOTE" "$GITHUB_BRANCH" 2>&1 || {
            echo "[$(date '+%H:%M:%S')] WARN: git push failed, will retry..."
            sleep 10
            GIT_SSH_COMMAND="ssh -o StrictHostKeyChecking=no" git push "$GITHUB_REMOTE" "$GITHUB_BRANCH" 2>&1 || {
                echo "[$(date '+%H:%M:%S')] WARN: git push retry failed, continuing without push"
            }
        }
        echo "[$(date '+%H:%M:%S')] Git push complete: https://sevenlucas7.github.io/JZT-/"
    fi
fi

exit 0
