# 最佳化ROI模擬器 + 模型診斷落地 — 實作計畫

> 基準分支：`feat/profit-prediction-data`（含收益模型產物）
> 新分支：`feat/roi-simulator-and-diagnostics`
> 對應文件：`D:\SLIDE_決策框架_已知vs預測_整合與實作.md`（落地順序 1–4）
> 已確認決策：① 統一決策資料集 ② 側邊欄新增獨立頁 ③ 沿用現有角色模式 ④ 客群/區域彙總 + 簡單趨勢外推

---

## 0. 關鍵前提（已驗證，非臆測）

| 事實 | 證據 | 影響 |
|---|---|---|
| 延遲模型用「隨機分層切分」，收益模型用「時間切分」 | `data_pipeline.py:150` train_test_split(stratify); `profit_data_pipeline` time_split | 兩個測試集**訂單不重疊**，無法逐單對齊 |
| 兩者 hash 不同 | 延遲 salt `EDIS_2026` 64字元；收益 salt `SLIDE_PROFIT_2026` 16字元 | 不能直接 join |
| 但延遲 hash 可從原始資料重建並 join | `sha256("EDIS_2026:"+OrderId)`，實測 22,544/22,544 命中、profit 0 null | **統一決策資料集可行** |
| 現有頁面（Dashboard/最佳化/風險清單）皆讀 `predictions.csv` | app.py + 各 js | 新功能**另建產物**，不動 predictions.csv → 零衝突 |

**真價值（已知）一律取驗證集真答案**：`net_of_service = profit_actual − true_label × penalty`、`true_label` 即驗證集實際延遲；**不自造回填**。

---

## Phase 0 — 統一決策資料集（離線、零衝突）

新檔 `scripts/build_decision_dataset.py`：
1. 讀 `predictions.csv`（延遲驗證集：order_id_hash, p_late, true_label, expected_penalty, upgrade_cost, shipping_mode, order_region, order_date）。
2. 讀原始 `data/raw/DataCoSupplyChainDataset.csv`，以 `sha256("EDIS_2026:"+OrderId)` 重建 hash。
3. **以 order_id_hash 為單位（order-level）彙總**，避免 item 重複造成列爆炸：
   - 延遲面：`p_late`=訂單各 item 代表值、`true_label`=max(item)、`expected_penalty`、`upgrade_cost` 取自 predictions。
   - 真價值面（原始）：`profit_actual`=Σ Order Profit Per Order；維度 `customer_segment / order_region / category_name / shipping_mode / discount_rate / customer_id_hash`。
   - 收益模型預測：用 `models/profit_lightgbm_model.txt` + `profit_feature_schema.json` 對同一批訂單評分 → `profit_pred`（僅供校準 trust map）。
4. 衍生欄：`net_of_service = profit_actual − true_label*PENALTY`、`epar = profit_actual * p_late`、`profit_resid = profit_actual − profit_pred`、`is_false_positive_value = (profit_actual>0) & (net_of_service<0)`。
5. 產出 `data/processed/decision_dataset.csv` + `decision_dataset_summary.json`（headline KPI）。
6. PENALTY 預設 250（對齊 optimizer delay_penalty），可由 API 參數覆寫。

> 不修改 predictions.csv、profit_predictions.csv 等任何既有產物。

---

## Phase 1 — 後端 API（app.py，沿用 get_cached_predictions 快取模式）

讀取統一資料集用「mtime 快取」避免每請求重讀 18 萬列（防效能/重入問題）。

**最佳化ROI模擬器（落地點 1 + 2）**
1. `GET /api/roi/summary` → 帳載利潤總額、net-of-service 真價值總額、被服務侵蝕金額、假性賺錢訂單數/比例（「61%」洞察）、總 EPAR。
2. `GET /api/roi/portfolio?value_axis=&risk_axis=&segment=&region=&category=&shipping=&discount_band=` → 散點 + 名單資料（value/risk/epar/flags），closed=actual、預測軸=pred（SLIDE E6）。
3. `POST /api/roi/optimize`（**Manager 限定，require_manager**）→ 取 at-risk 訂單以 EPAR 排序，**重用既有 `ShippingOptimizer`**（net_benefit=預期罰金省−升級成本，與現有一致避免衝突），回傳選單 + 客戶層彙整（該救誰/省多少/花多少）。SLIDE E2。
4. `POST /api/profit/predict-single` → 收益模型單筆 what-if 評分（依 profit_feature_schema 編碼）。
5. `POST /api/roi/whatif` → 掃 discount × shipping 網格，每格 `profit_pred`（收益）+ `p_late`（延遲）→ `net = profit_pred − p_late*penalty`，回傳最佳組合 + 熱力圖網格 + 接/婉拒建議（SLIDE E3）。
6. `GET /api/roi/trust-map?dimension=segment` → 各群 profit 殘差 mean/std + 延遲 AUC + 樣本數 → 可信區段（SLIDE E4）。

