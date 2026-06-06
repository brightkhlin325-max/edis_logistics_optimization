# FastAPI 後端與 RBAC 權限管理實作計畫

此計畫書說明如何為 **DataCo 物流延遲預測與最佳化調度系統（EDIS）** 建立後端 API。

## 預計變更

我們將在專案根目錄下建立核心的後端應用程式。

### 後端 API

#### [NEW] [app.py](file:///C:/Users/lincf/.gemini/antigravity/scratch/edis_logistics_optimization/app.py)
實作 FastAPI 應用程式，包含：
- 基於角色的權限控管（RBAC）中介軟體或依賴注入（利用 Request Header 如 `X-User-Role: Viewer` 或 `X-User-Role: Manager` 判斷）。
- `/api/metrics` 端點：回傳機器學習模型的效能指標（如 ROC-AUC、F1-score 等）。
- `/api/predict` 端點：回傳去識別化後的物流延遲風險預測清單（包含延遲機率與風險分級）。
- `/api/optimize` 端點：回傳物流調度最佳化推薦清單。此端點會驗證權限，若角色為 `Viewer` 則回傳 HTTP 403 Forbidden。

## 驗證計畫

### 手動測試
1. 使用 Uvicorn 啟動 FastAPI 伺服器：
   `& "D:\Bright\Anaconda\Scripts\python.exe" -m uvicorn app:app --reload`
2. 使用 PowerShell 的 `Invoke-RestMethod` 或 `curl` 測試 API 端點：
   - 測試 `/api/metrics`
   - 測試 `/api/predict`
   - 攜帶 `X-User-Role: Manager` 測試 `/api/optimize`（預期回傳 200 OK 與最佳化結果）
   - 攜帶 `X-User-Role: Viewer` 測試 `/api/optimize`（預期回傳 403 Forbidden 拒絕存取）
