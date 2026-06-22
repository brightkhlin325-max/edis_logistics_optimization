import pytest
from fastapi.testclient import TestClient
import sys
from pathlib import Path

# 將根目錄加入 sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))
from app import app

client = TestClient(app)

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


def test_predict_exposes_available_months():
    """回應須帶 available_months（給前端月份 flipper）與 active_month。"""
    response = client.get("/api/predict?limit=5")
    assert response.status_code == 200, response.text
    body = response.json()
    assert "available_months" in body
    assert isinstance(body["available_months"], list)
    assert "active_month" in body


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


def test_executive_summary_net_savings_invariant():
    """驗證 banner 修正：net_savings 為精算淨節省，且不超過舊式樂觀概算。

    net_savings = Σ(正 ROI 訂單的 net_benefit)
    舊式概算   = 全部曝險 - 建議預算（會把未升級訂單罰金誤算成節省，故偏高）
    因此恆有： 0 <= net_savings <= exposure - recommended_budget
    """
    response = client.get("/api/executive-summary")
    assert response.status_code == 200, response.text
    data = response.json()
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

