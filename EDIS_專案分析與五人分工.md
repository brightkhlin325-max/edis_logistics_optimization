# EDIS 專案分析與五人分工

更新日期：2026-06-06  
專案名稱：DataCo 物流延遲預測與最佳化調度系統（EDIS）  
組員：Danny、紹光、Lisa、子堯、Bright

---

## 1. 專案核心分析

### 1.1 專案定位

本專案不是單純的資料科學預測模型，而是一個「預測加決策」的混合式供應鏈系統。核心邏輯如下：

1. 使用 DataCo 供應鏈資料集建立物流延遲風險預測模型。
2. 以模型輸出的延遲機率作為決策依據。
3. 將延遲機率、產品利潤、延遲罰款、升級運送成本與預算限制放入最佳化模型。
4. 輸出哪些訂單值得升級運送或優先調度，讓有限物流資源產生最大效益。

因此，最終展示時要強調：  
「模型不是只給準確率，而是把預測結果轉成可執行的物流決策。」

### 1.2 資料集理解

DataCo SMART SUPPLY CHAIN FOR BIG DATA ANALYSIS 主要包含供應鏈交易、訂單、配送、客戶、產品與物流相關欄位。資料適合用於：

- 物流延遲預測
- 訂單風險分層
- 運送模式與地區風險分析
- 供應鏈 KPI 儀表板
- 預測後的調度最佳化

本專案應以 `DataCoSupplyChainDataset.csv` 作為主要建模資料，並以 `DescriptionDataCoSupplyChain.csv` 作為欄位說明依據。`tokenized_access_logs.csv` 可作為延伸資料，但不建議列入 MVP，避免專案範圍過大。

### 1.3 AI 模型任務定義

模型任務為二元分類：

- 輸入 `X`：去識別化後的訂單與物流特徵，例如計劃運送天數、物流模式、目的地區域、客戶群體、產品價格、訂單數量、訂單日期特徵。
- 輸出 `Y`：是否延遲。
- 預測輸出：每筆訂單的延遲機率 `p_late`。

建議模型採用 XGBoost，原因是：

- 適合表格資料。
- 可處理非線性與特徵交互作用。
- 訓練速度快，適合課堂專案快速迭代。
- 可搭配 feature importance 或 SHAP 做可解釋性分析。

### 1.4 特徵工程重點

建議保留或轉換的特徵：

| 類型 | 建議欄位或衍生特徵 | 用途 |
|---|---|---|
| 時效特徵 | `Days for shipment (scheduled)` | 捕捉承諾天數與延遲風險 |
| 運送模式 | `Shipping Mode` | Standard、Second、First 等模式風險差異 |
| 地理特徵 | `Order Region`、`Order Country`、`Market` | 捕捉距離、跨境與區域物流差異 |
| 訂單特徵 | `Order Item Quantity`、`Product Price`、`Sales` | 捕捉訂單規模與商業價值 |
| 客戶特徵 | `Customer Segment` | 捕捉不同客群的訂單型態 |
| 時間特徵 | 訂單月份、星期幾、是否週末 | 捕捉季節性與週期性需求 |
| 類別編碼 | One-Hot、Frequency Encoding | 讓模型能處理類別欄位 |

### 1.5 必須避免的資料洩漏

本專案最容易被質疑的地方是資料洩漏。由於資料集中可能包含配送完成後才知道的欄位，若直接放入模型，準確率會虛高，但不符合「出貨前預測」的真實情境。

MVP 建議不要放入以下欄位作為模型輸入：

| 欄位類型 | 欄位例子 | 原因 |
|---|---|---|
| 目標本身 | `Late_delivery_risk` | 這是標籤，不能當特徵 |
| 結果狀態 | `Delivery Status` | 幾乎直接揭露是否延遲 |
| 實際配送天數 | `Days for shipping (real)` | 出貨完成後才知道 |
| 實際送達或運送完成日期 | 與實際完成時間相關欄位 | 預測當下不可得 |
| 高度衍生結果欄位 | 與延遲結果直接推導相關的欄位 | 可能造成不合理高分 |

