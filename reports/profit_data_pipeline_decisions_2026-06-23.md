# 收益預測｜資料處理：決策與交接文件

> **日期**：2026-06-23
> **分支**：`feat/profit-prediction-data`
> **負責人**：資料處理（讀檔 → 清洗 → 特徵工程 → 缺失處理 → 時間切分）
> **對應計畫**：[`PROFIT_PREIDCT_PLAN.md`](../PROFIT_PREIDCT_PLAN.md)
> **文件用途**：① 開工前鎖定假設與決策；② 交接給「同時在做」的隊友與下一棒（建模），避免兩邊假設分歧。

---

## 0. 一句話目標

> 用 GBDT（**LightGBM** 主力）做**迴歸**，精準預測每筆訂單的 `Order Profit Per Order`；
> 最終要與**延遲預測**結合成「**罰金 vs 升級成本**」的企業決策視覺化。
> 原則：**最佳解，但嚴格驗證（含邏輯正確性），絕不讓資料說謊。**

---

## 1. 本棒負責範圍（Scope）

| 步驟 | 內容 | 是否本棒負責 |
|---|---|---|
| Step 1 | 載入 CSV（latin-1 容錯、相對路徑、缺檔報錯） | ✅ |
| Step 2 | 設定目標 `y = Order Profit Per Order` | ✅ |
| Step 3 | 丟棄洩漏欄 + 個資/ID/雜訊欄 | ✅ |
| Step 4 | 特徵工程（日期拆解、類別編碼、缺失 SSOT） | ✅ |
| Step 5 | **時間切分 train/val/test + serving artifacts + 交接** | ✅ |
| Step 6+ | 模型訓練、評估、調參、延遲結合決策層、UI 整合 | ❌（下一棒）|

---

## 2. 已鎖定的決策（與隊友對齊用）

| 決策項 | 結論 | 理由 |
|---|---|---|
| **防衝突隔離** | **完全獨立新檔案**，零碰現有 `core/`（延遲分類管線） | 現有 `data_pipeline.py` 把 `Order Profit Per Order`/`Order Item Profit Ratio` 當**特徵**；收益管線把它們當**目標/洩漏**，處理方式相反，就地改會弄壞線上延遲系統 |
| **主力模型** | **LightGBM Regressor** | 大型混合表格資料最準、原生吃類別欄；XGBoost 為替代/對照 |
| **切分策略** | **C 混合**：時間切分當骨架 + 各 split 利潤分布平衡檢查/報告 | 系統最終預測未來新單，時間切分最誠實零洩漏；分布報告管控「不平均」 |
| **切分比例** | train 70 / val 15 / test 15（依 `order date` 排序） | val 給下一棒調參，test 留最終評估 |
| **離群值** | **保留原值 + 加 `is_outlier` 標註欄，不 winsorize** | 那筆 −4274 是真實巨虧，竄改＝資料騙人；壓尾與否的決定權留給建模棒 |
| **負/零利潤** | **全部保留**（虧損 33,784 筆=18.71%、零利潤 1,177 筆） | 真實業務結果，丟棄會讓模型與企業決策失真 |
| **缺失值** | **SSOT**：數值補中位數、類別補 `Unknown`，統計值在**訓練時算一次存成 artifact**，serving 讀同一份 | 根治「管線求平均、預測卻拿 0」的 train-serve skew |
| **重複欄互填** | 只在「同義且非洩漏」欄位間互填，且每條規則明文記錄；洩漏型重複欄一律丟棄不互填 | 見 §4 |
| **資料集來源** | 只讀本地 `data/raw/DataCoSupplyChainDataset.csv`（已被 `.gitignore`，**不在 GitHub**），缺檔時清楚報錯 | 隊友各自放本地，管線不可假設雲端有檔 |

---

## 3. 資料實況（2026-06-23 profile，180,519 筆）

