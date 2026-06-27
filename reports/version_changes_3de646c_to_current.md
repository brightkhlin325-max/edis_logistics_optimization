# 3de646c 到本次提交差異交接

比對基準：`3de646c893d671ee20b21b44926c59197a86cfad` -> 本次 `ui_restructure` 提交。

## 重點變更

1. ROI 資料流已拆清楚：驗證集歷史 ROI 使用 `decision_dataset.csv` 真實標籤；使用者上傳待預測資料時，ROI 會改用 session 預測資料與收益模型預估利潤，不再混成同一種口徑。
2. ROI 罰金參數已能影響上傳資料分析；無真實結果時會標示為目前上傳資料 ROI，不再顯示假性賺錢比例等需要真實答案的指標。
3. Dashboard 與風險訂單管理的「模擬」入口統一改為 `What-if`，並共用安全的欄位帶入流程，避免一邊改好另一邊失效。
4. 最佳化調度維持 500 筆候選上限，並依「預期延遲損失 - 升級成本 > 0」與預算挑選；頁面明細改成上下排版，主管摘要移除求解器術語。
5. 已知結果 CSV 回填改為同時要求 `Late_delivery_risk` 與 `Order Profit Per Order`，避免只補延遲標籤卻無法支援收益模型與 ROI。
6. 新增 `/static/template.csv`，修正 AI 決策助理「範本」無法下載問題。
7. 模型診斷頁的已知結果匯入移到頁面標題旁，文案改成兩個模型共用；匯入只累積資料，需重訓並採用新版模型後才會更新 Dashboard、最佳化與診斷結果。
8. Trust Map 的收益模型可信度若原始 trust map 缺資料，會用 `profit_test_ready.csv` 與 `profit_predictions.csv` 回補分群 R2/MAE/RMSE，不再顯示無資料。
9. AI 決策助理預設問題移除固定 `$5000` 情境，本機回答會讀取目前最佳化頁的預算、升級成本與罰金設定，並避免 PuLP/MILP 等內部術語。
10. 權限 UI 改成無權限功能直接隱藏，不再顯示鎖住按鈕；權限管理表補齊 Viewer、Manager、Engineer 的實際可見功能。

## 驗證

- `python -m pytest tests/test_api_endpoints.py -q --basetemp=tmp_pytest_strict_20260627a -p no:cacheprovider`：36 passed
- `python -m pytest -q --basetemp=tmp_pytest_strict_20260627b -p no:cacheprovider`：62 passed
- 本機網站已重啟於 `http://127.0.0.1:8001/static/index.html`，首頁可正常載入。

## 注意

已知結果 CSV 回填不是自動重訓，也不會立即替換模型。流程是：匯入已知結果 -> 模型診斷頁啟動重訓 -> 比對新舊指標 -> 採用新版模型。