在報告中可以主動說明：「我們只使用出貨前或訂單建立時可得的欄位，以避免資料洩漏。」

### 1.6 最佳化調度設計

模型輸出延遲機率後，最佳化引擎要解決的是資源配置問題。建議 MVP 使用簡化但清楚的 0/1 整數規劃：

- 決策變數：`x_i = 1` 代表第 `i` 筆訂單升級運送，`x_i = 0` 代表不升級。
- 目標函數：最大化預期淨效益。
- 預期效益：`p_late_i * delay_penalty_i - upgrade_cost_i`
- 約束條件：
  - 總升級成本不得超過物流預算。
  - 可選擇加入每日最大升級件數。
  - 可選擇加入特定區域或高價訂單優先權重。

可用口語化方式呈現：  
「不是所有高風險訂單都升級，而是在預算內挑出最值得升級的訂單。」

### 1.7 系統架構分析

專案可以拆成三層：

1. 安全資料管線  
   - 載入 DataCo CSV。
   - 去除姓名、地址、郵遞區號等敏感欄位。
   - 對必要 ID 進行雜湊。
   - 產出安全版訓練資料。

2. 地端核心計算  
   - XGBoost 延遲風險預測。
   - 模型評估與可解釋性分析。
   - PuLP 或 SciPy 最佳化求解。
   - 在本地執行，不依賴外部 API。

3. 決策儀表板與 RBAC  
   - Viewer：只能看模型指標與去識別化風險摘要。
   - Logistics_Manager：可調整預算並執行最佳化調度。
   - Viewer 呼叫 `/api/optimize` 必須回傳 403。
   - 前端也要鎖定按鈕，但真正安全邏輯必須在後端。

### 1.8 建議 MVP 範圍

為了讓五人分工可落地，建議 MVP 不要一次做太多功能。最小可展示版本應包含：

1. DataCo 資料載入與 EDA。
2. 敏感欄位移除與安全資料集輸出。
3. XGBoost 模型訓練與評估。
4. 延遲風險預測結果輸出。
5. 最佳化調度結果輸出。
6. FastAPI 三個主要端點：
   - `/api/metrics`
   - `/api/predict`
   - `/api/optimize`
7. 單頁 Dashboard：
   - KPI 區塊
   - 延遲風險列表
   - 預算輸入
   - 最佳化結果
   - Role Switcher
8. Viewer 與 Manager 權限差異展示。
9. 期末簡報與 demo script。

---

## 2. 現有專案狀態判讀

依據專案管理表，目前前期工作已有明確起點：

| 已有內容 | 狀態判讀 |
|---|---|
| 專案發想與主題討論 | 進行中或已接近完成 |
| 資料蒐集 | 已完成 |
| 競品分析 | 已完成 |
| 專案 Diagram 製作 | 已完成 |
| 簡報製作 | 已完成初版 |
| 數據集確認 | 已完成 |
| 專題方向與簡報修改 | 已完成或正在收斂 |

接下來分工不應再停留在 brainstorming，而應轉向「可展示 MVP 實作」與「報告論述強化」。

---

## 3. 五人角色分工總覽

### 分工原則

1. 每個人都要有清楚可交付成果。
2. 技術模組之間要有明確輸入輸出，避免互相等待。
3. 分工要對應期末展示：資料、模型、最佳化、系統、安全、簡報。
4. 每個工作包都要能被驗收。

### 建議角色分配

