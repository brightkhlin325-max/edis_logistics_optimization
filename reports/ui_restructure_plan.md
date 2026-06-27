# SLIDE 介面重構規劃（定案版）
> 8 項頁面調整 + Sidebar 角色重組。CSV 全站統一功能暫不動。

## 已定案決策（4 點）
1. **項目 4 合併**：兩個最佳化器**統一用 `decision_dataset.csv`**。
2. **項目 5**：「預警判定門檻」拉桿 + 「門檻即時校正建議」面板**一起移除**。
3. **刪除的後端端點**（`/api/roi/optimize`、`/api/roi/whatif`）：**先只隱藏前端，後端保留**，確認穩定後再清。
4. **區域風險地圖**：**只從 sidebar 移除**（程式與後端保留，不刪檔）。

---

## Sidebar 重組（目標）

| 角色 | 目標項目 | 現況差異 |
|---|---|---|
| **Viewer** | Dashboard 總覽、最佳化調度 | 移除「最佳化ROI模擬器」（→ 併入最佳化調度，項目4）|
| **Manager** | 風險訂單管理、AI 決策助理 | 移除「收益預測」（→ 併入模型診斷與重訓，項目8）|
| **Engineer** | 模型診斷與重訓、權限管理、模型設定 | 從 sidebar 移除「區域風險地圖」（程式保留）|

對應檔案：`static/index.html`（nav 區塊 40–73 行）

> 移除 `nav-roi-simulator`、`nav-profit-prediction`、`nav-region-map` 三個**導航項目**。
> 決策 4：`region-map` **只移除 nav 連結**，`page-region-map` section、`region_map.js`、`/api/regions`、`/api/geojson/*` 後端**全部保留**（之後可能還原）。
> `roi-simulator` / `profit-prediction` 的 section 則因合併而併入他頁（項目 4 / 8）。

---

## 逐項規劃

### 1. ROI 模擬器：延遲罰金「建議值」說明 + 可調整
**現況**：`roi_simulator.html:45` 有 `#roiPenalty` 輸入框（預設 250），但沒說「建議填多少」。
**做法**：
- 在罰金輸入框旁加「建議區間」提示（例如：依 SLA 合約，建議 $200–$500；預設 $250 對齊調度引擎）。
- 可選：加 3 顆快捷鈕（保守 $150 / 標準 $250 / 嚴格 $500）一鍵帶入。
**檔案**：`roi_simulator.html` 控制列（38–50 行）。

### 2. 刪除「ROI 最佳化求解 (PuLP) — 該救誰」整塊
**現況**：`roi_simulator.html:160–241`（C 區塊，含 `#roiOptResult`、客戶層彙整、入選明細）。
**做法**：整塊 C 區從前端移除；清理 `roi_simulator.js` 的 `runRoiOptimize()`、`jumpToOptimization()`、`syncRoiSimulatorRole()` 相關 DOM 呼叫。
**後端**：`/api/roi/optimize`（app.py 2927）**保留不刪**（決策 3：先隱藏前端），僅前端不再呼叫。
> 與項目 4 一致 —— ROI 區不再自己做最佳化，統一由調度引擎負責。

### 3. ROI 名單分頁（目前一次只看 50 筆）
**現況**：`roi_simulator.html` 的「風險暴露名單」`#roiAtRiskBody`（131–157 行）一次顯示固定筆數；散點 `max_points=1500` 取樣。
**做法**：
- 後端 `/api/roi/portfolio` 的 `at_risk_list` 加 `page` / `limit` 參數（預設 50/頁）。
- 前端名單下方加「上一頁 / 第 X 頁 / 下一頁」，沿用 `risk_list` 既有分頁樣式。
**檔案**：`app.py`（roi_portfolio，2862–2925）、`roi_simulator.js`（`renderAtRisk`）、`roi_simulator.html`。

### 4. 「最佳化ROI模擬器」與「最佳化調度」合併（**重點：先驗證資料源**）
**調查結果（關鍵）**：兩者資料源**目前不同**：
| 頁面 | 端點 | 資料源 |
|---|---|---|
| 最佳化調度 | `/api/optimize` | `predictions.csv`（延遲，order-item）|
| ROI 最佳化 | `/api/roi/optimize` | `decision_dataset.csv`（訂單層，含收益）|

