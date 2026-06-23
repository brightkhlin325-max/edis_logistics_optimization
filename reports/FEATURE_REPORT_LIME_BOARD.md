# EDIS 修改報告：LIME 因子誠實化 + 問答看板月份 flipper / 緊急度排序

> 日期：2026-06-22
> 分支：`feat/edits` → 目標 `main`

---

## 摘要

| # | 項目 | 檔案 | 狀態 |
|---|------|------|:---:|
| 1 | 用詞「主要 X 因子」改為「可能導致延遲的主要因子」 | explainer.py, index.html | ✅ |
| 2 | LIME 因子誠實標記（本訂單實際值 vs 模型整體因子） | explainer.py, app.js | ✅ |
| 3 | 老闆直觀問答看板：依緊急程度排序 + 月份 flipper | app.py, app.js, index.html | ✅ |

驗證：嚴格模式 `pytest -W error` **25 passed**；對 `main` 合併**無衝突**；無遞迴/死碼/多餘 stack。

---

## 1. 用詞精準化（issue 1）

- 敘述（`core/explainer.py` `_build_manager_narrative`）：
  「主要 X 因子為：…」→「**可能導致延遲的主要因子為：…**」
- 問答看板表頭（`static/index.html`）：「主要延遲原因 (X 因子)」→「**可能導致延遲的主要因子**」

## 2. LIME 因子誠實化（issue 2，採 A 誠實版）

**問題**：原本把模型「全域 feature importance」呈現得像是「這張訂單的個別歸因」。但實際 `predictions.csv` 只有
`order_id_hash, shipping_mode, order_region, order_date, p_late, true_label, risk_bucket, expected_penalty, upgrade_cost`，
**沒有**每筆訂單的承諾天數、交易型態等欄位。

**修正**：`FactorImpact` 新增 `order_specific` 旗標——
- `True`：因子帶有**本訂單實際值**（運送模式、目的地區域）。
- `False`：**模型整體性因子**，資料中無逐筆數值（承諾運送天數、訂單交易型態、其他）。

前端（`static/app.js`）在兩處 LIME 視圖（展開列 + 彈窗）以小標呈現：
`本訂單實際值`（藍）／`模型整體因子`（灰），不再讓使用者誤以為天數/交易型態是這張訂單的真實數值。

## 3. 問答看板排序 + 月份 flipper（issue 3）

**問題**：`/api/predict` 在分頁前**完全沒有排序**（`load_cached_predictions` 只 `read_csv`），
看板因此高低風險交錯。

**修正（後端 `app.py`）**：
- 依 `p_late` **由高到低（緊急程度）**排序後再分頁，最該關注的排最前。
- 新增 `month=YYYY-MM` 篩選：`order_date` 為美式 `M/D/YYYY`，以 `pd.to_datetime` 正確解析（不可截字串）。
- 回應新增 `available_months`（取自全量資料，排序穩定）與 `active_month`，供前端 flipper。

**修正（前端 `app.js` / `index.html`）**：
- 在問答看板標頭加入 `◀ 月份 ▶` flipper（`''` = 全部月份置於最前），切換即重載該月、維持緊急度排序。
- `flipMonth` 以 `Math.max/min` 夾擠邊界、變動才動作——無溢位、無遞迴、無無界迴圈。

---

## 測試（`tests/`）

| 檔案 | 新增/變更 |
|------|-----------|
| `tests/test_explainer.py` ✨新 | 敘述新用詞；`order_specific` 旗標（運送模式/區域=True、承諾天數/交易型態=False） |
| `tests/test_api_endpoints.py` | 新增：緊急度降冪排序、`available_months`/`active_month` 存在、`month` 篩選 |

**驗證指令**
```bash
pytest tests/ -v
pytest tests/ -W error -W "ignore::DeprecationWarning:pulp.pulp" -W "ignore::DeprecationWarning:pulp.apis.coin_api" -q
```
結果：**25 passed**。

---

## 變更檔案

| 檔案 | 變更 |
|------|------|
| `core/explainer.py` | 用詞 + `order_specific` 誠實旗標 |
| `app.py` | `/api/predict` 月份篩選 + 緊急度排序 + `available_months` |
| `static/app.js` | 月份 flipper、因子來源小標、看板月份重載 |
| `static/index.html` | flipper UI、表頭用詞 |
| `tests/test_explainer.py` | 新增測試 |
| `tests/test_api_endpoints.py` | 新增 3 項 API 測試 |

## 整合 main 元件化重構 + 後續修正

開發期間 `main` 推了大重構（`184fd61`、`2f27742`），將 `index.html`/`app.js`
拆成多個元件檔（`components/*.html`、`dashboard.js`、`risk_list.js` 等）。已：
- 將本分支 merge `origin/main`，後端（app.py/explainer.py/tests）無衝突自動合併。
- 衝突的 `static/app.js`、`static/index.html` 取 main 新版，並把本功能的前端改動
  **重貼到新結構**：`components/dashboard.html`（flipper + 表頭）、`dashboard.js`
  （flipper 邏輯、因子小標、月份接線）、`app.js`（fetchPredictions 月份參數）。

整合後又修正兩個畫面問題：
1. **彈窗無反應**：重構把 `openExplainModal`/`closeExplainModal` 遺落在
   `index_original.html`，未移入任何作用中 JS，導致「建議升級運送」點擊無效。
   已移植回 `dashboard.js`（含因子來源小標）並 `window` 匯出。
2. **全部顯示 100%**：全體 `p_late` 最大僅 0.9988，但整數四捨五入使 ≥99.5%（3017 筆）
   都顯示「100%」，加上緊急度排序集中於前頁。已改為**顯示 1 位小數**（99.9%）。

## 備註

- 「顯示實際 X 值（如承諾天數）」採誠實版：因 `predictions.csv` 無該欄位，故標示為模型整體因子，不偽造逐筆數值。若日後要顯示真實逐筆天數，需在 `model_pipeline.py` 輸出對應欄位（屬另一較大工項）。