| 成員 | 主責角色 | 核心任務 | 主要交付物 |
|---|---|---|---|
| Danny | 專案整合與最佳化決策 | 系統架構、進度整合、最佳化模型、demo flow | 架構圖、optimizer、整合腳本、最終 demo 流程 |
| Lisa | 資料管線與隱私安全 | DataCo 清理、去識別化、特徵工程前處理 | `security_utils.py`、`data_pipeline.py`、安全版資料集 |
| 子堯 | ML 模型與評估 | XGBoost 訓練、評估、特徵重要性、模型輸出 | `model_pipeline.py`、模型檔、評估報告 |
| Bright | 後端 API 與 RBAC 測試 | FastAPI、權限檢查、403 測試、端點整合 | `app.py`、API 測試結果、權限驗證紀錄 |
| 紹光 | Dashboard、UI/UX 與簡報 | 前端儀表板、視覺化、角色切換、簡報與報告 | `index.html`、`styles.css`、demo 截圖、期末簡報 |

---

## 4. 個人詳細工作包

### 4.1 Danny：專案整合與最佳化決策

**定位**  
Danny 負責把整個專案從「模型預測」推進到「可執行決策」，並確保各模組能在期末 demo 串起來。

**任務清單**

| 任務 ID | 任務 | 輸入 | 輸出 |
|---|---|---|---|
| D-01 | 定義 MVP 範圍與系統流程 | 現有簡報、實作計畫 | MVP scope、系統流程圖 |
| D-02 | 設計最佳化問題 | 模型預測機率、訂單價值、預算 | 目標函數與限制式 |
| D-03 | 實作 `optimizer.py` | 預測結果 CSV | 最佳化推薦訂單清單 |
| D-04 | 整合模型輸出與最佳化輸入 | 子堯模型結果 | `prediction_with_decision.csv` |
| D-05 | 設計 demo script | API、Dashboard、簡報 | 3 至 5 分鐘展示流程 |

**驗收標準**

- 能用固定測試資料跑出「建議升級運送的訂單」。
- 每筆建議要有原因，例如高延遲風險、高預期損失、在預算內。
- 能清楚說明最佳化不是單純排序，而是在限制條件下選擇最佳組合。

---

### 4.2 Lisa：資料管線與隱私安全

**定位**  
Lisa 負責讓資料從原始 DataCo CSV 變成安全、乾淨、可建模的資料。這個角色是模型與安全架構的基礎。

**任務清單**

| 任務 ID | 任務 | 輸入 | 輸出 |
|---|---|---|---|
| L-01 | 建立欄位盤點表 | DataCo CSV、欄位說明 | 欄位分類表 |
| L-02 | 標記敏感欄位與不可用欄位 | 原始欄位 | `sensitive_columns`、`leakage_columns` |
| L-03 | 實作 `security_utils.py` | 原始資料列 | 去識別化資料列 |
| L-04 | 實作 `data_pipeline.py` | DataCo CSV | 安全版資料集 |
| L-05 | 產出 EDA 摘要 | 清理後資料 | 缺失值、類別分布、延遲比例 |

**驗收標準**

- 原始姓名、地址、郵遞區號不得進入訓練資料。
- `Late_delivery_risk` 只能作為標籤，不能留在特徵矩陣。
- 產出一份乾淨的 `train_ready.csv`，子堯可直接使用。
- EDA 至少包含延遲比例、Shipping Mode 分布、地區延遲風險、訂單價值分布。

---

### 4.3 子堯：ML 模型與評估

**定位**  
子堯負責讓延遲預測模型可信、可解釋、可被最佳化模組使用。

**任務清單**

| 任務 ID | 任務 | 輸入 | 輸出 |
|---|---|---|---|
| Z-01 | 建立 baseline model | `train_ready.csv` | Logistic Regression 或 Dummy baseline |
| Z-02 | 訓練 XGBoost | 安全特徵矩陣 | XGBoost model |
| Z-03 | 評估模型 | validation set | ROC-AUC、PR-AUC、F1、混淆矩陣 |
| Z-04 | 調整 threshold | 預測機率、商業成本 | 建議決策閾值 |
| Z-05 | 輸出預測結果 | 測試訂單 | `predictions.csv` |
| Z-06 | 可解釋性分析 | 訓練後模型 | feature importance 或 SHAP 圖 |

