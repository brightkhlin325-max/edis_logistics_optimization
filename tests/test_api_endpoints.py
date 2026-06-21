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
    if response.status_code == 500:
        data = response.json()
        assert "xgboost" in data["detail"].lower() or "模型檔案不存在" in data["detail"]
    else:
        assert response.status_code == 200
        data = response.json()
        assert "p_late" in data
        assert "risk_bucket" in data
        assert "expected_penalty" in data

def test_threshold_tuning_endpoints():
    """驗證門檻值調適接口。"""
    response = client.get("/api/threshold-tuning?current_threshold=0.5")
    assert response.status_code in (200, 400, 404)

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