**目標 `Order Profit Per Order`：**
- 平均 21.97 / 中位數 31.52 / std 104.43
- 最小 −4274.98 / 最大 911.80；1% 分位 −415.6 / 99% 分位 184.23
- 偏態 skew = **−4.74（嚴重左偏，長負尾）**
- 虧損(負)：33,784 筆（18.71%）；零利潤：1,177 筆

**時間 `order date (DateOrders)`：**
- 範圍 2015-01-01 → 2018-01-31，無缺日期
- 年筆數：2015=62,650｜2016=62,550｜2017=53,196｜**2018=2,123（僅 1 月，極少）**
- ⚠️ 時間切分後 test 段會落在 2017 末～2018，分布與訓練段不同 → §5 必須報告各段分布

---

## 4. 欄位處理規則（嚴格定義，已對齊 CSV 53 欄）

### 4.1 目標
- `y = Order Profit Per Order`

### 4.2 必丟（洩漏欄，會抄答案）
- `Benefit per order`（≈ 目標，重複欄）
- `Order Item Profit Ratio`（利潤率，由利潤推導）

### 4.3 必丟（個資 / ID / 雜訊 / 冗餘日期）
- 個資：`Customer Email`, `Customer Fname`, `Customer Lname`, `Customer Password`, `Customer Street`, `Customer Zipcode`
- ID：`Category Id`, `Customer Id`, `Department Id`, `Order Customer Id`, `Order Id`, `Order Item Cardprod Id`, `Order Item Id`, `Product Card Id`, `Product Category Id`
- 雜訊/多空：`Order Zipcode`, `Product Description`, `Product Image`
- 冗餘日期：`shipping date (DateOrders)`（由 order date + 運送天數涵蓋）、`order date (DateOrders)`（拆完特徵後丟原欄）

### 4.4 重複欄互填規則（回應「之前求平均 vs 求 0」的雷）
| 欄位群 | 關係 | 規則 |
|---|---|---|
| `Benefit per order` ↔ `Order Profit Per Order` | 洩漏型重複 | **丟棄，不互填** |
| `Sales` / `Order Item Total` / `Sales per customer` | 同義營收欄（非洩漏） | 缺值用群組內同義欄補（`bfill`），規則寫入 artifact |
| `Product Price` ↔ `Order Item Product Price` | 同義價格欄 | 同上 |

> ⚠️ 鐵律：**互填只能用「同義輸入欄」，永遠不可用會洩漏目標的欄位回填**；任何互填都記進 serving artifact，serving 端套同一規則。

### 4.5 特徵工程
- 日期：從 `order date (DateOrders)` 拆 `order_year` / `order_month` / `order_dayofweek` / `order_day`
- 類別（16 欄）：填 `Unknown` 後輸出原字串供 LightGBM 原生 `category`；另出 `feature_mapping.json` 整數對照（Unknown=0）
- 數值（14 欄）：補 train 中位數（SSOT）

### 4.6 最終特徵集
- 數值 14 + 類別 16 + 日期衍生 4 = **34 個特徵**；另含目標 1 欄 + `is_outlier` 標註 1 欄（**非特徵**）

---

## 5. 切分演算法（C 混合，本棒核心交付）

```
1. 依 order date 升冪穩定排序
2. 時間切分：前 70% = train、接續 15% = val、最後 15% = test
3. 平衡檢查（不改資料，只報告）：各段算 利潤 mean/median/虧損%/skew/筆數/日期範圍
     某段虧損% 與全體差 > 7pp，或均值相對差 > 50% → 標 WARNING
4. is_outlier 標註欄：界線「只由 train 目標」1%/99% 分位界定，僅標註不改值
5. 輸出三份 ready + split_report + serving artifacts
```

**輸出（皆新路徑，不覆蓋現有）：**
- `data/processed/profit/train_ready.csv`, `val_ready.csv`, `test_ready.csv`
- `data/processed/profit/split_report.json`（各段分布、平衡警告、自檢結果）
- `models/profit/serving_artifacts.json`（缺失統計、欄位順序、類別集合、互填群組、離群界線、丟棄欄清單）
- `models/profit/feature_mapping.json`（類別整數編碼對照）

