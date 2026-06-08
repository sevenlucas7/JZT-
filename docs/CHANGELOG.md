# JZT 在线看板修改记录

## 2026-06-04 — 在线版环比展示与 OneDrive 最新数据同步

### 背景

Boss 在飞书截图标注了 JZT 在线看板两个问题：

1. 顶部 KPI、分组卡片、账户卡片里同时展示两个没有说明的百分比，容易误解。
2. 鼠标 hover 到环比 badge 时显示 `新数据 / 旧数据 × 100`，不适合作为用户界面文案。
3. SKU 明细表头写 `新/旧`，不够直观，应改成 `环比`。

### 已完成修改

- 文件：`jzt_dashboard_renderer.py`
- 新增 `mom_title(index_pct, direction)`：
  - 底层仍按 `新数据 / 旧数据 × 100` 计算指数。
  - hover tooltip 改成人话：
    - `环比上升xx.x%`
    - `环比下降xx.x%`
    - `环比持平`
    - 无旧数据时显示 `暂无可比旧数据`
- `delta_badge()`：
  - 可见 badge 从单纯 `104%` 改成 `环比 104%`。
  - title 不再显示公式。
- `delta_badge_small()` / `sku_delta_chip()`：
  - 小 badge 仍显示指数百分比，例如 `104%`。
  - hover title 改为环比自然语言。
- 顶部 KPI / series / account card：
  - 每个指标只保留一个最新环比 badge。
  - 移除未说明的 `vs yesterday` 同屏展示，避免两个百分比并列造成歧义。
- SKU 表头：
  - `综合花费 新/旧` → `综合花费 环比`
  - `综合 ROI 新/旧` → `综合 ROI 环比`
  - `JST 花费 新/旧` → `JST 花费 环比`
  - `JST ROI 新/旧` → `JST ROI 环比`
  - `SEM 花费 新/旧` → `SEM 花费 环比`
  - `SEM ROI 新/旧` → `SEM ROI 环比`
- Format cards：
  - 标签 `新/旧` → `环比`

### 数据同步记录

当天 OneDrive / Fabric 新数据已同步到在线版：

- CSV：`GMEC-Downy_全品牌数据Raw-当天_20260604_20260604.csv`
- CSV 数据更新时间：`2026-06-04 16:48:11`
- JZT 计算时间：`2026-06-04 16:56:16`
- 在线版 slot：`1602`
- GitHub commit：`55dbb04 Auto-update JZT dashboard 2026-06-04 1602`
- 线上验证 URL：`https://sevenlucas7.github.io/JZT-/?v=55dbb04`

### 验证结果

已验证线上页面：

- `data/latest_meta.json` 为 `slot_label = 1602`
- `source_file_modified_at = 2026-06-04 16:48:11`
- 页面 HTML 包含最新数据时间 `2026-06-04 16:48:11`
- 页面无旧文案残留：
  - 无 `新/旧`
  - 无 `新数据 / 旧数据 × 100`
  - 无 `vs yesterday`
  - 无 `vs 2h ago`
- SKU 表头含 `环比`
- tooltip 样本：
  - `环比上升11.9%`
  - `环比上升3.8%`
  - `环比上升10.2%`

### 维护注意

1. 手动同步在线版时，要显式指定目标 slot/date，避免 session 环境变量残留导致倒回旧数据：

```bash
JZT_PYTHON_BIN=/usr/bin/python3 \
JZT_SLOT_LABEL=1602 \
JZT_REPORT_DATE=2026-06-04 \
bash "$HOME/.hermes/scripts/jingzhuntong/jzt_sync_github_pages.sh"
```

2. 当前 session 曾出现过残留环境变量：

```bash
JZT_SLOT_LABEL=1502
JZT_REPORT_DATE=2026-06-04
```

如果不显式覆盖，wrapper 会优先读环境变量，而不是按当前时间自动推 slot。

3. 同步后必须检查：

```bash
cd "$HOME/JZT报数"
python3 - <<'PY'
import json, re
from pathlib import Path
meta = json.loads(Path('data/latest_meta.json').read_text())
html = Path('index.html').read_text()
print(meta.get('report_date'), meta.get('slot_label'), meta.get('source_file_modified_at'))
print('old_ui_hits', bool(re.search(r'新/旧|新数据 / 旧数据|vs yesterday|vs 2h ago', html)))
PY
```