**模型診斷落地（落地點 3 + 4，Engineer）**
7. `GET /api/diagnose/deterioration?unit=segment|region` → 各群逐月 net-of-service 真價值 + 延遲率時間序列 + **簡單線性趨勢外推**下月 + 劣化最快名單（Phase 3）。
8. `GET /api/profit/leakage-audit` → 洩漏守門狀態、白名單（margin×total）、被擋欄位、actual/pred 欄位標示（落地點 4 之檢視）。
9. 強化 `core/profit_data_pipeline.py::_validate`：對「非白名單」乘積式恆等（|corr|>0.98）報錯；`margin×total` 白名單放行（落地點 4 之守門）。

---

## Phase 2 — 前端

**新檔**：`static/components/roi_simulator.html`、`static/roi_simulator.js`
**改 `index.html`**：側邊欄「最佳化調度」下新增 `nav-roi-simulator`（最佳化ROI模擬器）；新增 `page-roi-simulator` section；引入 roi_simulator.js。
**改 `app.js`**：`showPage()` 加 roi-simulator 分支；`allowedPages` 三角色皆可見；nav 顯示比照「最佳化調度」（全角色可見、最佳化動作 Manager 限定）。

ROI 模擬器頁（對應截圖 1、2）：
- 區塊A KPI：帳載利潤 vs net-of-service 真價值、被侵蝕金額、假性賺錢比例。
- 區塊B 真價值–風險散點：value/risk 軸下拉 + faceted 複選篩選 + **點散點開明細 modal**（防呆：節流點擊、無遞迴）。
- 區塊C 預期在險利潤名單 + 預算輸入 + 「執行 ROI 最佳化」(Manager) → 該救誰 + 客戶層彙整。
- 區塊D What-if：訂單特徵輸入 + discount×shipping 掃描 → 建議折扣/運送 + 接/婉拒 + 熱力圖。
- 區塊E 預測-vs-實際校準 trust map：分群可信度表/熱圖。

模型診斷頁（`model_perf.html` + `model_perf.js` 追加）：
- 帳戶劣化趨勢面板：逐月真價值/延遲率折線 + 外推虛線 + 劣化最快名單。
- 洩漏守門狀態面板：守門結果、白名單、actual/pred 標示。

---

## Phase 3 — 嚴格驗證（按你要求：執行給你看、避免 overflow/stack 與衝突）

0. **先對齊 GitHub（最終驗證前必做）**：`git fetch origin`，檢查 SLIDE repo 是否有新增內容（`origin/main` 或其他相關分支的新 commit）。若有與本功能相關的更新，先評估並整合（merge/rebase 或納入考量），再進行下面的驗證，確保驗證對象是「已含 GitHub 最新內容」的狀態。
1. **資料**：跑 `build_decision_dataset.py`，檢查列數、無 null、數值範圍、KPI 合理。
2. **後端**：`pytest`（既有測試須全綠）＋ 新增端點/守門測試；啟 uvicorn，逐一 curl 新端點看回應。
3. **前端**：啟動 app 點過 ROI 模擬器全區塊 + 診斷新面板；看 console 無錯。
4. **防 stack overflow 專項稽核**：無遞迴 showPage、無自觸發 render 迴圈、散點點擊節流、fetch 攔截器不重入、What-if 網格上限封頂。
5. **回歸**：確認 Dashboard／最佳化調度／風險清單仍正常且 predictions.csv 未被更動。
6. **執行給你看**：把上述執行結果（資料/測試/端點/前端）呈現給你。
7. 全綠且你確認後才進入 **PUSH 環節**；**push 與 PR 需你同意**。

---

## 待你確認後才動工
以上為完整規劃。你說「可以」我才開始（新分支、逐步實作、嚴格驗證、執行給你看）。
</content>
</invoke>
