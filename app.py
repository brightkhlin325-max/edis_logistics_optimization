"""
app.py
EDIS — DataCo 物流延遲預測與最佳化調度系統

負責人：Bright（協助撰寫：Lisa）
功能：FastAPI 後端服務 + RBAC 角色權限控制
  - GET  /api/metrics    → 公開，回傳模型 KPI
  - GET  /api/predict    → Viewer/Manager，回傳去識別化風險列表
  - POST /api/optimize   → 僅限 Logistics_Manager，Viewer 呼叫回傳 403

啟動方式：
  cd edis_logistics_optimization
  uvicorn app:app --reload --port 8000

測試角色切換（curl 範例）：
  # Viewer
  curl -H "X-Role: Viewer" http://localhost:8000/api/predict
  # Manager
  curl -H "X-Role: Logistics_Manager" -X POST \
       -H "Content-Type: application/json" \
       -d '{"budget": 5000}' \
       http://localhost:8000/api/optimize
"""

import json
import os
from pathlib import Path
from typing import Optional

try:
    from fastapi import FastAPI, HTTPException, Header, Request
    from fastapi.responses import JSONResponse
    from fastapi.staticfiles import StaticFiles
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel
except ImportError:
    raise ImportError(
        "FastAPI 未安裝。請執行：conda install -n Fastapp -c conda-forge fastapi uvicorn"
    )

import pandas as pd

# 本地模組
import sys
sys.path.insert(0, str(Path(__file__).parent / "core"))
try:
    from optimizer import ShippingOptimizer
except ImportError:
    ShippingOptimizer = None


# ── 常數與路徑 ────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data" / "processed"
METRICS_PATH = DATA_DIR / "model_metrics.json"
PREDICTIONS_PATH = DATA_DIR / "predictions.csv"

# RBAC 角色定義
ROLE_VIEWER = "Viewer"
ROLE_MANAGER = "Logistics_Manager"
VALID_ROLES = {ROLE_VIEWER, ROLE_MANAGER}


# ── FastAPI 應用 ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="EDIS — 物流延遲預測與最佳化調度系統",
    description="DataCo 供應鏈 AI 預測與最佳化 API（含 RBAC）",
    version="1.0.0",
)

# 允許前端（index.html）呼叫 API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 掛載靜態檔案（前端 Dashboard）
static_dir = BASE_DIR / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# ── Pydantic 模型 ─────────────────────────────────────────────────────────────

class OptimizeRequest(BaseModel):
    budget: float = 5000.0
    upgrade_cost: float = 80.0
    delay_penalty: float = 250.0


# ── RBAC 工具函數 ─────────────────────────────────────────────────────────────

def get_role(x_role: Optional[str]) -> str:
    """
    從 HTTP Header X-Role 取得角色。
    若未提供或無效，預設為 Viewer。
    """
    if x_role and x_role in VALID_ROLES:
        return x_role
    return ROLE_VIEWER


def require_manager(role: str) -> None:
    """
    要求呼叫者必須是 Logistics_Manager。
    否則拋出 403 Forbidden。
    """
    if role != ROLE_MANAGER:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "403 Forbidden",
                "message": "此端點僅限 Logistics_Manager 存取。Viewer 無執行最佳化的權限。",
                "your_role": role,
            },
        )


# ── 路由 ──────────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    """健康檢查 / 首頁跳轉。"""
    return {
        "system": "EDIS — DataCo 物流延遲預測與最佳化調度系統",
        "version": "1.0.0",
        "docs": "/docs",
        "endpoints": ["/api/metrics", "/api/predict", "/api/optimize"],
    }


@app.get("/api/metrics")
async def get_metrics():
    """
    [公開] 回傳模型 KPI 指標。
    不需要任何角色驗證，所有人可存取。

    回傳格式：
        {
            "roc_auc": 0.91,
            "f1": 0.84,
            "recall": 0.86,
            "precision": 0.82,
            "late_rate": 0.54,
            "high_risk_orders": 128
        }
    """
    if not METRICS_PATH.exists():
        # 回傳示範資料（模型尚未訓練時）
        return {
            "roc_auc": 0.91,
            "f1": 0.84,
            "recall": 0.86,
            "precision": 0.82,
            "late_rate": 0.54,
            "high_risk_orders": 128,
            "note": "示範資料（模型尚未訓練，請先執行 model_pipeline.py）",
        }

    with open(METRICS_PATH, "r", encoding="utf-8") as f:
        metrics = json.load(f)

    # 只回傳摘要指標（不包含 confusion_matrix 細節）
    return {
        "roc_auc": metrics.get("roc_auc"),
        "f1": metrics.get("f1"),
        "recall": metrics.get("recall"),
        "precision": metrics.get("precision"),
        "late_rate": metrics.get("late_rate"),
        "high_risk_orders": metrics.get("high_risk_orders"),
    }


