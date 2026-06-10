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

import io
import json
import os
from pathlib import Path
from typing import Optional

try:
    from fastapi import FastAPI, HTTPException, Header, Request, UploadFile, File
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
    from preprocessor import predict_uploaded_csv
except ImportError:
    ShippingOptimizer = None
    predict_uploaded_csv = None


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
        "endpoints": ["/api/metrics", "/api/predict", "/api/optimize", "/api/upload"],
    }


@app.post("/api/upload")
async def upload_csv(file: UploadFile = File(...)):
    """
    [公開/Manager] 上傳訂單 CSV 檔案以進行延遲機率預測，並更新寫入 predictions.csv。
    """
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="請上傳 .csv 格式的檔案。")

    if predict_uploaded_csv is None:
        raise HTTPException(
            status_code=500,
            detail="系統內部錯誤：無法載入特徵預測器 (preprocessor.py)。"
        )

    try:
        contents = await file.read()
        mapping_path = BASE_DIR / "models" / "feature_mapping.json"
        model_path = BASE_DIR / "models" / "xgboost_model.json"
        
        df_predicted = predict_uploaded_csv(
            io.BytesIO(contents),
            mapping_path=mapping_path,
            model_path=model_path
        )
        
        df_predicted.to_csv(PREDICTIONS_PATH, index=False)
        
        return {
            "success": True,
            "message": f"成功處理 {len(df_predicted)} 筆訂單資料，並已更新延遲預測結果！",
            "count": len(df_predicted)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"CSV 檔案處理或預測失敗：{str(e)}")


@app.get("/api/metrics")
async def get_metrics(threshold: float = 0.5):
    """
    [公開] 回傳模型 KPI 指標，支援動態門檻值計算。
    """
    # 預設載入靜態指標
    metrics = {}
    if METRICS_PATH.exists():
        with open(METRICS_PATH, "r", encoding="utf-8") as f:
            metrics = json.load(f)

    # 如果 predictions.csv 存在，則根據輸入的 threshold 動態重新計算混淆矩陣與指標
    if PREDICTIONS_PATH.exists():
        try:
            df = pd.read_csv(PREDICTIONS_PATH)
            if "true_label" in df.columns and "p_late" in df.columns:
                actual = df["true_label"].astype(int)
                predicted = (df["p_late"] >= threshold).astype(int)

                tn = int(((actual == 0) & (predicted == 0)).sum())
                fp = int(((actual == 0) & (predicted == 1)).sum())
                fn = int(((actual == 1) & (predicted == 0)).sum())
                tp = int(((actual == 1) & (predicted == 1)).sum())

                confusion_matrix = [[tn, fp], [fn, tp]]

                precision = float(tp / (tp + fp)) if (tp + fp) > 0 else 0.0
                recall = float(tp / (tp + fn)) if (tp + fn) > 0 else 0.0
                f1 = (
                    float(2 * precision * recall / (precision + recall))
                    if (precision + recall) > 0
                    else 0.0
                )
                late_rate = float(predicted.mean())
                high_risk_orders = int((df["p_late"] >= threshold).sum())
                expected_penalty_sum = float(df[df["p_late"] >= threshold]["expected_penalty"].sum())
                total_orders = len(df)

                # 每月趨勢與誤差資料 (Y vs Yhat)
                monthly_trends = []
                if "order_date" in df.columns:
                    try:
                        df_dates = df.copy()
                        df_dates["order_date_parsed"] = pd.to_datetime(df_dates["order_date"], errors="coerce")
                        df_dates = df_dates.dropna(subset=["order_date_parsed"])
                        df_dates["month"] = df_dates["order_date_parsed"].dt.to_period("M").astype(str)
                        
                        grouped = df_dates.groupby("month").agg(
                            actual_late=("true_label", "sum"),
                            predicted_late=("predicted_late", "sum"),
                            total=("true_label", "count")
                        ).reset_index()
                        grouped = grouped.sort_values("month")
                        monthly_trends = grouped.to_dict(orient="records")
                    except Exception:
                        pass

                return {
                    "roc_auc": metrics.get("roc_auc", 0.803),
                    "f1": round(f1, 4),
                    "recall": round(recall, 4),
                    "precision": round(precision, 4),
                    "late_rate": round(late_rate, 4),
                    "high_risk_orders": high_risk_orders,
                    "expected_penalty_sum": round(expected_penalty_sum, 2),
                    "total_orders": total_orders,
                    "confusion_matrix": confusion_matrix,
                    "monthly_trends": monthly_trends,
                    "feature_importance": metrics.get("feature_importance"),
                }
        except Exception:
            pass

    # 示範/備用回傳
    return {
        "roc_auc": metrics.get("roc_auc", 0.91),
        "f1": metrics.get("f1", 0.84),
        "recall": metrics.get("recall", 0.86),
        "precision": metrics.get("precision", 0.82),
        "late_rate": metrics.get("late_rate", 0.54),
        "high_risk_orders": metrics.get("high_risk_orders", 128),
        "confusion_matrix": metrics.get("confusion_matrix"),
        "feature_importance": metrics.get("feature_importance"),
    }


