# 上傳分流 / 累積訓練資料 / 重訓升級 — 程式碼邏輯說明（乙）

> 本文件說明「讓上傳資料能安全地餵進訓練」這個 PR（乙）的每一處改動的邏輯與原因。
> 對應分支：`feat/training-data-pipeline`（疊在甲 `fix/data-consistency-monthly` 之上）

## 背景：為什麼要做

現況（乙之前）：
- 上傳 `/api/upload` 的資料**只拿來預測**、且**覆寫** predictions.csv，用完即丟，**永遠不進訓練**。
- 重訓 `/api/retrain` 只讀**靜態原始檔**做特徵刪除 → 模型**不會隨新資料進步**（單薄）。
- 所以「上傳髒資料把模型搞壞」的情境根本不存在——因為上傳不進訓練。

乙的目標：**讓上傳的新資料能真正餵進訓練，且安全（不被髒資料污染、可一鍵放棄）。**

## 設計：上傳分兩條路

| 路徑 | 端點 | 用途 | 需求 | 寫到哪 |
|---|---|---|---|---|
| 只預測 | `POST /api/upload`（現有） | 看這批訂單的延遲預測 | 不需標籤 | predictions.csv / session 檔（覆寫） |
| **進訓練** | `POST /api/upload-training`（**新**） | 累積供未來重訓 | **含標籤 + 過驗證 + Manager** | `data/training_store/accumulated.csv`（**append 累積**） |

## 改動明細

| 檔案 | 改動 | 原因 |
|---|---|---|
| `core/training_store.py` | **新增**：`append_training_csv()` / `build_combined_training_file()` | 累積入庫 + 合併供重訓 |
| `app.py` | 新增 `POST /api/upload-training`（Manager 限定） | 上傳分流的「進訓練」路 |
| `core/retrainer.py` | `run()` 合併「原始 + 累積」當訓練來源 | 模型才會隨新資料進步 |
| `data/training_store/.gitkeep` | 新增資料夾佔位（accumulated.csv 被 .gitignore） | 訓練庫位置 |

## 細節邏輯

### 1. 入庫 `append_training_csv`（安全閘門）
1. **C 驗證**：重用 `validate_upload_columns`（重複欄 / 是否像訂單資料）→ 不過 raise `UploadValidationError`（400）。
2. **必須有標籤**：找不到 `Late_delivery_risk` → raise `TrainingDataError`（400）。沒有真實答案就無法學習。
3. **去 PII（at-rest 安全）**：`DeIdentifier.drop_sensitive_columns()` 移除客戶姓名/Email 等敏感欄；**Order Id 不在此雜湊**，留待重訓時由 `DataPipeline` 統一去識別化，避免欄位重名衝突。
4. **append 累積**：讀舊 + `concat` + 寫回（容忍不同上傳的欄位差異），而非覆蓋。

### 2. 合併重訓 `build_combined_training_file` + retrainer
- 重訓時把 `原始檔 + accumulated.csv` 合併成一個暫存檔，餵給 `DataPipeline`。
- `DataPipeline` 內部會統一去識別化、特徵工程（與服務端 SSOT 一致，承甲）。
- 新模型仍進 **temp → adopt/discard**（既有機制）：比對新舊指標，由 Manager 決定保留或捨棄。

### 3. 安全閥（為什麼「壞不了」）
- 沒標籤 / 沒過驗證的資料 **進不了訓練庫**（400）。
- PII 不落地（入庫即去除）。
- 就算累積資料讓新模型變差，**adopt/discard 一鍵放棄**，現有模型不受影響。

## 驗證結果（單元 8/8 PASS）
- append 累積（total 2→4）、PII（Customer Fname）已去除、標籤保留。
- 缺標籤 → `TrainingDataError`；`foo,bar,baz` → `UploadValidationError`（皆 400）。
- 合併 raw+累積筆數正確；`/api/upload-training` 端點註冊成功。

## 後續 / 未做
- 前端目前未加「上傳訓練資料」按鈕（API 已可用，可後續加 UI）。
- 可加：訓練庫的去重、資料品質報告、累積量門檻才允許重訓。
