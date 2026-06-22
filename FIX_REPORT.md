# EDIS 修正報告：嚴格單元驗證與後端問題修復

> 日期：2026-06-22
> 分支：`main`
> 範圍：問題 1、2、4 + Actionable Insight banner 算法修正（問題 3 PuLP 經討論後暫不處理）

---

## 摘要

| # | 問題 | 嚴重度 | 狀態 |
|---|------|:---:|:---:|
| 1 | `starlette`/`httpx` 版本不相容，嚴格測試無法執行 | 🔴 高 | ✅ 已修 |
| 2 | `app.py` 使用已棄用的 `@app.on_event("startup")` | 🟠 中 | ✅ 已修 |
| 4 | 測試覆蓋淺、斷言過寬 | 🟡 中 | ✅ 已修 |
| ＋ | Actionable Insight banner「淨節省」算法高估 | 🟡 中 | ✅ 已修 |
| 3 | PuLP 舊式 API 棄用警告 | 🟠 中 | ⏸️ 暫不處理（見文末） |

驗證結果：**嚴格模式（`pytest -W error`）下 20 項測試全數通過**（僅放行第三方 PuLP 警告）。

另外併入 `fix/resolve-merge-conflicts` 分支的 `bd2cb5e`，移除 `static/index.html` 中殘留的 8 處 git 合併衝突標記與重複區塊（該分支先前未合回 main）。

---

## 問題 1 — starlette / httpx 相容性（嚴格模式阻斷）

**現象**
`fastapi.testclient.TestClient` 底層的 `starlette 1.3.1` 已棄用 `httpx`，要求改用 `httpx2`。環境只裝了 `httpx 0.28.1`，因此：
- 一般測試 → 僅警告，可通過
- 嚴格測試（`-W error`）→ 警告升級為錯誤，**收集階段即失敗**（`ModuleNotFoundError: No module named 'httpx2'`）

**修正**
於 `Fastapp` 環境安裝 `httpx2`（連帶 `httpcore2`、`truststore`）。TestClient 改用 `httpx2`，棄用警告消失，嚴格模式可正常收集與執行。

```text
pip install httpx2
```

**影響**：僅測試/環境層，未改動任何應用程式碼。

---

## 問題 2 — `on_event("startup")` → lifespan 遷移

**現象**
`app.py` 以已棄用的 `@app.on_event("startup")` 註冊啟動邏輯（初始化 SQLite 審計表 `init_db()` + 背景磁碟清理任務）。FastAPI 未來大版本移除後，這些啟動工作將不再執行。

**修正**（`app.py`）
改用 `contextlib.asynccontextmanager` 定義 `lifespan`，傳入 `FastAPI(lifespan=lifespan)`，**行為完全等價**：
- 啟動時呼叫 `init_db()` 並建立背景 `cleanup_loop()` 任務
- 關閉時 `task.cancel()` 優雅取消背景任務（原寫法缺少此清理）

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    task = asyncio.create_task(cleanup_loop())
    try:
        yield
    finally:
        task.cancel()

app = FastAPI(..., lifespan=lifespan)
```

**驗證**：伺服器啟動顯示 `Application startup complete`，且嚴格模式不再出現 `on_event is deprecated` 警告。

---

## ＋ Actionable Insight Banner「淨節省」算法修正

**問題**
首頁決策橫幅顯示「為公司省下淨額 $X」。原本前端以
`savings = expected_penalty_exposure − recommended_budget` 計算。

此式偏高估：
- `expected_penalty_exposure` 是**所有**高風險訂單的預期罰金（含升級不划算者）
- `recommended_budget` 只花在**值得升級（net_benefit > 0）**的訂單上
- 用「全部曝險」減「部分預算」，等於把**未被升級訂單的罰金也算成節省**

實測（門檻 0.5）：舊式概算把節省高估約 **$8,943**（低門檻情境差距更大）。

**修正**
- 後端 `/api/executive-summary`（`app.py`）新增精算欄位
  `net_savings = Σ(正 ROI 訂單的 net_benefit)`，即真正可實現的淨節省。
- 前端 `static/app.js` banner 優先使用 `d.net_savings`；舊式算法僅在後端未提供該欄位時作為後備。

**不變量**（已寫成測試）：`0 ≤ net_savings ≤ expected_penalty_exposure − recommended_budget`

---

## 問題 4 — 測試覆蓋與斷言強化

**修正前**：僅 1 檔 8 項 API 測試，`core/` 零單元測試，且部分斷言過寬
（如 `predict-single` 連 500 都算通過、`threshold-tuning` 接受 200/400/404 任一）。

**修正後**：3 檔共 **20 項**測試。

| 檔案 | 內容 |
|------|------|
| `tests/conftest.py` | 統一設定 `sys.path`（root + core），各測試檔共用 |
| `tests/test_api_endpoints.py` | 收緊 `predict-single`（強制 200、驗證 `p_late∈[0,1]`、`risk_bucket∈{Low,Medium,High}`、`recommend_upgrade` 為布林）與 `threshold-tuning`（強制 200、驗證指標值域與混淆矩陣非負）；新增 banner `net_savings` 不變量測試 |
| `tests/test_optimizer.py` | `ShippingOptimizer` 單元測試：空候選安全回傳、**預算限制下的已知最佳解**、預算充足選入所有正 ROI、`run()` 候選篩選（門檻 + ROI>0）、`to_dict()` 結構與四捨五入 |
| `tests/test_security_utils.py` | `DeIdentifier` 去識別化：敏感欄位刪除、Order Id SHA-256 雜湊（決定性 / salt 敏感 / 改名）、`mask_name` 邊界、`apply_all` 管線、清單輔助函式回傳複本 |

---

## 驗證指令

```bash
# 一般模式
pytest tests/ -v

# 嚴格模式（放行第三方 PuLP 棄用警告）
pytest tests/ -W error \
  -W "ignore::DeprecationWarning:pulp.pulp" \
  -W "ignore::DeprecationWarning:pulp.apis.coin_api" -q
```

結果：**20 passed**。

---

## 問題 3 — PuLP 舊式 API（暫不處理，僅記錄）

`core/optimizer.py` 使用 `pulp.LpVariable(...)` 直接建構與 `pulp.PULP_CBC_CMD`，
在 PuLP 4.0 將被移除（目前環境為 PuLP 3.3.2，功能完全正常，僅有棄用警告）。

**結論**：目前不升級 PuLP、不改程式碼即永不損壞。後續若要處理，建議方向為
（a）在依賴鎖定 `pulp<4.0`，(b) 於 pytest 設定過濾該警告，(c) 真要升級 4.0 時再改寫那三行。

---

## 變更檔案清單

| 檔案 | 變更 |
|------|------|
| `app.py` | lifespan 遷移；`/api/executive-summary` 新增 `net_savings` |
| `static/app.js` | banner 改用 `net_savings`，舊式算法降為後備 |
| `static/index.html` | 併入 `bd2cb5e`，移除殘留合併衝突標記與重複區塊 |
| `tests/conftest.py` | 新增（共用 path 設定） |
| `tests/test_optimizer.py` | 新增（5 項） |
| `tests/test_security_utils.py` | 新增（6 項） |
| `tests/test_api_endpoints.py` | 收緊 2 項斷言、新增 1 項 banner 不變量測試 |