4. 线上验证建议加 cache-busting commit query：

```bash
curl -L 'https://sevenlucas7.github.io/JZT-/?v=<commit>'
```

### 相关文件

- Repo renderer：`~/JZT报数/jzt_dashboard_renderer.py`
- Online repo：`~/JZT报数`
- Sync wrapper：`~/.hermes/scripts/jingzhuntong/jzt_sync_github_pages.sh`
- Sync helper：`~/.hermes/scripts/jingzhuntong/jzt_sync_github_pages.py`
- Runtime artifacts：`~/.openclaw/runtime/jzt_reports/<date>/`
- Skill reference：`jzt-report-pipeline/references/github-pages-online-dashboard.md`

---

## 2026-06-04 — 在线版建议数据修复

### 背景

Boss 指出「JZT 看板在线版」展示数据可能不对，需要对照 cron job 文字报数和本地 JZT 看板。经核对，账户总花费、ROI、SKU 明细与 cron 文字报数一致；真正不一致的是在线版「建议与洞察」区域。

### 根因

`~/.hermes/scripts/jingzhuntong/jzt_sync_github_pages.py` 调用 repo renderer 时传入了空建议列表：

```python
html = build_html_dashboard(data.get("skus", []), data, meta, [])
```

导致在线版显示：

```text
低于目标账户 1
0 条 SKU 级预警
暂无明显异常，当前账户整体 ROI 表现稳定。
```

但同一 slot 的 cron 文字报数和本地看板实际有 5 条建议。

### 已完成修改

- `~/.hermes/scripts/jingzhuntong/jzt_sync_github_pages.py`
  - 从 repo `jzt_deliver_feishu.py` import `generate_suggestions`
  - 在线版 sync 时按同一套建议引擎生成 suggestions
  - 再传入 `build_html_dashboard(...)`
- `~/JZT报数/jzt_dashboard_renderer.py`
  - 修复 Legacy / PWD series card 的 ROI 环比 badge：不能复用总览 ROI 环比，需按 series 内账户加权重算

### 验证结果

slot：`2026-06-04 1802`

账户汇总对照 cron 文字报数：

| 账户 | cron 总花费 / ROI | online split 总花费 / ROI | 结果 |
|---|---:|---:|---|
| GMEC-Ariel | 5532.17 / 2.8 | 5532.17 / 2.8 | OK |
| GMEC-Ariel-L | 11791.80 / 3.4 | 11791.76 / 3.4 | OK |
| GMEC-Downy | 12774.90 / 2.9 | 12774.92 / 2.9 | OK |
| GMEC-Tide | 3731.10 / 2.3 | 3731.10 / 2.3 | OK |
| GMEC-Tide-L | 10913.80 / 3.5 | 10913.82 / 3.5 | OK |

线上已验证：

- `slot_label = 1802`
- `source_file_modified_at = 2026-06-04 17:56:38`
- 顶部 KPI 显示 `低于目标账户 1 / 5 条 SKU 级预警`
- 「建议与洞察」显示 5 条建议
- 不再显示 `暂无明显异常`

相关 commits：

- `4d12754 Auto-update JZT dashboard 2026-06-04 1802`
- `1c6ea09 Fix JZT online dashboard suggestion data`

## 2026-06-08 — Fix automatic online dashboard sync with text-report data

- Root cause: JZT compute/text artifacts updated successfully, but the separate GitHub Pages sync job committed locally and skipped push because the cron/Hermes non-interactive environment did not inherit Boss' interactive zsh `GITHUB_TOKEN`.
- Fix 1: `~/.hermes/scripts/jingzhuntong/jzt_sync_github_pages.sh` now sources `GITHUB_TOKEN` from `zsh -lic` when the non-interactive environment lacks it.
- Fix 2: `~/.hermes/scripts/jingzhuntong/jzt_pipi_compute.sh` now runs the GitHub Pages sync wrapper best-effort immediately after generating the split artifact, so the online dashboard advances with the same freshly computed text-report data instead of relying only on the separate `:03` sync cron.
- Verification: local, `origin/main`, and GitHub Pages `data/latest_meta.json` all report `2026-06-08 1202`, `source_file_modified_at=2026-06-08 11:56:43`, `generated_at=2026-06-08 12:03:25`.
