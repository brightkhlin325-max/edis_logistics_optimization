import pytest
from fastapi.testclient import TestClient
import sys
import io
import pandas as pd
from pathlib import Path

# 將根目錄加入 sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))
from app import app, DATA_DIR
from risk_policy import risk_bucket_for_probability
from training_store import append_training_csv, TrainingDataError

client = TestClient(app)


def _write_session_predictions(session_id: str, rows: list[dict]) -> Path:
    path = DATA_DIR / f"predictions_session_{session_id}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)
    return path

def test_public_metrics_endpoint():
    """驗證公開 metrics 端點正常運作且傳回基本 KPI。"""
    response = client.get("/api/metrics?threshold=0.5")
    assert response.status_code == 200
    data = response.json()
    assert "roc_auc" in data
    assert "precision" in data
    assert "recall" in data

def test_rbac_optimize_viewer():
    """驗證 Viewer 角色存取 /api/optimize 會被拒絕並回傳 403。"""
    response = client.post(
        "/api/optimize",
        headers={"X-Role": "Viewer"},
        json={"budget": 5000.0}
    )
    assert response.status_code == 403
    data = response.json()
    assert "detail" in data
    assert "Viewer" in data["detail"]["message"] or "Logistics_Manager" in data["detail"]["message"]

def test_rbac_optimize_manager():
    """驗證 Manager 角色存取 /api/optimize 成功。"""
    response = client.post(
        "/api/optimize",
        headers={"X-Role": "Logistics_Manager"},
        json={"budget": 5000.0}
    )
    # 不管有沒有 predictions.csv，預期應該都會成功返回 (哪怕是 fallback 示範數據)
    assert response.status_code == 200
    data = response.json()
    assert "budget" in data
    assert "selected_orders" in data

