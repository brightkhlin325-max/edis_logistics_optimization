# EDIS UI 改版整合計畫
> 分支：`new_uidesign` | 原則：**保留所有現有 API 功能，套用 PDF 新版視覺設計**

---

## 核心原則

> ⚠️ **不刪除任何已串接的 API 功能**，只重新設計版面與視覺呈現。
> 新設計（PDF）的精神：深藍側欄、KPI 折線卡片、彩色長條圖、雷達圖、分頁標籤。

---

## 現有頁面與已串接 API（完整盤點，全部保留）

| # | 頁面 (pageId) | 已串接 API | 改版動作 |
|---|---|---|---|
| 1 | **dashboard** | `/api/metrics`、`/api/predict`、`/api/executive-summary`、`/api/scenario-analysis` | ✨ 套新版：3 KPI 折線卡 + Top10 表 |
| 2 | **risk-list** | `/api/predict`、`/api/regions`（篩選 + 門檻 + 分頁）| ✨ 加橫向風險分佈長條圖 |
| 3 | **optimization** | `/api/optimize`、`/api/chart/monthly`、`/api/diagnose/monthly` | 🔄 保留，僅統一卡片樣式 |
| 4 | **ai-assistant** | `/api/llm/manager-brief`、Ollama chat、`/api/explain/{id}` | 🔄 保留，僅統一樣式 |
| 5 | **model-perf** | `/api/metrics`（混淆矩陣 + 特徵重要性）| ✨ 套新版：雷達圖 + 特徵長條圖 + 分頁標籤 |
| 6 | **region-map** | `/api/regions` | 🔄 保留 |
| 7 | **rbac** | （靜態權限矩陣表）| 🔄 保留 |
| 8 | **settings** | `/api/threshold-tuning`、`/api/upload-training`、`/api/reset-orders`、`/api/retrain`、`/api/tasks/{id}/status`、`/api/retrain/adopt`、`/api/retrain/discard` | 🔄 保留（門檻調整已在此頁）|
| 9 | **llm-settings** | `/api/llm/settings` | 🔄 保留 |
| — | login | `/api/login` | 🔄 保留 |

**圖例**：✨ 大改版（套 PDF 新設計）　🔄 保留功能、僅統一卡片/配色樣式

---

## 改版三大重點頁面（對應 PDF 三頁）

### Page 1 — Dashboard（✨ 大改版）

**保留的功能**：`renderMetrics()`、`fetchPredictions()`、executive summary、scenario analysis 全數保留。

**新版版面**：
```
┌──────────────────────────────────────────────────────┐
│ [3 張 KPI 折線卡片]                                  │
│  整體延遲率 54.8%  │ ROC-AUC 0.803 │ 高風險 11,363  │
│  ╱╲__╱╲ (sparkline)│ __╱‾╲_        │ __╱‾‾‾        │
├──────────────────────────────────────────────────────┤
│ [既有的 executive summary / scenario 區塊保留]       │
├──────────────────────────────────────────────────────┤
│ [最近高風險訂單 Top 10 表格 — 既有 fetchPredictions] │
└──────────────────────────────────────────────────────┘
```
- KPI 數字來源不變（`/api/metrics?threshold=`）
- 新增：卡片底部 **SVG 折線 sparkline**（裝飾性視覺）
- 既有的進階區塊（executive summary、情境分析）整理進可收合卡片

---

### Page 2 — 風險訂單列表（✨ 加長條圖）

**保留的功能**：搜尋、風險篩選、運送模式篩選、地區篩選、門檻、分頁，全數保留。

**新增**：左側 **風險等級分佈橫向長條圖**（High/Medium/Low 數量）
```
┌────────────────────────┐  ┌──────────────────────────┐
│ 風險分佈                │  │ [既有訂單表格 + 篩選列]  │
│ High   ████ 42         │  │ 搜尋 / 篩選 / 門檻 / 分頁│
│ Medium ████████ 87    │  │ 彩色進度條 (既有)        │
│ Low    ██████████ 134 │  │                          │
└────────────────────────┘  └──────────────────────────┘
```
- 長條圖資料：用既有 `/api/predict?threshold=` 的 count，或新增 `/api/summary?by=risk_bucket`

---

### Page 3 — 模型效能（✨ 雷達圖 + 分頁標籤）

**保留的功能**：`loadModelPerformance()`、混淆矩陣、特徵重要性，全數保留。

**新增**：
- **雷達圖**（SVG polygon）：Precision / Recall / ROC-AUC / F1 四軸
- **分頁標籤切換**：`評估指標 | 混淆矩陣 | 特徵重要性`
- 特徵重要性沿用既有水平長條圖（資料來自 `/api/metrics` 真實 feature_importance）

```
┌──────────────────────────────────────────────────┐
│ [Tab] 評估指標 | 混淆矩陣 | 特徵重要性           │
├──────────────────────────────────────────────────┤
│  ┌────────────┐   ┌──────────────────────────┐   │
│  │  雷達圖    │   │ Feature Importance 長條圖│   │
│  │ Precision  │   │ Standard Class  ███ 34.7%│   │
│  │  Recall AUC│   │ Same Day        ██  19.7%│   │
│  │    F1      │   │ ...（真實資料）          │   │
│  └────────────┘   └──────────────────────────┘   │
└──────────────────────────────────────────────────┘
```

---

## 共用視覺更新（套用全站）

| 元素 | 新版規格 |
|---|---|
| 側邊欄 | 深藍 `#437096`，保留全部 9 個導航項目 |
| 卡片 | 白底 `#ffffff`、圓角、淺邊框、輕陰影 |
| 風險色 | High `#e74c3c` / Medium `#e67e22` / Low `#27ae60` |
| 長條圖 | 純 CSS，bar 寬度 transition 0.6s |
| 折線/雷達 | SVG polyline / polygon（無外部 library）|
| 字型 | 沿用 DM Sans / DM Mono / Noto Sans TC |

---

## 實作策略（安全、不破壞功能）

1. **不動 `<script>` 的 API 邏輯** — 所有 `fetch`、`load*()`、`render*()` 函數原封不動
2. **只改 HTML 結構與 CSS** — 調整 DOM 排版、新增圖表容器
3. **新增的圖表函數獨立** — `renderSparkline()`、`renderRadarChart()`、`renderRiskDistBar()`，不影響既有邏輯
4. **逐頁驗證** — 每改一頁就用瀏覽器確認 API 資料正常載入

---

## 實作優先順序

| 優先 | 任務 | 風險 |
|---|---|---|
| 🔴 1 | 全站側邊欄 + 卡片樣式統一（CSS）| 低 |
| 🔴 2 | Dashboard 3 KPI 折線卡片 | 低 |
| 🟡 3 | 模型效能：雷達圖 + 分頁標籤 | 中 |
| 🟡 4 | 風險列表：橫向風險分佈長條圖 | 中 |
| 🟢 5 | 其餘頁面卡片樣式微調 | 低 |

---

## 待紹光確認

1. **Dashboard 既有的 executive summary / scenario analysis 區塊** — 保留在首頁下方，還是移到獨立頁？
2. **模型效能分頁標籤** — 三個 tab（指標/混淆矩陣/特徵）是否符合預期？
3. **門檻設定** — 目前在「系統設定」頁，是否要在風險列表頁也放一個快捷滑桿？
4. 是否需要保留所有 9 個側邊欄項目，或精簡合併某些頁面？

---

*確認後即依「只改樣式、不動 API」原則實作。*