**做法（定案）**：
- 合併後保留**一個**「最佳化調度」頁（Viewer），ROI 的「真價值/在險名單/散點/Trust Map」做為其分析區塊併入。
- **統一資料源 → 全部改吃 `decision_dataset.csv`**（決策 1）。`/api/optimize` 原本吃 `predictions.csv`，需改為以 decision_dataset 為準（或在合併頁只呼叫吃 decision_dataset 的端點）。
- 移除重複的最佳化求解器（與項目 2 一致，只留調度引擎那個 PuLP）。
**檔案**：`optimization.html` + `roi_simulator.html`（合併）、`optimization.js` + `roi_simulator.js`、`index.html`（移除 roi nav）、`app.py`（最佳化端點統一資料源）。
> ⚠️ 最複雜、風險最高，**最後做**。完成後必須驗證：合併頁的最佳化結果、KPI、散點數字與統一前一致。

### 5. 風險訂單管理：移除「預警判定門檻」拉桿 + 校正面板
**現況**：`risk_list.html:11–14` 有 `預警判定門檻 (Threshold)` 的 `range` 拉桿（`updateThreshold()`）；41 行「門檻即時校正建議」面板 `#thresholdTuningPanel`。
**做法（定案）**：拉桿區塊（含 `thresholdValDisplay`）**與**「門檻即時校正建議」面板（`#thresholdTuningPanel`）**一起移除**（決策 2）。
- 清理 `risk_list.js` 的 `updateThreshold()`、門檻校正相關呼叫（`/api/threshold-tuning` 若僅此處用到則前端停用、後端保留）。
> 注意：移除門檻拉桿後，風險清單改用固定門檻（沿用後端預設 0.5）。

### 6. 移除「What-if 全域決策模擬器」
**現況**：`roi_simulator.html:243–284`（D 區塊）+ `roi_simulator.js` 的 `runWhatif()`、`renderWhatifHeatmap()`、`populateWhatifRegions()`。
**做法（定案）**：整塊 D 區從前端移除，清理對應 JS（`runWhatif`/`renderWhatifHeatmap`/`populateWhatifRegions`）。後端 `/api/roi/whatif`（2992–3047）**保留不刪**（決策 3），僅前端停用。

### 7. AI 決策助理：對話框置中 + 引導問題移到對話框上方
**現況**：`ai_assistant.html` 為上下結構 —— 訊息區 `#aiChatLog`（上）→ composer-wrap（下，含引導問題 + 輸入框）。引導問題目前在輸入框「正上方」。
**做法**：
- 整個 `.ai-chat-shell` 置中（`max-width` + `margin:auto`，例如 760px 置中欄）。
- 引導問題 chips 移到**輸入框正上方、訊息區下方**置中呈現（目前已接近，主要調 CSS 對齊與置中）。
**檔案**：`ai_assistant.html`、`styles.css`（`.ai-chat-shell` / `.ai-composer-wrap`）。

### 8. 收益預測整合進「模型診斷與重訓」，可切換子頁
**現況**：`model-perf`（延遲模型診斷）與 `profit-prediction`（收益）是兩個獨立頁。
**做法**：
- 在「模型診斷與重訓」頁頂加**子頁切換 Tab**：`延遲預測模型 ⇄ 收益預測模型`。
- `延遲預測模型` = 現有 model_perf 內容；`收益預測模型` = 現有 profit_prediction 內容（RMSE/MAE/R²、特徵重要性、誤差表）。
- 移除 Manager 區的「收益預測」獨立 nav。
**檔案**：`model_perf.html`（加 tab 容器，內嵌 profit 區塊）、`model_perf.js` + `profit_prediction.js`（切換時各自載入）、`index.html`（移除 nav-profit-prediction）。

---

## 建議執行順序（風險由低到高）

| 順序 | 項目 | 風險 |
|---|---|---|
| 1 | 項目 5（移除預警拉桿）| 低 |
| 2 | 項目 1（罰金建議值提示）| 低 |
| 3 | 項目 2（刪 ROI 求解區）、項目 6（刪 What-if）| 低 |
| 4 | 項目 7（AI 對話框置中）| 低–中 |
| 5 | 項目 3（ROI 名單分頁）| 中（前後端）|
| 6 | 項目 8（收益併入模型診斷，子頁切換）| 中 |
| 7 | Sidebar 重組 | 中 |
| 8 | 項目 4（兩個最佳化器合併 + 統一資料源）| **高** |

---

## 後端「先隱藏前端、保留」清單（決策 3 / 4）
這些端點/檔案本次**不刪**，僅前端不再呼叫，待整體穩定後再評估清理：
- `/api/roi/optimize`（項目 2）
- `/api/roi/whatif`（項目 6）
- `/api/threshold-tuning`（項目 5，若僅風險清單用）
- `region_map.js` / `page-region-map` / `/api/regions` / `/api/geojson/*`（Sidebar，項目 4 決策）

---

*規劃定案。CSV 全站統一功能依指示暫不動。依「風險由低到高」順序實作。*
