# 本次 COMMIT 內容 — 最佳化ROI模擬器 + 模型診斷落地

> 分支：`feat/roi-simulator-and-diagnostics`
> 狀態：**實作中**（此文件於驗證完成、PUSH 前更新為最終實際結果）
> 對應規劃：`ROI_SIMULATOR_PLAN.md`、桌面《最佳化ROI模擬器_規劃.md》

---

## 一、這次 COMMIT 做了什麼（摘要）

新增「**最佳化ROI模擬器**」獨立頁，並在工程師「模型診斷」頁落地 SLIDE 決策框架的後續階段，把「收益(真利潤/預測) × 延遲(真延遲/預測) × 客戶決策」整合成可操作的前端＋後端，且**不更動任何既有產物與頁面資料來源（零衝突）**。

---

## 二、變更檔案清單

### 新增
- `scripts/build_decision_dataset.py` — 離線建統一決策資料集
- `data/processed/decision_dataset.csv`（產物）、`decision_dataset_summary.json`
- `static/components/roi_simulator.html` — ROI 模擬器頁面
- `static/roi_simulator.js` — ROI 模擬器邏輯
- `tests/test_roi_endpoints.py` — 新端點測試
- `reports/本次COMMIT內容_最佳化ROI模擬器.md`（本檔）、`ROI_SIMULATOR_PLAN.md`

### 修改
- `app.py` — 新增 ROI 與診斷 API 端點
- `core/profit_data_pipeline.py` — 強化 `_validate` 洩漏守門
- `static/index.html` — 側邊欄新增「最佳化ROI模擬器」、section、script
- `static/app.js` — showPage / allowedPages / 角色顯示
- `static/components/model_perf.html`、`static/model_perf.js` — 帳戶劣化趨勢 + 洩漏守門面板
- `setup_and_run.bat` — 啟動時若缺 decision_dataset.csv 自動產生（非致命）

> environment.yml / requirements.txt 無需變更：lightgbm/pulp/xgboost/scikit-learn/scipy/fastapi 等皆已列入；Chart.js 走 CDN。

---

## 三、功能對照 SLIDE 落地順序

| SLIDE 點 | 內容 | 實作 |
|---|---|---|
| 點1 (A+B1) | 雙層欄位 + net-of-service 真價值 + 在險利潤名單 + PuLP | 統一資料集 + `/api/roi/summary,portfolio,optimize` + ROI 頁 KPI/散點/名單 |
| 點2 (Phase2) | What-if 模擬器 + 預測-vs-實際校準 trust map | `/api/profit/predict-single,/api/roi/whatif,/api/roi/trust-map` + ROI 頁 What-if/trust map |
| 點3 (Phase3) | 帳戶劣化趨勢 + forecast | `/api/diagnose/deterioration`（客群/區域 + 趨勢外推）+ 診斷頁面板 |
| 點4 | 洩漏守門進 _validate + actual/pred 標示 | `profit_data_pipeline._validate` + `/api/profit/leakage-audit` + 診斷頁面板 |

---

## 四、設計重點 / 不衝突保證
- **真答案取自驗證集 `true_label`，不自造回填**。
- 統一資料集由 `predictions.csv`（現有最佳化用驗證集）那批訂單建立；**predictions.csv 等既有產物未更動**。
- ROI 最佳化**重用既有 `ShippingOptimizer`**，EPAR 僅做排序與客戶層彙整（SLIDE E2 指示）。
- 前端防 stack overflow：無遞迴 showPage、散點點擊節流、What-if 網格封頂、fetch 攔截不重入。

---

## 五、驗證結果（已完成）
- [x] `git fetch origin`：origin/main 已前進至 `7df0bd9`（PR #26 已把我們的 base 併入 main）；另有 docs-only 分支 `codex/project-polish-docs`（未併、與本功能無關）。無新程式衝突。
- [x] `build_decision_dataset.py` 產出：22,544 訂單、0 null、KPI 合理（真價值總額 −$1.43M、假性賺錢 45.3%）；trust map 樣本外（延遲 AUC 0.79–0.81、收益 R² 0.79–0.82，與模型真實表現一致）。
- [x] `pytest` 全綠：**32 passed**（既有測試未受影響）。
- [x] uvicorn 啟動 + 端點 curl：summary/portfolio/trust-map/deterioration/leakage-audit/profit-single/whatif 皆 200；optimize Viewer→**403**、Manager→**200**。
- [x] 靜態頁/組件服務正常（index、roi_simulator.html/js、model_perf 皆 200，wiring 命中）。
- [x] 防 stack overflow 稽核：圖表 destroy-before-create、篩選只觸發單一載入（非遞迴）、罰金輸入 debounce、What-if 網格後端封頂（≤48）、散點取樣封頂（≤3000）、fetch 攔截不重入。
- [x] 回歸：/api/metrics、/api/scenario-analysis、/api/predict-single 皆 200；**predictions.csv 未被更動**（mtime 仍為 2026-06-17）。

> 註：`data/processed/decision_dataset*.csv/json` 與既有模型產物同屬 `.gitignore`（由 build 腳本重生），不進版控，無衝突。
> 強化 `_validate`：實測真資料 PASS（margin×total 白名單放行）、注入單欄洩漏被攔截。
</content>