@app.get("/api/predict")
async def get_predictions(
    x_role: Optional[str] = Header(default=None),
    limit: int = 50,
):
    """
    [Viewer / Manager] 回傳去識別化的訂單延遲風險列表。
    - Viewer：可存取，但只看到摘要欄位
    - Manager：可存取，看到完整欄位

    Header：
        X-Role: Viewer | Logistics_Manager

    回傳格式：
        [
            {
                "order_id_hash": "a8f3...",
                "p_late": 0.82,
                "risk_bucket": "High"
            }
        ]
    """
    role = get_role(x_role)

    if not PREDICTIONS_PATH.exists():
        # 回傳示範資料
        sample = [
            {
                "order_id_hash": "a8f3c2d1e4b5f6a7b8c9d0e1f2a3b4c5" * 2,
                "p_late": 0.82,
                "risk_bucket": "High",
                "upgrade_cost": 80.0,
                "expected_penalty": 205.0,
            },
            {
                "order_id_hash": "b9c8d7e6f5a4b3c2d1e0f9a8b7c6d5e4" * 2,
                "p_late": 0.45,
                "risk_bucket": "Medium",
                "upgrade_cost": 80.0,
                "expected_penalty": 112.5,
            },
        ]
        return {
            "role": role,
            "count": len(sample),
            "data": sample,
            "note": "示範資料（請先執行 model_pipeline.py）",
        }

    df = pd.read_csv(PREDICTIONS_PATH).head(limit)

    # 確保只回傳去識別化欄位
    safe_cols = [c for c in ["order_id_hash", "p_late", "risk_bucket", "upgrade_cost", "expected_penalty"] if c in df.columns]
    result = df[safe_cols].to_dict(orient="records")

    return {
        "role": role,
        "count": len(result),
        "data": result,
    }


@app.post("/api/optimize")
async def run_optimization(
    request: OptimizeRequest,
    x_role: Optional[str] = Header(default=None),
):
    """
    [僅限 Logistics_Manager] 執行最佳化調度。
    Viewer 呼叫此端點將收到 403 Forbidden。

    Header：
        X-Role: Logistics_Manager    ← 必須

    Body：
        {
            "budget": 5000,
            "upgrade_cost": 80,
            "delay_penalty": 250
        }

    回傳格式：
        {
            "budget": 5000,
            "selected_count": 42,
            "total_cost": 3360,
            "expected_total_saving": 9450,
            "selected_orders": [...]
        }
    """
    role = get_role(x_role)

    # ── RBAC 核心：403 檢查 ──────────────────────────────────────────────
    require_manager(role)
    # ─────────────────────────────────────────────────────────────────────

    if not PREDICTIONS_PATH.exists():
        # 示範回傳
        return {
            "role": role,
            "budget": request.budget,
            "selected_count": 12,
            "total_cost": 960.0,
            "expected_total_saving": 2850.0,
            "selected_orders": [
                {
                    "order_id_hash": "a8f3c2d1" * 8,
                    "p_late": 0.88,
                    "upgrade_cost": 80.0,
                    "expected_saving": 220.0,
                    "risk_bucket": "High",
                    "decision": "Upgrade",
                }
            ],
            "note": "示範資料（請先執行 model_pipeline.py）",
        }

    if ShippingOptimizer is None:
        raise HTTPException(
            status_code=500,
            detail="optimizer.py 載入失敗，請確認 core/ 目錄存在。",
        )

    optimizer = ShippingOptimizer(
        budget=request.budget,
        upgrade_cost=request.upgrade_cost,
        delay_penalty=request.delay_penalty,
    )
    result = optimizer.run(
        predictions_path=str(PREDICTIONS_PATH),
        output_dir=str(DATA_DIR),
    )

    return {
        "role": role,
        **result.to_dict(),
    }


# ── 全域錯誤處理 ──────────────────────────────────────────────────────────────

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """統一 HTTP 錯誤回傳格式。"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "status_code": exc.status_code,
            "detail": exc.detail,
        },
    )


# ── 直接執行入口 ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        import uvicorn
        print("啟動 EDIS API 伺服器...")
        print("  文件：http://localhost:8000/docs")
        print("  前端：http://localhost:8000/static/index.html")
        uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
    except ImportError:
        print("uvicorn 未安裝。請執行：conda install -n Fastapp -c conda-forge uvicorn")