**驗收標準**

- 有 baseline 與 XGBoost 比較。
- 評估不只放 accuracy，至少要有 ROC-AUC、Recall、Precision、F1。
- 明確說明資料洩漏欄位已排除。
- 產出的 `predictions.csv` 至少包含 `order_id_hash`、`p_late`、`risk_bucket`、`expected_penalty`。

---

### 4.4 Bright：後端 API 與 RBAC 測試

**定位**  
Bright 負責把模型與最佳化功能包成後端服務，並確保 Viewer 與 Manager 權限差異真的在後端成立。

**任務清單**

| 任務 ID | 任務 | 輸入 | 輸出 |
|---|---|---|---|
| B-01 | 建立 FastAPI 專案骨架 | 實作計畫 | `app.py` |
| B-02 | 實作 `/api/metrics` | 模型評估結果 | 公開 KPI JSON |
| B-03 | 實作 `/api/predict` | 安全測試資料 | 延遲風險 JSON |
| B-04 | 實作 `/api/optimize` | 預測結果、預算 | 最佳化結果 JSON |
| B-05 | 實作角色驗證 | API key 或 role header | Viewer、Manager 權限控制 |
| B-06 | 撰寫安全測試 | Viewer 呼叫 optimize | 403 測試紀錄 |

**驗收標準**

- Viewer 呼叫 `/api/optimize` 必須回傳 403。
- Manager 呼叫 `/api/optimize` 能回傳最佳化調度結果。
- `/api/predict` 回傳資料必須是去識別化結果。
- 需保留一份 API demo 指令，例如 curl 或 Postman 截圖。

---

### 4.5 紹光：Dashboard、UI/UX 與簡報

**定位**  
紹光負責讓專案成果可被看懂、可被展示、可被評分者快速理解。

**任務清單**

| 任務 ID | 任務 | 輸入 | 輸出 |
|---|---|---|---|
| S-01 | 設計 Dashboard layout | 系統流程、API 回傳格式 | Wireframe |
| S-02 | 實作 KPI 卡片 | `/api/metrics` | 模型效能區塊 |
| S-03 | 實作風險訂單表 | `/api/predict` | 延遲風險列表 |
| S-04 | 實作預算與最佳化區塊 | `/api/optimize` | 調度推薦結果 |
| S-05 | 實作 Role Switcher | Viewer、Manager role | 權限視覺差異 |
| S-06 | 製作期末簡報與 demo 截圖 | 全組成果 | 最終簡報檔 |

**驗收標準**

- Viewer 視角看不到最佳化按鈕或按鈕不可點擊。
- Manager 視角可以輸入預算並看到最佳化結果。
- Dashboard 至少有三個 KPI：延遲率、模型 AUC 或 F1、高風險訂單數。
- 簡報中要有一頁清楚展示「預測到決策」的完整流程。

---

## 5. RACI 矩陣

說明：  
R = Responsible，實際執行  
A = Accountable，最後負責  
C = Consulted，需提供意見  
I = Informed，需同步進度

| 工作項目 | Danny | Lisa | 子堯 | Bright | 紹光 |
|---|---|---|---|---|---|
| 專案範圍與架構定義 | A/R | C | C | C | C |
| Kaggle 資料理解與 EDA | C | A/R | C | I | I |
| 敏感欄位移除與去識別化 | C | A/R | C | C | I |
| 特徵工程 | C | A/R | R | I | I |
| XGBoost 模型訓練 | I | C | A/R | I | I |
| 模型評估與可解釋性 | C | C | A/R | I | C |
| 最佳化調度模型 | A/R | I | C | C | C |
| FastAPI 後端 | C | I | C | A/R | C |
| RBAC 與 403 驗證 | C | C | I | A/R | R |
| Dashboard UI | C | I | I | C | A/R |
| Demo script | A/R | I | C | C | R |
| 期末簡報 | A | C | C | C | R |

---

## 6. 建議里程碑