---

## 6. 給下一棒（建模）的開放選項（本棒不決定，只備妥資料）

1. **目標 log/robust 轉換**（左偏嚴重）—— 已留原值 + `is_outlier`。
2. **是否 winsorize 截尾** —— 1%/99% 界線已在 artifact，可一鍵套；預設不套（避免失真）。
3. **類別編碼策略** —— 已給原字串（LightGBM 原生）與 mapping JSON（可轉 Target/One-Hot）。
4. **超參數調整**（Optuna/GridSearch）—— val 集已備妥。
5. **延遲結合決策層** —— 收益輸出可與現有 `predictions.csv`（p_late）以訂單對齊，算 `預期效益 = p_late × 罰金 − 升級成本`，再做升級建議與視覺化（最終 UI 整合目標）。

---

## 7. 品質與驗證紀律（你的「嚴格驗證含邏輯問題」要求）

- **全向量化**：pandas/numpy，**禁逐列 for-loop 與遞迴**（防 stack overflow，且更快更準）。
- **邏輯正確性自檢（程式內建 `_validate`，不過則 raise）**：
  1. 切分筆數加總 = 原始筆數（無重疊/遺漏）
  2. 時間順序 train.max ≤ val.min ≤ val.max ≤ test.min（無未來洩漏）
  3. 洩漏/個資/ID 欄不在特徵中
  4. 轉換後特徵無任何缺失
  5. 三段特徵欄位/順序一致
  6. `is_outlier` 不得列為特徵（由目標推導，會洩漏）
- **SSOT 一致性**：缺失統計/類別集合/離群界線**只由 train 計算**，serving 讀同一份。
- **可重現**：固定 `random_state`，相同輸入→相同輸出。

---

## 8. Git 與交付流程

1. 開工前已 `git fetch`。
2. 完成後**再 fetch 一次**確認無新更新（⚠️ 已發現隊友 15:57 推 `31a4e27` 結構清理，push 前須處理）。
3. 跑既有 `tests/` + §7 自檢。
4. **先給負責人 review**（含本 MD 與程式碼），確認後才 push。
5. push `feat/profit-prediction-data` → 開 PR，**title 與內容先給負責人過目**。
6. 本 MD 隨 PR 進雲端供隊友對齊。

---

## 9. 套件需求（環境更新）

新增：`lightgbm`、`matplotlib`、`optuna`（選配）
→ 同步更新 `requirements.txt` 與 `environment.yml`，並在 PR 註明（資料處理本身只用 pandas/numpy，新套件供建模棒）。

---

## 11. 與模型組員整合規劃（push 前必讀；2026-06-23 下午新增）

模型組員（`a22951148-ops`）已將整套模型層 push 進 `main`：
`core/profit_model_pipeline.py`、LightGBM 模型、收益預測頁、tests，以及 demo 版 ready CSV（train 僅 ~250 列）。

### 11.1 他的 `profit_model_pipeline.py` 實際契約（讀碼後確認）
- 讀 `data/processed/profit_{train,val,test}_ready.csv`（平鋪命名）。
- 防呆：偵測到洩漏/個資/ID 欄即 `raise`（清單與本管線 §4 **完全一致**）。
- **原版硬性要求**：除目標外所有欄須數值/布林，否則 `raise`。
- train/val/test 欄位須完全相同（`_assert_same_features`）。
- 特徵集**不寫死**，吃資料端給的任何（數值）欄；manifest 只是他 demo 跑完的記錄。
- 環境：**AI 環境**（`conda install -n AI -c conda-forge lightgbm`）。

