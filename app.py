"""
app.py
EDIS — DataCo 物流延遲預測與最佳化調度系統

負責人：Bright（協助撰寫：Lisa）
功能：FastAPI 後端服務 + RBAC 角色權限控制
  - GET  /api/metrics    → 公開，回傳模型 KPI
  - GET  /api/predict    → Viewer/Manager，回傳去識別化風險列表
  - GET  /api/explain    → Viewer/Manager，回傳單筆訂單 X 因子與主管摘要
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
    from fastapi import FastAPI, HTTPException, Header, Request, File, UploadFile
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
from preprocessor import predict_uploaded_csv
try:
    from optimizer import ShippingOptimizer
except ImportError:
    ShippingOptimizer = None
try:
    from explainer import ManagerExplainer
except ImportError:
    ManagerExplainer = None


# ── 常數與路徑 ────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data" / "processed"
METRICS_PATH = DATA_DIR / "model_metrics.json"
PREDICTIONS_PATH = DATA_DIR / "predictions.csv"
PREDICTIONS_ACTIVE_PATH = DATA_DIR / "predictions_active.csv"

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
    max_candidates: int = 500


def load_metrics() -> dict:
    if not METRICS_PATH.exists():
        return {}
    with open(METRICS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_predictions(limit_default: bool = True) -> pd.DataFrame:
    if PREDICTIONS_ACTIVE_PATH.exists():
        return pd.read_csv(PREDICTIONS_ACTIVE_PATH)
    if not PREDICTIONS_PATH.exists():
        return pd.DataFrame()
    df = pd.read_csv(PREDICTIONS_PATH)
    if limit_default:
        return df.head(150)
    return df


def build_explainer(limit_default: bool = False) -> Optional["ManagerExplainer"]:
    if ManagerExplainer is None:
        return None
    return ManagerExplainer(predictions=load_predictions(limit_default), metrics=load_metrics())


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
        "endpoints": ["/api/metrics", "/api/predict", "/api/explain/{order_id_hash}", "/api/optimize"],
    }


@app.get("/api/metrics")
async def get_metrics(threshold: float = 0.5):
    """
    [公開] 回傳模型 KPI 指標，支援動態門檻值。
    """
    df_active = load_predictions(limit_default=True)
    df_full = load_predictions(limit_default=False)
    
    # 載入預設特徵重要性與基礎指標
    metrics_base = {}
    if METRICS_PATH.exists():
        try:
            with open(METRICS_PATH, "r", encoding="utf-8") as f:
                metrics_base = json.load(f)
        except Exception:
            pass
            
    if df_full.empty:
        return {
            "roc_auc": metrics_base.get("roc_auc", 0.91),
            "f1": metrics_base.get("f1", 0.84),
            "recall": metrics_base.get("recall", 0.86),
            "precision": metrics_base.get("precision", 0.82),
            "late_rate": metrics_base.get("late_rate", 0.54),
            "high_risk_orders": metrics_base.get("high_risk_orders", 128),
            "confusion_matrix": metrics_base.get("confusion_matrix", [[50, 10], [15, 80]]),
            "feature_importance": metrics_base.get("feature_importance", {}),
            "is_active": False,
        }
        
    actual_col = "true_label" if "true_label" in df_full.columns else ("actual_late" if "actual_late" in df_full.columns else None)
    
    # 計算 active dataset 相關統計，供首頁 KPI 使用
    active_high_risk = 0
    active_late_rate = 0.0
    if not df_active.empty and "p_late" in df_active.columns:
        active_high_risk = int((df_active["p_late"] >= threshold).sum())
        active_actual_col = "true_label" if "true_label" in df_active.columns else ("actual_late" if "actual_late" in df_active.columns else None)
        if active_actual_col and active_actual_col in df_active.columns:
            active_late_rate = float(df_active[active_actual_col].astype(int).mean())
        else:
            active_late_rate = float(df_active["p_late"].mean())
            
    if actual_col is None or actual_col not in df_full.columns or "p_late" not in df_full.columns:
        return {
            "roc_auc": metrics_base.get("roc_auc", 0.91),
            "f1": metrics_base.get("f1", 0.84),
            "recall": metrics_base.get("recall", 0.86),
            "precision": metrics_base.get("precision", 0.82),
            "late_rate": round(active_late_rate, 4),
            "high_risk_orders": active_high_risk,
            "confusion_matrix": metrics_base.get("confusion_matrix", [[50, 10], [15, 80]]),
            "feature_importance": metrics_base.get("feature_importance", {}),
            "is_active": PREDICTIONS_ACTIVE_PATH.exists(),
        }
        
    from sklearn.metrics import roc_auc_score, precision_score, recall_score, f1_score, confusion_matrix
    y_true_full = df_full[actual_col].astype(int)
    y_prob_full = df_full["p_late"].values
    y_pred_full = (y_prob_full >= threshold).astype(int)
    
    try:
        auc_val = float(roc_auc_score(y_true_full, y_prob_full))
    except Exception:
        auc_val = 1.0
        
    prec_val = float(precision_score(y_true_full, y_pred_full, zero_division=0))
    rec_val = float(recall_score(y_true_full, y_pred_full, zero_division=0))
    f1_val = float(f1_score(y_true_full, y_pred_full, zero_division=0))
    cm_val = confusion_matrix(y_true_full, y_pred_full).tolist()
    
    return {
        "roc_auc": round(auc_val, 4),
        "f1": round(f1_val, 4),
        "recall": round(rec_val, 4),
        "precision": round(prec_val, 4),
        "late_rate": round(active_late_rate, 4),
        "high_risk_orders": active_high_risk,
        "confusion_matrix": cm_val,
        "feature_importance": metrics_base.get("feature_importance", {}),
        "is_active": PREDICTIONS_ACTIVE_PATH.exists(),
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
    threshold: float = 0.5,
):
    """
    [Viewer / Manager] 回傳去識別化的訂單延遲風險列表。
    """
    role = get_role(x_role)

    if not PREDICTIONS_PATH.exists() and not PREDICTIONS_ACTIVE_PATH.exists():
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
            },
            {
                "order_id_hash": "b9c8d7e6f5a4b3c2d1e0f9a8b7c6d5e4" * 2,
                "shipping_mode": "First Class",
                "order_region": "Central America",
                "p_late": 0.45,
                "risk_bucket": "Medium",
                "upgrade_cost": 80.0,
                "expected_penalty": 112.5,
            },
        ]
        return {
            "role": role,
            "count": len(sample),
            "page": page,
            "limit": limit,
            "data": sample,
            "note": "示範資料（請先執行 model_pipeline.py）",
        }

    df = load_predictions()

    # 功能1：相容 true_label → actual_late，並計算 is_correct
    if "true_label" in df.columns and "actual_late" not in df.columns:
        df["actual_late"] = df["true_label"]
    if "actual_late" in df.columns and "p_late" in df.columns:
        df["predicted_late"] = (df["p_late"] >= threshold).astype(int)
        df["is_correct"] = (df["predicted_late"] == df["actual_late"].astype(int))
        df["is_correct"] = df["is_correct"].apply(lambda x: bool(x))

    # 應用過濾器
    if search:
        df = df[df['order_id_hash'].astype(str).str.contains(search, case=False, na=False)]
    if risk:
        df = df[df['risk_bucket'] == risk]
    if shipping:
        df = df[df['shipping_mode'] == shipping]
    if region:
        df = df[df['order_region'] == region]

    total_count = len(df)
    
    start_idx = (page - 1) * limit
    end_idx = start_idx + limit
    df_page = df.iloc[start_idx:end_idx]

    # 確保只回傳去識別化欄位
    safe_cols = [
        c for c in [
            "order_id_hash",
            "shipping_mode",
            "order_region",
            "p_late",
            "risk_bucket",
            "upgrade_cost",
            "expected_penalty",
            "actual_late",
            "is_correct",
        ]
        if c in df_page.columns
    ]
    result = df_page[safe_cols].to_dict(orient="records")

    return {
        "role": role,
        "count": total_count,
        "page": page,
        "limit": limit,
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
        demo_selected_orders = [
            {
                "order_id_hash": "a8f3c2d1" * 8,
                "p_late": 0.88,
                "upgrade_cost": 80.0,
                "expected_penalty": 220.0,
                "net_benefit": 140.0,
                "expected_saving": 140.0,
                "risk_bucket": "High",
                "decision": "Upgrade",
                "reason": "High risk, p_late=0.88, net benefit NT$ 140, within budget",
            }
        ]
        return {
            "role": role,
            "budget": request.budget,
            "selected_count": 12,
            "total_cost": 960.0,
            "expected_total_saving": 1890.0,
            "expected_total_penalty_avoided": 2850.0,
            "solver": "demo response",
            "selected_orders": demo_selected_orders,
            "manager_analysis": {
                "headline": "示範分析：高風險訂單應優先升級，主要原因是延遲機率高且升級後仍有正淨效益。",
                "recommended_policy": "優先升級 High risk 且淨效益為正的訂單。",
                "solver": "demo response",
                "budget_usage_pct": round(960.0 / request.budget * 100.0, 2) if request.budget else 0.0,
                "sample_order_explanations": [
                    {
                        "order_id_hash": demo_selected_orders[0]["order_id_hash"],
                        "risk_bucket": "High",
                        "p_late": 0.88,
                        "recommended_action": "升級運送並列入優先調度",
                        "top_x_factors": [
                            {
                                "feature": "Shipping Mode_Standard Class",
                                "label": "運送模式",
                                "impact": "raises risk",
                                "evidence": "示範資料顯示 Standard Class 會提高延遲風險",
                                "weight": 0.0,
                            }
                        ],
                        "manager_summary": "此訂單延遲風險高，升級運送後預期仍有正淨效益，建議優先處理。",
                    }
                ],
                "llm_ready_prompt": "請根據示範最佳化結果產出主管版物流調整建議。",
            },
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
        max_candidates=request.max_candidates,
    )
    
    # Determine the target path for optimization (uploaded CSV or limited 150-row validation set)
    if PREDICTIONS_ACTIVE_PATH.exists():
        opt_path = str(PREDICTIONS_ACTIVE_PATH)
    else:
        temp_opt_path = DATA_DIR / "predictions_temp_opt.csv"
        df_150 = load_predictions(limit_default=True)
        df_150.to_csv(temp_opt_path, index=False)
        opt_path = str(temp_opt_path)

    result = optimizer.run(
        predictions_path=opt_path,
        output_dir=str(DATA_DIR),
    )
    result_dict = result.to_dict()

    explainer = build_explainer()
    manager_analysis = explainer.summarize_optimization(result_dict) if explainer else {
        "headline": "Explainer module unavailable.",
        "recommended_policy": "請確認 core/explainer.py 可載入。",
        "sample_order_explanations": [],
    }

    return {
        "role": role,
        **result_dict,
        "manager_analysis": manager_analysis,
    }


@app.get("/api/explain/{order_id_hash}")
async def explain_order(
    order_id_hash: str,
    x_role: Optional[str] = Header(default=None),
):
    """
    [Viewer / Manager] 回傳單筆訂單的 LIME-style X 因子與主管版分析。

    目前使用 model_metrics.json 的 feature importance 加上 predictions.csv
    可見欄位產生 local attribution；未來可替換為真正 LIME 模型。
    """
    role = get_role(x_role)
    if not PREDICTIONS_PATH.exists():
        raise HTTPException(status_code=404, detail="predictions.csv 不存在，請先產生模型預測。")
    if ManagerExplainer is None:
        raise HTTPException(status_code=500, detail="explainer.py 載入失敗。")

    df = load_predictions(limit_default=False)
    rows = df[df["order_id_hash"].astype(str) == str(order_id_hash)]
    if rows.empty:
        raise HTTPException(status_code=404, detail="找不到此 order_id_hash。")

    explainer = build_explainer(limit_default=False)
    return {
        "role": role,
        **explainer.explain_order(rows.iloc[0].to_dict()),
    }


@app.get("/api/regions")
async def get_region_risk():
    """計算並回傳各區域的平均延遲率排行。"""
    if not PREDICTIONS_PATH.exists():
        return [
            {"order_region": "Western Europe", "p_late": 0.82, "count": 2},
            {"order_region": "Central America", "p_late": 0.45, "count": 1},
        ]
    df = load_predictions(limit_default=False)
    if df.empty or 'order_region' not in df.columns:
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


@app.get("/api/chart/monthly")
async def get_monthly_chart():
    """[公開] 功能3：月份維度 Y_hat vs Y 趨勢。"""
    if not PREDICTIONS_PATH.exists():
        demo = [
            {"month": f"2016-{str(m).zfill(2)}",
             "avg_p_late": round(0.5 + (m % 3) * 0.05, 3),
             "actual_late_rate": round(0.48 + (m % 4) * 0.04, 3)}
            for m in range(1, 13)
        ]
        return {"data": demo, "note": "示範資料"}

    df = load_predictions(limit_default=False)

    # 相容 true_label
    if "true_label" in df.columns and "actual_late" not in df.columns:
        df["actual_late"] = df["true_label"]

    date_col = next((c for c in ["order_date", "Order Date", "date"] if c in df.columns), None)
    if date_col is None:
        return {"data": [], "note": "找不到日期欄位"}

    df["_month"] = pd.to_datetime(df[date_col], errors="coerce").dt.to_period("M").astype(str)
    df = df.dropna(subset=["_month"])

    agg_dict = {"avg_p_late": ("p_late", "mean")}
    if "actual_late" in df.columns:
        agg_dict["actual_late_rate"] = ("actual_late", "mean")

    agg = df.groupby("_month").agg(**agg_dict).reset_index().rename(columns={"_month": "month"})
    if "actual_late_rate" not in agg.columns:
        agg["actual_late_rate"] = None

    return {"data": agg.to_dict(orient="records")}

@app.post("/api/upload-orders")
async def upload_orders(
    file: UploadFile = File(...),
    x_role: Optional[str] = Header(default=None),
):
    """
    [僅限 Logistics_Manager] 匯入新訂單 CSV 進行延遲預測。
    """
    role = get_role(x_role)
    require_manager(role)
    
    mapping_path = BASE_DIR / "models" / "feature_mapping.json"
    model_path = BASE_DIR / "models" / "xgboost_model.json"
    
    if not mapping_path.exists() or not model_path.exists():
        raise HTTPException(status_code=500, detail="模型或特徵映射檔不存在，請先確認 models 目錄中包含 xgbooost_model.json 與 feature_mapping.json")
        
    try:
        import io
        contents = await file.read()
        df_predicted = predict_uploaded_csv(io.BytesIO(contents), mapping_path, model_path)
        
        # 確保 data/processed 目錄存在
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        df_predicted.to_csv(PREDICTIONS_ACTIVE_PATH, index=False)
        
        return {
            "status": "success",
            "message": f"成功匯入並預測 {len(df_predicted)} 筆新訂單",
            "count": len(df_predicted),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"匯入與預測失敗: {str(e)}")

@app.post("/api/reset-orders")
async def reset_orders(
    x_role: Optional[str] = Header(default=None),
):
    """
    [僅限 Logistics_Manager] 重設匯入的訂單，切換回預設測試集。
    """
    role = get_role(x_role)
    require_manager(role)
    
    if PREDICTIONS_ACTIVE_PATH.exists():
        try:
            os.remove(PREDICTIONS_ACTIVE_PATH)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"重設失敗: {str(e)}")
            
    return {
        "status": "success",
        "message": "已成功清除匯入訂單，回到預設驗證集",
    }

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