### Milestone 1：資料與問題定義完成

**目標**：把資料處理與建模邊界定義清楚。

交付物：

- 欄位分類表。
- 敏感欄位清單。
- 資料洩漏欄位清單。
- EDA 初版圖表。
- MVP scope。

負責人：

- Lisa 主責資料。
- Danny 主責 scope。
- 子堯確認建模可用欄位。

### Milestone 2：模型與最佳化核心完成

**目標**：讓系統有可運作的 AI 預測與決策輸出。

交付物：

- `train_ready.csv`
- `model_pipeline.py`
- 模型評估結果
- `predictions.csv`
- `optimizer.py`
- 最佳化推薦結果

負責人：

- 子堯主責模型。
- Danny 主責最佳化。
- Lisa 支援資料修正。

### Milestone 3：API 與 Dashboard 串接完成

**目標**：讓前後端可以完成展示流程。

交付物：

- `/api/metrics`
- `/api/predict`
- `/api/optimize`
- RBAC 測試
- Dashboard 初版
- Viewer 與 Manager 視角展示

負責人：

- Bright 主責 API。
- 紹光主責 UI。
- Danny 協調 API 與 optimizer 串接。

### Milestone 4：簡報、測試與最終 Demo

**目標**：完成可以穩定展示的期末版本。

交付物：

- 最終簡報。
- Demo script。
- 測試結果截圖。
- 系統流程圖。
- 模型與最佳化結果說明。
- 權限控制展示。

負責人：

- 紹光主責簡報。
- Danny 主責 demo flow。
- Bright 主責安全測試截圖。
- 子堯主責模型結果說明。
- Lisa 主責資料安全說明。

---

## 7. 建議主任務清單

| 任務 ID | 任務名稱 | 負責人 | 優先權 | 依賴 |
|---|---|---|---|---|
| TASK-101 | 確認 MVP scope 與 demo 流程 | Danny | High | 無 |
| TASK-102 | DataCo 欄位盤點與資料字典整理 | Lisa | High | 無 |
| TASK-103 | 敏感欄位與資料洩漏欄位清單 | Lisa | High | TASK-102 |
| TASK-104 | EDA 圖表與延遲風險初步洞察 | Lisa | High | TASK-102 |
| TASK-105 | 去識別化模組 `security_utils.py` | Lisa | High | TASK-103 |
| TASK-106 | 資料前處理管線 `data_pipeline.py` | Lisa | High | TASK-105 |
| TASK-107 | Baseline model | 子堯 | Medium | TASK-106 |
| TASK-108 | XGBoost model | 子堯 | High | TASK-107 |
| TASK-109 | 模型評估與 feature importance | 子堯 | High | TASK-108 |
| TASK-110 | 輸出 `predictions.csv` | 子堯 | High | TASK-108 |
| TASK-111 | 最佳化問題公式化 | Danny | High | TASK-110 |
| TASK-112 | 實作 `optimizer.py` | Danny | High | TASK-111 |
| TASK-113 | FastAPI 骨架與 `/api/metrics` | Bright | High | TASK-109 |
| TASK-114 | `/api/predict` 串接模型輸出 | Bright | High | TASK-110 |
| TASK-115 | `/api/optimize` 串接最佳化結果 | Bright | High | TASK-112 |
| TASK-116 | RBAC role header 與 403 測試 | Bright | High | TASK-115 |
| TASK-117 | Dashboard wireframe | 紹光 | Medium | TASK-101 |
| TASK-118 | Dashboard API 串接與 Role Switcher | 紹光 | High | TASK-113 到 TASK-116 |
| TASK-119 | 最終簡報與 Demo 截圖 | 紹光 | High | TASK-118 |
| TASK-120 | Final integration rehearsal | 全員 | High | 全部核心任務 |

---

## 8. 每位成員簡報負責段落