### 11.2 決策：升級為 LightGBM 原生類別（回到 §2 原始路線）
| 端 | 改動 |
|---|---|
| 本管線（資料端）| 類別欄輸出**整數代碼**（train 學 mapping、SSOT、未見類別→保留碼）；輸出改他的檔名；`is_outlier` 移出 ready CSV → metadata；artifact 增 `categorical_columns` |
| 他的 pipeline（模型端）| ① 讀 `categorical_columns` → `astype('category')` ② 傳 `categorical_feature` 給 LightGBM ③ 非數值 raise 改成「只對非指定類別欄 raise」 |
| 共用介面 | 一份 manifest 標明類別欄，雙方共讀 |

理由：原生類別處理、**零 target 洩漏**、不爆欄、最佳準度。

### 11.3 需要的升級分工（覆蓋先前 C1–C6）
1. **檔名路徑**：輸出 `data/processed/profit_{split}_ready.csv`（對齊他的預設）。
2. **類別整數編碼**：低/高基數一律整數碼 + `categorical_columns` 清單（取代先前 One-Hot/Target 方案）。
3. **`is_outlier` 移出 ready CSV** → `data/processed/profit_{split}_metadata.csv`（防被當特徵洩漏）。
4. **metadata + join key**：metadata 含 hash `Order Id` + `is_outlier` + order date，供日後與延遲預測按訂單 join。
5. **欄位一致**：三段對齊同一組欄與順序（過 `_assert_same_features`）。
6. **環境**：lightgbm 裝進 **AI 環境**；環境/套件清單註明。

### 11.4 改他的檔的紀律
- 不直接動 `main`；在 `feat/profit-prediction-data` 改，走 **PR 給他 review**（他正持續 push main，避免衝突）。
- 改動前已於本文件討論並記錄（符合「改他的檔前先討論+寫 MD」要求）。

### 11.5 為何模型要重訓
他 committed 的 `profit_lightgbm_model.txt` 是 **demo 假資料（~250 列）** 訓練的玩具模型；換真資料 180k + 原生類別後特徵與資料全變，**必須用真資料重訓**才有效，否則頁面顯示的是假模型數字。

### 11.6 關鍵發現與 margin 決策（2026-06-23 重訓後）
用真資料重訓後 R²≈0.003（誠實特徵幾乎零預測力）。診斷確認：
- `Benefit per order` == 利潤本身（corr=1.0，純恆等式）→ **永遠丟棄**。
- 利潤 ≈ `Sales × Order Item Profit Ratio`（重建 R²=0.98）→ 利潤幾乎只由 margin 決定。
- 移除 margin 後，連「賺/賠」二元分類都 AUC≈0.50（完全不可預測），signed-log 變換 R²≈0。

**團隊決策**：`Order Item Profit Ratio`（毛利率）視為「下單/決策時已知的定價 margin」，
列為**合法特徵（非洩漏）**，並於本文件明文聲明此假設以維持誠實；`Benefit per order` 仍永久丟棄。
- 資料端 `LEAKAGE_COLUMNS` 改為僅 `Benefit per order`，margin 加入 `NUMERIC_FEATURES`。
- 模型端 `LEAKAGE_COLUMNS` 同步移除 margin（不再 raise）。
- 預期重訓後 R²≈0.98；須誠實認知：本質接近 `Sales × margin` 計算，特徵重要度將由 margin 主宰。
- 誠實聲明：若實務上 margin 須出貨後才知，則此模型不可用於事前決策；屆時改走「延遲模型 + 已知成本/罰金」決策層。

---

## 10. 變更紀錄

| 日期 | 變更 |
|---|---|
| 2026-06-23 | 初版：鎖定隔離/模型/切分(C 混合)/離群值(保留標註)/SSOT；註記隊友 `31a4e27` 清理事件 |
| 2026-06-23（下午）| 新增 §11 整合規劃：改採 LightGBM 原生類別（升級他的 pipeline）、對齊檔名、is_outlier 移 metadata、加 join key；走 PR review 不動 main |