def test_predict_single_order_validation():
    """驗證單筆預測接口的 Pydantic 模型驗證與運算結果。"""
    payload = {
        "shipping_mode": "Standard Class",
        "order_region": "Western Europe",
        "days_for_shipment": 4.0,
        "product_price": 59.99,
        "order_item_quantity": 1,
        "customer_segment": "Consumer",
        "market": "Europe"
    }
    response = client.post("/api/predict-single", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()
    # 結構齊全
    for key in ("p_late", "risk_bucket", "expected_penalty",
                "net_benefit_if_upgrade", "recommend_upgrade"):
        assert key in data, f"缺少欄位 {key}"
    # 值域合理：機率落在 [0, 1]
    assert 0.0 <= data["p_late"] <= 1.0
    # 風險分級為已知值
    assert data["risk_bucket"] in {"Low", "Medium", "High"}
    # 罰金非負、升級建議為布林
    assert data["expected_penalty"] >= 0
    assert isinstance(data["recommend_upgrade"], bool)

def test_threshold_tuning_endpoints():
    """驗證門檻值調適接口回傳完整且合理的指標。"""
    response = client.get("/api/threshold-tuning?current_threshold=0.5")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["row_count"] > 0
    cur = data["current"]
    assert cur["threshold"] == 0.5
    # precision / recall / f1 必須落在 [0, 1]
    for metric in ("precision", "recall", "f1"):
        assert 0.0 <= cur[metric] <= 1.0, f"{metric}={cur[metric]} 超出範圍"
    # 混淆矩陣四格非負
    for cell in ("tp", "tn", "fp", "fn"):
        assert cur[cell] >= 0


def test_predict_sorted_by_urgency_desc():
    """問答看板資料須依 p_late 由高到低（緊急程度）排序。"""
    response = client.get("/api/predict?limit=20")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    if len(data) >= 2:  # 示範資料可能不足，僅在有足量資料時驗證
        ps = [d["p_late"] for d in data]
        assert ps == sorted(ps, reverse=True), f"未依緊急程度降冪排序: {ps}"


def test_predict_relabels_legacy_rows_with_shared_risk_policy():
    response = client.get("/api/predict?limit=50&threshold=0.3")
    assert response.status_code == 200, response.text
    for row in response.json()["data"]:
        assert row["risk_bucket"] == risk_bucket_for_probability(row["p_late"])


def test_predict_exposes_available_months():
    """回應須帶 available_months（給前端月份 flipper）與 active_month。"""
    response = client.get("/api/predict?limit=5")
    assert response.status_code == 200, response.text
    body = response.json()
    assert "available_months" in body
    assert isinstance(body["available_months"], list)
    assert "active_month" in body


def test_predict_exposes_whatif_source_fields():
    """風險清單的「模擬」須帶入原始可用欄位，而非固定預設值。"""
    response = client.get("/api/predict?limit=10&threshold=0.5")
    assert response.status_code == 200, response.text
    rows = response.json()["data"]
    assert rows, "預測清單不可為空"

    for row in rows:
        assert "days_for_shipment" in row
        assert "product_price" in row
        assert "order_item_quantity" in row
        assert row["days_for_shipment"] is not None
        assert row["product_price"] is not None
        assert row["order_item_quantity"] is not None

    tuples = {
        (
            row["days_for_shipment"],
            round(float(row["product_price"]), 2),
            row["order_item_quantity"],
        )
        for row in rows
    }
    assert tuples != {(4, 59.99, 1)}, "What-if 欄位仍全數落回預設值"


def test_predict_month_filter():
    """指定 month 後，回應的 active_month 應一致，且資料量不超過全量。"""
    full = client.get("/api/predict?limit=5").json()
    months = full.get("available_months") or []
    if not months:
        pytest.skip("無月份資料（可能為示範資料）")
    target = months[0]
    resp = client.get(f"/api/predict?limit=5&month={target}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["active_month"] == target
    assert body["count"] <= full["count"]
    # 仍維持緊急度降冪
    ps = [d["p_late"] for d in body["data"]]
    assert ps == sorted(ps, reverse=True)


def test_executive_summary_uses_optimizer_with_500_candidate_cap():
    """驗證 banner 修正：net_savings 為精算淨節省，且不超過舊式樂觀概算。

    net_savings = Σ(正 ROI 訂單的 net_benefit)
    舊式概算   = 全部曝險 - 建議預算（會把未升級訂單罰金誤算成節省，故偏高）
    因此恆有： 0 <= net_savings <= exposure - recommended_budget
    """
    response = client.get("/api/executive-summary")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["optimization_basis"] == "ShippingOptimizer"
    assert data["optimization_max_candidates"] == 500
    assert data["positive_roi_orders"] <= 500
    assert data["optimization_total_orders_considered"] <= 500
    assert data["recommended_budget"] == data["optimization_total_cost"]
    assert data["net_savings"] == data["optimization_expected_total_saving"]
    assert "net_savings" in data, "缺少 net_savings 欄位（banner 修正未生效）"
    exposure = data["expected_penalty_exposure"]
    budget = data["recommended_budget"]
    net = data["net_savings"]
    assert net >= 0
    # 精算淨節省不應超過舊式樂觀上界（容許微小浮點誤差）
    assert net <= (exposure - budget) + 1e-6

def test_rbac_optimize_engineer():
    """驗證 Engineer 角色存取 /api/optimize 成功。"""
    response = client.post(
        "/api/optimize",
        headers={"X-Role": "Engineer"},
        json={"budget": 5000.0}
    )
    assert response.status_code == 200
    data = response.json()
    assert "budget" in data

def test_rbac_retrain_viewer():
    """驗證 Viewer 角色存取 /api/retrain 會被拒絕並回傳 403。"""
    response = client.post(
        "/api/retrain",
        headers={"X-Role": "Viewer"},
        json={"excluded_features": []}
    )
    assert response.status_code == 403

def test_rbac_retrain_engineer():
    """驗證 Engineer 角色存取 /api/retrain 成功。"""
    response = client.post(
        "/api/retrain",
        headers={"X-Role": "Engineer"},
        json={"excluded_features": []}
    )
    assert response.status_code == 200
    data = response.json()
    assert "task_id" in data


def test_profit_metrics_manager_access():
    response = client.get(
        "/api/profit/metrics",
        headers={"X-Role": "Logistics_Manager"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "is_trained" in data
    assert data["metrics"]["feature_count"] == 33
    assert data["manifest"]["feature_count"] == 33
    assert data["manifest"]["model_feature_count"] == 33
    assert data["metrics"].get("metric_file_feature_count") == 33
    assert data["metrics"].get("metric_file_status") is None


def test_profit_metrics_viewer_access():
    response = client.get(
        "/api/profit/metrics",
        headers={"X-Role": "Viewer"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "is_trained" in data


def test_profit_feature_importance_uses_current_model_contract():
    response = client.get("/api/profit/feature-importance?limit=50")
    assert response.status_code == 200, response.text
    data = response.json()
    features = {row["feature"] for row in data["data"]}

    assert data["feature_count"] == 33
    assert "Days for shipping (real)" not in features
    assert "Late_delivery_risk" not in features
    assert "Delivery Status" not in features
    assert "Order Status" not in features


def test_profit_leakage_audit_uses_deployed_feature_contract():
    """守門應檢查部署模型契約，不能被舊版 processed schema 誤判為 FAIL。"""
    response = client.get("/api/profit/leakage-audit")
    assert response.status_code == 200, response.text
    data = response.json()

    assert data["gate_status"] == "PASS"
    assert data["leaked_in_features"] == []
    assert data["feature_count"] == 33
    assert data["serving_contract"]["contract_errors"] == []
    assert data["serving_contract"]["active_feature_count"] == 33
    assert data["serving_contract"]["model_feature_count"] == 33
    assert data["serving_contract"]["legacy_schema_feature_count"] == 33
    assert data["serving_contract"]["legacy_schema_ignored"] is False
    assert data["serving_contract"]["legacy_schema_status"] == "compatible"
    assert data["serving_contract"]["legacy_schema_blocked"] == []
    assert "不是收益模型訓練特徵" in data["column_labeling"]["p_late / late_pred"]


def test_profit_single_prediction_uses_serving_feature_contract():
    """舊版 processed schema 不得影響部署中收益模型的單筆推論。"""
    response = client.post(
        "/api/profit/predict-single",
        json={
            "shipping_mode": "First Class",
            "order_region": "Western Europe",
            "product_price": 49.99,
            "order_item_quantity": 3,
            "days_for_shipment": 2,
        },
    )
    assert response.status_code == 200, response.text
    assert isinstance(response.json()["predicted_profit"], float)


def test_profit_prediction_page_route():
    response = client.get("/profit-prediction")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")


def test_roi_summary_penalty_zero_is_not_treated_as_default():
    zero = client.get("/api/roi/summary?penalty=0").json()
    standard = client.get("/api/roi/summary?penalty=250").json()

    assert zero["penalty_basis"] == 0.0
    assert standard["penalty_basis"] == 250.0
    assert zero["net_of_service_total"] == zero["book_profit_total"]
    assert zero["service_erosion_total"] == 0.0
    assert standard["net_of_service_total"] != zero["net_of_service_total"]
    assert standard["service_erosion_total"] > zero["service_erosion_total"]


def test_roi_summary_uses_session_upload_expected_value_without_ground_truth():
    session_id = "pytest_roi_session_summary"
    path = _write_session_predictions(session_id, [
        {
            "order_id_hash": "pytest-order-1",
            "shipping_mode": "First Class",
            "order_region": "Western Europe",
            "customer_segment": "Consumer",
            "category_name": "Cleats",
            "market": "Europe",
            "p_late": 0.91,
            "days_for_shipment": 2,
            "product_price": 59.99,
            "order_item_quantity": 2,
            "discount_rate": 0.1,
            "upgrade_cost": 55.0,
        },
        {
            "order_id_hash": "pytest-order-2",
            "shipping_mode": "Standard Class",
            "order_region": "South America",
            "customer_segment": "Corporate",
            "category_name": "Fishing",
            "market": "LATAM",
            "p_late": 0.22,
            "days_for_shipment": 5,
            "product_price": 120.0,
            "order_item_quantity": 1,
            "discount_rate": 0.0,
            "upgrade_cost": 50.0,
        },
    ])
    try:
        response = client.get("/api/roi/summary?penalty=250", headers={"X-Session-ID": session_id})
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["rows_orders"] == 2
        assert data["data_scope"]["scope"] == "session_upload"
        assert data["data_scope"]["profit_basis"] == "predicted_profit"
        assert data["data_scope"]["delay_cost_basis"] == "expected_probability"
        assert data["data_scope"]["has_ground_truth"] is False
        assert data["false_positive_available"] is False
        assert data["false_positive_value_pct"] == 0.0
        assert data["service_erosion_total"] == pytest.approx((0.91 + 0.22) * 250, abs=0.05)
    finally:
        path.unlink(missing_ok=True)


def test_roi_portfolio_and_optimize_follow_session_upload_scope():
    session_id = "pytest_roi_session_portfolio"
    path = _write_session_predictions(session_id, [
        {
            "order_id_hash": "pytest-order-1",
            "shipping_mode": "First Class",
            "order_region": "Western Europe",
            "customer_segment": "Consumer",
            "category_name": "Cleats",
            "market": "Europe",
            "p_late": 0.91,
            "days_for_shipment": 2,
            "product_price": 59.99,
            "order_item_quantity": 2,
            "discount_rate": 0.1,
            "upgrade_cost": 55.0,
        },
        {
            "order_id_hash": "pytest-order-2",
            "shipping_mode": "Standard Class",
            "order_region": "South America",
            "customer_segment": "Corporate",
            "category_name": "Fishing",
            "market": "LATAM",
            "p_late": 0.22,
            "days_for_shipment": 5,
            "product_price": 120.0,
            "order_item_quantity": 1,
            "discount_rate": 0.0,
            "upgrade_cost": 50.0,
        },
    ])
    try:
        portfolio = client.get(
            "/api/roi/portfolio?risk_axis=true_label&max_points=100",
            headers={"X-Session-ID": session_id},
        )
        assert portfolio.status_code == 200, portfolio.text
        p_data = portfolio.json()
        assert p_data["total_filtered"] == 2
        assert p_data["risk_axis"] == "true_label"
        assert p_data["risk_axis_effective"] == "p_late"
        assert p_data["data_scope"]["scope"] == "session_upload"
        assert len(p_data["points"]) == 2

        optimize = client.post(
            "/api/roi/optimize",
            headers={"X-Role": "Logistics_Manager", "X-Session-ID": session_id},
            json={"budget": 5000.0, "upgrade_cost": 80.0, "delay_penalty": 250.0, "risk_threshold": 0.3},
        )
        assert optimize.status_code == 200, optimize.text
        o_data = optimize.json()
        assert o_data["data_scope"]["scope"] == "session_upload"
        assert o_data["candidate_pool"] == 1
        assert o_data["total_orders_considered"] == 1
        assert o_data["selected_count"] == 1
        assert o_data["selected_orders"][0]["order_id_hash"] == "pytest-order-1"
        assert o_data["selected_orders"][0]["profit_basis"] == "predicted_profit"
    finally:
        path.unlink(missing_ok=True)


def test_upload_prediction_preserves_roi_fields_without_pseudo_ground_truth():
    from preprocessor import predict_uploaded_csv

    root = Path(__file__).parent.parent
    csv_text = """Order Id,Shipping Mode,Order Region,order date (DateOrders),Days for shipment (scheduled),Product Price,Order Item Quantity,Order Item Discount Rate,Customer Segment,Category Name,Market,Type,Department Name,Order Country
ABC-1,First Class,Western Europe,2017-06-15 12:00,2,59.99,2,0.1,Consumer,Cleats,Europe,TRANSFER,Fitness,France
"""
    result = predict_uploaded_csv(
        io.StringIO(csv_text),
        mapping_path=root / "models" / "feature_mapping.json",
        model_path=root / "models" / "xgboost_model.json",
    )

    assert "true_label" not in result.columns
    assert result.loc[0, "customer_segment"] == "Consumer"
    assert result.loc[0, "category_name"] == "Cleats"
    assert result.loc[0, "market"] == "Europe"
    assert float(result.loc[0, "days_for_shipment"]) == 2.0
    assert float(result.loc[0, "product_price"]) == 59.99
    assert int(result.loc[0, "order_item_quantity"]) == 2


def test_roi_frontend_preserves_zero_penalty_input():
    js = (Path(__file__).parent.parent / "static" / "roi_simulator.js").read_text(encoding="utf-8")

    assert "Number.isFinite(n) ? n : fallback" in js
    assert "function _roiPenalty() { return _numberFromInput('roiPenalty', 250); }" in js
    assert "parseFloat(document.getElementById('roiPenalty')?.value) || 250" not in js
    assert "delay_penalty: _numberFromInput('roiOptPenalty', 250)" in js


def test_roi_frontend_exposes_dynamic_data_scope():
    root = Path(__file__).parent.parent / "static"
    js = (root / "roi_simulator.js").read_text(encoding="utf-8")
    html = (root / "components" / "roi_simulator.html").read_text(encoding="utf-8")

    assert 'id="roiDataScopeNote"' in html
    assert "function renderRoiScope(scope)" in js
    assert "false_positive_available === false ? 'N/A'" in js
    assert "risk_axis_effective" in js


def test_geojson_endpoint_serves_country_feature_collection():
    """地圖應使用原本國界 GeoJSON 熱力圖資料，不依賴外部網路成功與否。"""
    response = client.get("/api/geojson/countries")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["type"] == "FeatureCollection"
    assert data["features"]


def test_region_map_keeps_country_heatmap_without_bubble_fallback():
    """風險訂單管理的地圖仍應是國界熱力圖，不可改成區域泡泡圖。"""
    js = (Path(__file__).parent.parent / "static" / "region_map.js").read_text(encoding="utf-8")

    assert "L.geoJSON" in js
    assert "renderLeafletRegionBubbleMap" not in js
    assert "renderStaticRegionHeatmap" not in js
    assert "REGION_COORDS" not in js
    assert "泡泡" not in js
    assert "if (container) container.innerHTML" in js


def test_risk_list_simulator_button_uses_safe_arguments():
    """風險訂單的模擬按鈕應避免把 JSON 雙引號直接塞進 inline onclick。"""
    js = (Path(__file__).parent.parent / "static" / "risk_list.js").read_text(encoding="utf-8")

    assert "function encodeSimulatorOrder(order)" in js
    assert "function bindSimulatorButtons(container)" in js
    assert "data-simulator-order=\"${simulatorOrder}\"" in js
    assert "JSON.parse(button.dataset.simulatorOrder || '{}')" in js
    assert "onclick=\"window.openOrderSimulation(" not in js


def test_all_simulation_entrypoints_use_shared_handoff():
    """Dashboard 與風險名單必須共用可等待頁面載入的 What-if 入口。"""
    root = Path(__file__).parent.parent / "static"
    dashboard = (root / "dashboard.js").read_text(encoding="utf-8")
    simulator = (root / "simulator.js").read_text(encoding="utf-8")

    assert "window.openOrderSimulation(order)" in dashboard
    assert "window.openDashboardSimulator = openDashboardSimulator" in dashboard
    assert "function openOrderSimulation(" in simulator
    assert "window.openOrderSimulation = openOrderSimulation" in simulator
    assert "setSimulatorSelectValue('pf-order-region', order.order_region || order.orderRegion || 'Western Europe')" in simulator


def test_known_results_upload_requires_delay_and_profit_outcomes():
    """已知結果回填必須同時支援延遲與收益模型，缺實際利潤不可入庫。"""
    csv = io.StringIO(
        "Order Id,Shipping Mode,Order Region,Late_delivery_risk\n"
        "O-1,Standard Class,Western Europe,1\n"
    )

    with pytest.raises(TrainingDataError, match="Order Profit Per Order"):
        append_training_csv(csv, DATA_DIR / "_missing_profit_should_not_write.csv")


def test_roi_trust_map_backfills_profit_reliability():
    """Trust Map 的收益可信度應由現有樣本外收益預測檔回補，不可顯示成空資料。"""
    response = client.get("/api/roi/trust-map")
    assert response.status_code == 200, response.text
    data = response.json()
    profit = data["profit"]

    assert profit["available"] is True
    assert profit["by_segment"], profit
    assert {"group", "n", "mae", "rmse", "r2"}.issubset(profit["by_segment"][0])
    groups = {row["group"] for row in profit["by_segment"]}
    assert groups & {"Consumer", "Corporate", "Home Office"}
    assert profit["source"].startswith("profit_test_ready.csv + profit_predictions.csv")


def test_template_csv_exists_and_contains_required_outcomes():
    """AI 助理下載範本必須存在，且包含兩個模型需要的已知結果欄位。"""
    template = Path(__file__).parent.parent / "static" / "template.csv"
    assert template.exists()
    columns = pd.read_csv(template, nrows=0).columns.tolist()

    assert "Late_delivery_risk" in columns
    assert "Order Profit Per Order" in columns
    assert len(set(columns)) == len(columns)


def test_ui_hides_unauthorized_controls_instead_of_showing_locks():
    """Viewer/Manager 無權限項目應直接隱藏，不再顯示鎖住的操作入口。"""
    root = Path(__file__).parent.parent / "static"
    app_js = (root / "app.js").read_text(encoding="utf-8")
    roi_js = (root / "roi_simulator.js").read_text(encoding="utf-8")
    llm_js = (root / "llm_settings.js").read_text(encoding="utf-8")

    assert "lockedUploadBoxes.forEach(box => box.style.display = 'none')" in app_js
    assert "aiBriefBtn.style.display = isMOrEng ? 'inline-flex' : 'none'" in app_js
    assert "if (optPageLockedBox) optPageLockedBox.classList.add('hidden')" in app_js
    assert "if (lock) lock.classList.add('hidden')" in roi_js
    assert "if (locked) locked.style.display = 'none'" in llm_js


def test_ai_assistant_prompts_avoid_fixed_budget_and_solver_jargon():
    """AI 助理的預設問題與本機摘要不可綁死使用者情境或暴露內部求解器術語。"""
    root = Path(__file__).parent.parent
    ai_html = (root / "static" / "components" / "ai_assistant.html").read_text(encoding="utf-8")
    rbac_html = (root / "static" / "components" / "rbac.html").read_text(encoding="utf-8")
    explainer = (root / "core" / "explainer.py").read_text(encoding="utf-8")

    assert "$5000" not in ai_html
    assert "依目前最佳化調度頁的預算與成本設定" in ai_html
    assert "ROI 罰金檢查" in ai_html
    assert "如果每筆延遲罰金提高到 $500" not in ai_html
    assert "PuLP" not in rbac_html
    assert "MILP" not in rbac_html
    assert "使用 {solver}" not in explainer
    assert "MILP 最佳化結果" not in explainer


def test_model_perf_known_results_upload_is_global_and_two_model_worded():
    """已知結果 CSV 匯入應位於模型診斷頁標題旁，且文案不可只描述延遲標籤。"""
    html = (Path(__file__).parent.parent / "static" / "components" / "model_perf.html").read_text(encoding="utf-8")

    assert 'id="knownResultsUploadBox"' in html
    assert "Late_delivery_risk 與 Order Profit Per Order" in html
    assert "上傳最新標記為實際延遲狀態" not in html


def test_optimization_layout_and_dashboard_cards_are_aligned():
    """最佳化明細改為上下排版，Dashboard 兩張主管卡片維持等寬等高。"""
    root = Path(__file__).parent.parent / "static" / "components"
    optimization = (root / "optimization.html").read_text(encoding="utf-8")
    dashboard = (root / "dashboard.html").read_text(encoding="utf-8")
    opt_js = (Path(__file__).parent.parent / "static" / "optimization.js").read_text(encoding="utf-8")

    assert 'class="optimization-stack"' in optimization
    assert "flex-direction:column" in optimization
    assert "max-height:420px" in optimization
    assert '<tbody id="optPageOrdList">' in optimization
    assert "<th>預估淨效益</th>" in optimization
    assert "<tr>" in opt_js
    assert "positive net benefit" not in opt_js
    assert "repeat(2, minmax(0, 1fr))" in dashboard
    assert "min-height: 150px" in dashboard


def test_profit_diagnostics_are_on_profit_model_tab():
    """收益相關診斷應在收益模型分頁，不放在延遲模型分頁造成語意混淆。"""
    root = Path(__file__).parent.parent / "static" / "components"
    delay_html = (root / "model_perf.html").read_text(encoding="utf-8")
    profit_html = (root / "profit_prediction.html").read_text(encoding="utf-8")
    model_js = (Path(__file__).parent.parent / "static" / "model_perf.js").read_text(encoding="utf-8")

    assert "帳戶劣化趨勢 (Account Deterioration)" not in delay_html
    assert "洩漏守門狀態 (Leakage Gate)" not in delay_html
    assert "帳戶劣化趨勢 (Account Deterioration)" in profit_html
    assert "洩漏守門狀態 (Leakage Gate)" in profit_html
    assert "loadProfitPrediction()" in model_js
    assert "loadDeterioration()" in model_js
    assert "loadLeakageAudit()" in model_js


def test_trust_map_columns_are_balanced_and_profit_labels_are_decoded():
    """Trust Map 左右欄應等寬，收益分群不可只顯示編碼數字。"""
    root = Path(__file__).parent.parent / "static"
    html = (root / "components" / "roi_simulator.html").read_text(encoding="utf-8")
    js = (root / "roi_simulator.js").read_text(encoding="utf-8")
    app_py = (Path(__file__).parent.parent / "app.py").read_text(encoding="utf-8")

    assert 'class="trust-map-grid"' in html
    assert "grid-template-columns:repeat(2, minmax(0, 1fr))" in html
    assert "grid-template-columns:minmax(0, 1fr) auto" in js
    assert "decode_categorical_labels" in app_py
    assert "categorical_mappings" in app_py


def test_role_specific_tour_filters_hidden_or_unauthorized_pages():
    """右下角導覽應依角色顯示，不再介紹已隱藏或不存在的功能。"""
    tour = (Path(__file__).parent.parent / "static" / "tour.js").read_text(encoding="utf-8")

    assert "const TOUR_STEPS" in tour
    assert "roles: ['manager', 'engineer']" in tour
    assert "roles: ['engineer']" in tour
    assert "function _currentTour()" in tour
    assert "_roleAllowed(step)" in tour
    assert "nav-roi-simulator" not in tour
    assert "nav-region-map" not in tour


def test_local_ai_contract_answer_points_user_to_roi_penalty_controls():
    """合約/罰金問題應引導到 ROI 真價值分析，而不是固定回答某個假設。"""
    from app import build_llm_safe_payload, local_llm_fallback

    payload = build_llm_safe_payload({
        "budget": 8000.0,
        "delay_penalty": 500.0,
        "upgrade_cost": 72.0,
        "selected_count": 3,
        "total_cost": 216.0,
        "expected_total_saving": 1200.0,
        "manager_analysis": {
            "headline": "測試資料",
            "recommended_policy": "測試資料",
            "sample_order_explanations": [],
        },
    })
    answer = local_llm_fallback(payload, "目前 ROI 罰金假設應該怎麼檢查？")

    assert "ROI 真價值分析" in answer
    assert "USD $500" in answer
    assert "真價值" in answer
    assert "被服務侵蝕" in answer


def test_ai_sample_orders_are_not_fixed_when_cost_assumptions_change():
    """AI 抽查樣本應來自最佳化結果，成本假設改變時淨效益也要跟著改。"""
    from optimizer import ShippingOptimizer

    raw = pd.DataFrame({
        "order_id_hash": ["A", "B", "C"],
        "p_late": [0.90, 0.88, 0.60],
    })

    low = ShippingOptimizer(
        budget=500.0,
        upgrade_cost=72.0,
        delay_penalty=250.0,
        risk_threshold=0.3,
    ).run(raw, save_results=False).to_dict()
    high = ShippingOptimizer(
        budget=500.0,
        upgrade_cost=180.0,
        delay_penalty=250.0,
        risk_threshold=0.3,
    ).run(raw, save_results=False).to_dict()

    low_benefits = [float(item["net_benefit"]) for item in low["selected_orders"]]
    high_benefits = [float(item["net_benefit"]) for item in high["selected_orders"]]
    assert low_benefits == sorted(low_benefits, reverse=True)
    assert high_benefits == sorted(high_benefits, reverse=True)
    assert low_benefits != high_benefits
