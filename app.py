import logging
from typing import List, Optional
from fastapi import FastAPI, Header, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("edis-backend")

app = FastAPI(
    title="DataCo 物流延遲預測與最佳化調度系統 (EDIS) API",
    description="提供物流延遲風險預測指標、訂單預測結果與調度最佳化建議之 API 服務。",
    version="1.0.0"
)

# Enable CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Models for request/response validation
class MetricsResponse(BaseModel):
    roc_auc: float
    f1: float
    recall: float
    precision: float
    late_rate: float
    high_risk_orders: int

class PredictionItem(BaseModel):
    order_id_hash: str
    shipping_mode: str
    order_region: str
    p_late: float
    risk_bucket: str

class SelectedOrderItem(BaseModel):
    order_id_hash: str
    p_late: float
    upgrade_cost: float
    expected_saving: float
    decision: str

class OptimizationResponse(BaseModel):
    budget: float
    selected_orders: List[SelectedOrderItem]
    total_cost: float
    expected_total_saving: float

# RBAC Role Checker Dependency
def verify_manager_role(x_user_role: Optional[str] = Header(None, alias="X-User-Role")):
    logger.info(f"Received request with X-User-Role: {x_user_role}")
    if not x_user_role:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-User-Role header."
        )
    
    # Accept either 'Manager' or 'Logistics_Manager'
    allowed_roles = ["manager", "logistics_manager"]
    if x_user_role.lower() not in allowed_roles:
        logger.warning(f"Access denied for role: {x_user_role}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: Manager role required to perform this action."
        )
    return x_user_role

@app.get("/")
def read_root():
    return {"message": "DataCo 物流延遲預測與最佳化調度系統 (EDIS) API 正在運行中。"}

@app.get("/api/metrics", response_model=MetricsResponse)
def get_metrics():
    """
    回傳機器學習模型的效能指標（公開端點，所有角色皆可讀取）。
    """
    logger.info("Fetching model metrics")
    # Mock data as specified in implementation_plan.md
    return {
        "roc_auc": 0.91,
        "f1": 0.84,
        "recall": 0.86,
        "precision": 0.82,
        "late_rate": 0.54,
        "high_risk_orders": 128
    }

@app.get("/api/predict", response_model=List[PredictionItem])
def get_predictions():
    """
    回傳去識別化後的物流延遲風險預測清單（公開端點，所有角色皆可讀取）。
    """
    logger.info("Fetching predictions")
    # Mock data as specified in implementation_plan.md
    return [
        {
            "order_id_hash": "a8f3c7d9e2b10a4f5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b",
            "shipping_mode": "Standard Class",
            "order_region": "Western Europe",
            "p_late": 0.82,
            "risk_bucket": "High"
        },
        {
            "order_id_hash": "b7e2d8c9a1b30f4e5d6c7b8a9f0e1d2c3b4a5d6e7f8a9b0c1d2e3f4a5b6c7d8e",
            "shipping_mode": "First Class",
            "order_region": "Central America",
            "p_late": 0.45,
            "risk_bucket": "Medium"
        },
        {
            "order_id_hash": "c6d1b7a8f9e20d3c4b5a6f7e8d9c0b1a2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a",
            "shipping_mode": "Second Class",
            "order_region": "South America",
            "p_late": 0.15,
            "risk_bucket": "Low"
        }
    ]

@app.post("/api/optimize", response_model=OptimizationResponse)
def get_optimization(
    budget: float = 5000.0,
    role: str = Depends(verify_manager_role)
):
    """
    回傳物流調度最佳化推薦清單。
    此端點會驗證權限，若角色非 Manager/Logistics_Manager 則回傳 HTTP 403 Forbidden。
    """
    logger.info(f"Optimizing logistics with budget: {budget} for user with role: {role}")
    # Mock data as specified in implementation_plan.md
    return {
        "budget": budget,
        "selected_orders": [
            {
                "order_id_hash": "a8f3c7d9e2b10a4f5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b",
                "p_late": 0.82,
                "upgrade_cost": 120.0,
                "expected_saving": 350.0,
                "decision": "Upgrade"
            }
        ],
        "total_cost": 4920.0,
        "expected_total_saving": 14800.0
    }