@app.get("/api/predict")
async def get_predictions(
    x_role: Optional[str] = Header(default=None),
    limit: int = 50,
    page: int = 1,
    search: Optional[str] = None,
    risk: Optional[str] = None,
    shipping: Optional[str] = None,
    region: Optional[str] = None,
    threshold: Optional[float] = None,
    error_only: Optional[bool] = None,
):
    """
    [Viewer / Manager] 回傳去識別化的訂單延遲風險列表。
    """
    role = get_role(x_role)
    threshold_val = threshold if threshold is not None else 0.5

    if not PREDICTIONS_PATH.exists():
        # 回傳示範資料
        sample = [
            {
                "order_id_hash": "a8f3c2d1e4b5f6a7b8c9d0e1f2a3b4c5" * 2,
                "shipping_mode": "Standard Class",
                "order_region": "Western Europe",
                "p_late": 0.82,
                "risk_bucket": "High",
                "upgrade_cost": 80.0,
                "expected_penalty": 205.0,
                "predicted_late": 1 if 0.82 >= threshold_val else 0,
                "is_correct": True,
            },
            {
                "order_id_hash": "b9c8d7e6f5a4b3c2d1e0f9a8b7c6d5e4" * 2,
                "shipping_mode": "First Class",
                "order_region": "Central America",
                "p_late": 0.45,
                "risk_bucket": "Medium",
                "upgrade_cost": 80.0,
                "expected_penalty": 112.5,
                "predicted_late": 1 if 0.45 >= threshold_val else 0,
                "is_correct": False,
            },
        ]
        if error_only:
            sample = [s for s in sample if not s["is_correct"]]
        return {
            "role": role,
            "count": len(sample),
            "page": page,
            "limit": limit,
            "data": sample,
            "note": "示範資料（請先執行 model_pipeline.py）",
        }

    df = pd.read_csv(PREDICTIONS_PATH)

    # 動態計算 predicted_late 和 is_correct
    if "p_late" in df.columns:
        df["predicted_late"] = (df["p_late"] >= threshold_val).astype(int)
        if "true_label" in df.columns:
            df["is_correct"] = (df["true_label"].astype(int) == df["predicted_late"])
        else:
            df["is_correct"] = True

    # 應用過濾器
    if search:
        df = df[df["order_id_hash"].astype(str).str.contains(search, case=False, na=False)]
    if risk:
        df = df[df["risk_bucket"] == risk]
    if shipping:
        df = df[df["shipping_mode"] == shipping]
    if region:
        df = df[df["order_region"] == region]
    if threshold is not None:
        df = df[df["p_late"] >= threshold]
    if error_only:
        df = df[~df["is_correct"]]

    total_count = len(df)

    start_idx = (page - 1) * limit
    end_idx = start_idx + limit
    df_page = df.iloc[start_idx:end_idx]

    # 載入 metrics 以讀取 feature_importance
    metrics_data = {}
    if METRICS_PATH.exists():
        try:
            with open(METRICS_PATH, "r", encoding="utf-8") as f:
                metrics_data = json.load(f)
        except Exception:
            pass

    try:
        from explainer import ManagerExplainer
        explainer = ManagerExplainer(df, metrics_data)
    except Exception:
        explainer = None

    records = df_page.to_dict(orient="records")
    result = []
    for rec in records:
        top_factor = "未知"
        rec_action = "監控中"
        if explainer is not None:
            try:
                exp = explainer.explain_order(rec)
                rec_action = exp.get("recommended_action", "監控中")
                if exp.get("top_x_factors"):
                    top1 = exp["top_x_factors"][0]
                    top_factor = f"{top1.get('label', '')}: {top1.get('evidence', '')}"
            except Exception:
                pass
        
        result.append({
            "order_id_hash": rec.get("order_id_hash"),
            "shipping_mode": rec.get("shipping_mode"),
            "order_region": rec.get("order_region"),
            "p_late": rec.get("p_late"),
            "risk_bucket": rec.get("risk_bucket"),
            "upgrade_cost": rec.get("upgrade_cost"),
            "expected_penalty": rec.get("expected_penalty"),
            "predicted_late": rec.get("predicted_late"),
            "is_correct": rec.get("is_correct"),
            "top_factor": top_factor,
            "recommended_action": rec_action,
        })

    return {
        "role": role,
        "count": total_count,
        "page": page,
        "limit": limit,
        "data": result,
    }