| 成員 | 建議簡報段落 | 說明重點 |
|---|---|---|
| Danny | 專案定位、系統架構、最佳化決策 | 為什麼不是只做預測，而是做可執行調度 |
| Lisa | 資料集、EDA、去識別化 | 資料來源、欄位處理、隱私保護 |
| 子堯 | 模型方法與評估 | XGBoost、指標、資料洩漏控制、特徵重要性 |
| Bright | 後端 API 與 RBAC | API 設計、Viewer/Manager 權限、403 驗證 |
| 紹光 | Dashboard 與 Demo | UI 流程、角色切換、最終展示情境 |

---

## 9. 最終展示建議腳本

1. 先講痛點：物流資源有限，不能所有訂單都升級，企業需要知道哪些訂單最值得處理。
2. 展示資料：DataCo 供應鏈資料含訂單、客戶、產品、物流資訊。
3. 展示安全管線：敏感欄位在進入模型前已移除或雜湊。
4. 展示模型：XGBoost 預測每筆訂單延遲機率。
5. 展示最佳化：系統在預算限制下推薦最值得升級的訂單。
6. 展示權限：Viewer 只能看指標，Manager 才能執行最佳化。
7. 收尾：EDIS 把 AI 預測轉化成可執行的供應鏈決策，同時保留資料安全與角色控管。

---

## 10. 主要風險與處理方式

| 風險 | 影響 | 處理方式 |
|---|---|---|
| 資料洩漏導致模型分數虛高 | 報告可信度下降 | 明確排除結果欄位，主動在簡報說明 |
| 前後端串接太晚 | Demo 不穩 | API 回傳格式先定義，前端可先用 mock data |
| 最佳化模型太複雜 | 實作延遲 | MVP 用簡化 0/1 budget optimization |
| RBAC 只做前端鎖定 | 安全性不足 | 後端也要實作權限判斷與 403 |
| EDA 與模型敘事不一致 | 簡報邏輯斷裂 | Lisa 與子堯共用同一份欄位清單 |
| 組員產出格式不一 | 整合成本高 | 統一輸出 CSV 欄位與 API JSON schema |

---

## 11. 建議檔案結構

```text
edis_logistics_optimization/
  core/
    security_utils.py
    data_pipeline.py
    model_pipeline.py
    optimizer.py
  data/
    raw/
      DataCoSupplyChainDataset.csv
    processed/
      train_ready.csv
      predictions.csv
      optimization_result.csv
  static/
    index.html
    styles.css
    app.js
  reports/
    figures/
    model_report.md
    demo_script.md
  app.py
  README.md
```

---

## 12. API 回傳格式建議

### `/api/metrics`

```json
{
  "roc_auc": 0.91,
  "f1": 0.84,
  "recall": 0.86,
  "precision": 0.82,
  "late_rate": 0.54,
  "high_risk_orders": 128
}
```

### `/api/predict`

```json
[
  {
    "order_id_hash": "a8f3...",
    "shipping_mode": "Standard Class",
    "order_region": "Western Europe",
    "p_late": 0.82,
    "risk_bucket": "High"
  }
]
```

### `/api/optimize`

```json
{
  "budget": 5000,
  "selected_orders": [
    {
      "order_id_hash": "a8f3...",
      "p_late": 0.82,
      "upgrade_cost": 120,
      "expected_saving": 350,
      "decision": "Upgrade"
    }
  ],
  "total_cost": 4920,
  "expected_total_saving": 14800
}
```

---

## 13. 參考資料

- Kaggle DataCo SMART SUPPLY CHAIN FOR BIG DATA ANALYSIS：`https://www.kaggle.com/datasets/shashwatwork/dataco-smart-supply-chain-for-big-data-analysis`
- Mendeley Data 原始資料集 DOI：`10.17632/8gx2fvg2k6.5`
- 專案文件：`ai_model_specification.md`
- 專案文件：`implementation_plan.md`
- 專案簡報：`DataCo 物流延遲預測與最佳化調度系統 (EDIS).pdf`
- 專案管理表：`專案管理表.xlsx`