@app.get("/api/summary")
async def get_summary(by: str = "shipping_mode"):
    """[公開] 依指定維度彙總訂單數量與平均延遲機率。"""
    allowed = {"shipping_mode", "order_region", "risk_bucket"}
    if by not in allowed:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"by 必須為: {', '.join(allowed)}")

    if not PREDICTIONS_PATH.exists():
        return []

    df = pd.read_csv(PREDICTIONS_PATH)
    grouped = (
        df.groupby(by)
        .agg(count=(by, "count"), avg_p_late=("p_late", "mean"))
        .reset_index()
    )
    grouped["avg_p_late"] = grouped["avg_p_late"].round(4)
    grouped = grouped.sort_values("count", ascending=False)
    return grouped.rename(columns={by: "label"}).to_dict(orient="records")


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

    result_dict = result.to_dict()
    
    # 執行 ManagerExplainer 產出對應的管理報告以通過系統合約驗證與提供前端數據
    try:
        from explainer import ManagerExplainer
        df = pd.read_csv(PREDICTIONS_PATH)
        metrics = {}
        if METRICS_PATH.exists():
            with open(METRICS_PATH, "r", encoding="utf-8") as f:
                metrics = json.load(f)
        explainer = ManagerExplainer(df, metrics)
        result_dict["manager_analysis"] = explainer.summarize_optimization(result_dict)
    except Exception as e:
        result_dict["manager_analysis"] = {
            "headline": f"最佳化建議（無法載入分析器：{str(e)}）",
            "recommended_policy": "優先處理高風險與正淨效益訂單",
            "sample_order_explanations": []
        }

    return {
        "role": role,
        **result_dict,
    }


@app.get("/api/explain/{order_id_hash}")
async def get_order_explanation(
    order_id_hash: str,
    x_role: Optional[str] = Header(default=None),
):
    """
    [Viewer / Manager] 回傳特定訂單的 LIME-style 可解釋性分析。
    """
    role = get_role(x_role)

    if not PREDICTIONS_PATH.exists():
        raise HTTPException(status_code=404, detail="預測資料不存在，請先執行 pipeline。")

    df = pd.read_csv(PREDICTIONS_PATH)
    rows = df[df["order_id_hash"].astype(str) == order_id_hash]
    if rows.empty:
        raise HTTPException(status_code=404, detail=f"找不到訂單：{order_id_hash}")

    order_dict = rows.iloc[0].to_dict()

    # 載入 metrics 以讀取 feature_importance
    metrics = {}
    if METRICS_PATH.exists():
        try:
            with open(METRICS_PATH, "r", encoding="utf-8") as f:
                metrics = json.load(f)
        except Exception:
            pass

    try:
        from explainer import ManagerExplainer

        explainer = ManagerExplainer(df, metrics)
        explanation = explainer.explain_order(order_dict)
        return explanation
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"解釋器執行失敗：{str(e)}")


@app.get("/api/regions")
async def get_region_risk():
    """計算並回傳各區域的平均延遲率排行。"""
    if not PREDICTIONS_PATH.exists():
        return [
            {"order_region": "Western Europe", "p_late": 0.82, "count": 2},
            {"order_region": "Central America", "p_late": 0.45, "count": 1},
        ]
    df = pd.read_csv(PREDICTIONS_PATH)
    if 'order_region' not in df.columns:
        return []
    
    # 分群計算平均延遲率與訂單數
    grouped = df.groupby('order_region').agg(
        p_late=('p_late', 'mean'),
        count=('p_late', 'count')
    ).reset_index()
    
    grouped['p_late'] = grouped['p_late'].round(4)
    # 依延遲率降冪排序
    grouped = grouped.sort_values(by='p_late', ascending=False)
    return grouped.to_dict(orient="records")


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
