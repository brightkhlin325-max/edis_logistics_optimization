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
import base64
import ctypes
import hashlib
import hmac
import json
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

try:
    from fastapi import FastAPI, HTTPException, Header, Request, UploadFile, File, BackgroundTasks
    from fastapi.responses import FileResponse, JSONResponse
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
    from preprocessor import predict_uploaded_csv, validate_upload_columns, UploadValidationError
    from training_store import append_training_csv, TrainingDataError
except ImportError:
    ShippingOptimizer = None
    predict_uploaded_csv = None
    validate_upload_columns = None
    append_training_csv = None
    class UploadValidationError(ValueError):
        pass
    class TrainingDataError(ValueError):
        pass


# ── 常數與路徑 ────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data" / "processed"
METRICS_PATH = DATA_DIR / "model_metrics.json"
PREDICTIONS_PATH = DATA_DIR / "predictions.csv"
PROFIT_METRICS_PATH = DATA_DIR / "profit_model_metrics.json"
PROFIT_PREDICTIONS_PATH = DATA_DIR / "profit_predictions.csv"
PROFIT_MANIFEST_PATH = BASE_DIR / "models" / "profit_feature_manifest.json"
LLM_RUNTIME_CONFIG_PATH = DATA_DIR / "llm_runtime_config.json"

# DataFrame 快取機制
PREDICTIONS_CACHE = {}
ASSISTANT_CACHE: dict = {}  # (intent, params_json, pred_path_str) → response dict

def load_cached_predictions(path: Path) -> pd.DataFrame:
    """載入並快取 CSV 預測資料，避免每次請求都重複讀取與解析。"""
    if not path.exists():
        raise FileNotFoundError(f"檔案不存在: {path}")
    
    mtime = path.stat().st_mtime
    cache_entry = PREDICTIONS_CACHE.get(path)
    
    if cache_entry is None or cache_entry["mtime"] != mtime:
        df = pd.read_csv(path)
        PREDICTIONS_CACHE[path] = {
            "mtime": mtime,
            "df": df
        }
        return df.copy()
        
    return cache_entry["df"].copy()

# RBAC 角色定義
ROLE_VIEWER = "Viewer"
ROLE_MANAGER = "Logistics_Manager"
ROLE_ENGINEER = "Engineer"
VALID_ROLES = {ROLE_VIEWER, ROLE_MANAGER, ROLE_ENGINEER}


# ── FastAPI 應用 ──────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """應用生命週期：啟動時初始化 DB 並啟動背景磁碟清理任務。

    取代已棄用的 @app.on_event("startup")，行為維持不變。
    """
    import asyncio

    init_db()

    async def cleanup_loop():
        while True:
            try:
                import time
                now = time.time()
                # 清理 predictions_session_*.csv
                if DATA_DIR.exists():
                    for f in DATA_DIR.glob("predictions_session_*.csv"):
                        if f.is_file() and (now - f.stat().st_mtime) > 86400:
                            try:
                                os.remove(f)
                                print(f"[Cleanup] 已刪除過期 session 檔案: {f.name}")
                            except Exception:
                                pass
                # 清理 retrain_temp/*
                temp_dir = DATA_DIR / "retrain_temp"
                if temp_dir.exists():
                    import shutil
                    for d in temp_dir.iterdir():
                        if d.is_dir() and (now - d.stat().st_mtime) > 86400:
                            try:
                                shutil.rmtree(d)
                                print(f"[Cleanup] 已刪除過期重訓 session 目錄: {d.name}")
                            except Exception:
                                pass
            except Exception as e:
                print(f"[Cleanup] 清理發生錯誤: {str(e)}")
            await asyncio.sleep(3600)

    task = asyncio.create_task(cleanup_loop())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(
    title="SLIDE — 供應鏈物流智慧調度引擎",
    description="DataCo 供應鏈 AI 預測與最佳化 API（含 RBAC）",
    version="1.0.0",
    lifespan=lifespan,
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


@app.get("/profit-prediction")
async def profit_prediction_page():
    return FileResponse(static_dir / "index.html")


def init_db():
    """初始化 SQLite 審計日誌資料表。"""
    try:
        import sqlite3
        from auth import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                operator TEXT NOT NULL,
                action TEXT NOT NULL,
                detail TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        conn.close()
        print("[DB] 審計日誌資料表已初始化。")
    except Exception as e:
        print(f"[DB] 審計日誌資料表初始化失敗: {str(e)}")


# ── Pydantic 模型 ─────────────────────────────────────────────────────────────


class OptimizeRequest(BaseModel):
    budget: float = 5000.0
    upgrade_cost: float = 80.0
    delay_penalty: float = 250.0
    risk_threshold: float = 0.3


class LLMBriefRequest(OptimizeRequest):
    language: str = "zh-TW"
    max_sample_orders: int = 3
    question: str = ""


class LLMSettingsRequest(BaseModel):
    provider: str = "openai"
    model: str = "gpt-4o-mini"
    api_key: str = ""
    api_url: str = ""


class FlagEventRequest(BaseModel):
    month: str
    event_type: str
    note: str = ""


class RetrainRequest(BaseModel):
    excluded_features: list = []


class RetrainSessionRequest(BaseModel):
    session_id: str


# ── 非同步模型重訓背景任務與雜湊輔助 ───────────────────────────────────────────

RETRAIN_TASKS: dict[str, dict] = {}

def get_file_hash(path: Path) -> str:
    """計算並回傳指定檔案的 SHA-256 雜湊值。"""
    if not path.exists():
        return ""
    import hashlib
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            h.update(f.read())
        return h.hexdigest()
    except Exception:
        return ""


def run_retrain_task(task_id: str, excluded_features: list):
    """背景執行緒：跑資料前處理與特徵工程，重新訓練 XGBoost。"""
    try:
        from retrainer import ModelRetrainer
        
        # 1. 記錄基礎模型的 SHA-256 雜湊（用於 adopt 時的併發寫入版本控制）
        model_path = BASE_DIR / "models" / "xgboost_model.json"
        base_hash = get_file_hash(model_path)
        RETRAIN_TASKS[task_id]["base_model_hash"] = base_hash
        RETRAIN_TASKS[task_id]["progress"] = 15
        RETRAIN_TASKS[task_id]["log"] = "已載入重訓參數，開始讀取原始資料集..."

        retrainer = ModelRetrainer(base_dir=BASE_DIR)
        RETRAIN_TASKS[task_id]["progress"] = 45
        RETRAIN_TASKS[task_id]["log"] = "正在進行特徵工程與特徵刪除處理..."
        
        # 呼叫重訓（會進行資料分割、XGBoost 訓練與指標計算）
        result = retrainer.run(excluded_features=excluded_features)
        
        RETRAIN_TASKS[task_id]["progress"] = 90
        RETRAIN_TASKS[task_id]["log"] = "重訓結束，正在儲存暫存模型指標並封裝..."
        
        RETRAIN_TASKS[task_id]["result"] = {
            "session_id":      result["session_id"],
            "old_metrics":     result["old_metrics"],
            "new_metrics":     result["new_metrics"],
            "dropped_columns": result["dropped_columns"],
        }
        RETRAIN_TASKS[task_id]["status"] = "success"
        RETRAIN_TASKS[task_id]["progress"] = 100
        RETRAIN_TASKS[task_id]["log"] = "XGBoost 模型重訓順利完成，新舊模型對比就緒。"
        
    except Exception as e:
        import traceback
        error_msg = f"模型訓練失敗：{str(e)}\n\n詳細呼叫堆疊：\n{traceback.format_exc()}"
        RETRAIN_TASKS[task_id]["status"] = "failed"
        RETRAIN_TASKS[task_id]["error"] = str(e)
        RETRAIN_TASKS[task_id]["log"] = error_msg


def make_display_order_id(order_id: object) -> str:

    """Return a short manager-friendly display ID while preserving the hash in APIs."""
    if order_id is None:
        return "ORD-UNKNOWN"
    compact = "".join(ch for ch in str(order_id).upper() if ch.isalnum())
    # 取前 8 碼：6 碼在 ~2.8 萬筆訂單會有約 0.16% 撞號，8 碼幾乎不撞號（顯示與搜尋一致）
    return f"ORD-{compact[:8]}" if compact else "ORD-UNKNOWN"


def _safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _threshold_metrics(
    actual: pd.Series,
    probability: pd.Series,
    threshold: float,
    upgrade_cost: float = 80.0,
    delay_penalty: float = 250.0,
) -> dict:
    predicted = probability >= threshold
    tp = int(((actual == 1) & predicted).sum())
    tn = int(((actual == 0) & (~predicted)).sum())
    fp = int(((actual == 0) & predicted).sum())
    fn = int(((actual == 1) & (~predicted)).sum())

    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)
    f1 = _safe_div(2 * precision * recall, precision + recall)
    selected_count = int(predicted.sum())
    expected_cost = (fp * upgrade_cost) + (fn * delay_penalty)

    return {
        "threshold": round(float(threshold), 4),
        "precision": round(float(precision), 4),
        "recall": round(float(recall), 4),
        "f1": round(float(f1), 4),
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "selected_count": selected_count,
        "upgrade_spend": round(float(selected_count * upgrade_cost), 2),
        "expected_cost": round(float(expected_cost), 2),
    }


# ── RBAC 工具函數 ─────────────────────────────────────────────────────────────

from auth import verify_token

def get_role(x_role: Optional[str] = None, authorization: Optional[str] = None) -> str:
    """
    從 HTTP Header Authorization (JWT Bearer Token) 或 X-Role 取得角色。
    優先校驗 JWT Token，安全防禦加固。
    """
    if authorization:
        try:
            if authorization.startswith("Bearer "):
                token = authorization[7:]
            else:
                token = authorization
            result = verify_token(token)
            if result["success"]:
                return result["role"]
        except Exception:
            pass

    if x_role and x_role in VALID_ROLES:
        return x_role
    return ROLE_VIEWER


def get_predictions_path(x_session_id: Optional[str] = None) -> Path:
    """
    根據 X-Session-ID Header 回傳對應的 CSV 預測資料路徑。
    若該 Session 專屬檔案不存在，則 fallback 回傳預設驗證集 predictions.csv。
    """
    if x_session_id:
        safe_id = "".join(c for c in x_session_id if c.isalnum() or c in ("-", "_"))
        if safe_id:
            session_file = DATA_DIR / f"predictions_session_{safe_id}.csv"
            if session_file.exists():
                return session_file
    return PREDICTIONS_PATH


def require_manager(role: str) -> None:
    """
    要求呼叫者必須是 Logistics_Manager 或 Engineer。
    否則拋出 403 Forbidden。
    """
    if role not in (ROLE_MANAGER, ROLE_ENGINEER):
        raise HTTPException(
            status_code=403,
            detail={
                "error": "403 Forbidden",
                "message": "此端點僅限 Logistics_Manager 或 Engineer 存取。Viewer 無執行最佳化的權限。",
                "your_role": role,
            },
        )


def load_model_metrics() -> dict:
    if not METRICS_PATH.exists():
        return {}
    try:
        with open(METRICS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def attach_manager_analysis(result_dict: dict, pred_path: Path) -> dict:
    """Attach de-identified manager-facing analysis to an optimization result."""
    try:
        from explainer import ManagerExplainer

        df = load_cached_predictions(pred_path)
        explainer = ManagerExplainer(df, load_model_metrics())
        result_dict["manager_analysis"] = explainer.summarize_optimization(result_dict)
    except Exception as e:
        result_dict["manager_analysis"] = {
            "headline": f"最佳化建議（無法載入分析器：{str(e)}）",
            "recommended_policy": "優先處理高風險與正淨效益訂單",
            "sample_order_explanations": [],
            "llm_ready_prompt": "",
        }
    return result_dict


def build_optimization_result(request: OptimizeRequest, pred_path: Path, save_results: bool) -> dict:
    if not pred_path.exists():
        return {
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
            "manager_analysis": {
                "headline": "示範資料：建議主管核准高風險且淨效益為正的訂單升級。",
                "recommended_policy": "優先升級高風險與正淨效益訂單。",
                "sample_order_explanations": [],
                "llm_ready_prompt": "請根據示範最佳化結果產生主管摘要。",
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
        risk_threshold=request.risk_threshold,
    )
    result = optimizer.run(
        predictions_path_or_df=str(pred_path),
        output_dir=str(DATA_DIR),
        save_results=save_results,
    )
    return attach_manager_analysis(result.to_dict(), pred_path)


def display_order_id(order_id_hash: str) -> str:
    raw = re.sub(r"[^a-zA-Z0-9]", "", str(order_id_hash or "")).upper()
    return f"ORD-{raw[:8]}" if raw else "ORD-UNKNOWN"


def find_order_context_for_question(question: str, pred_path: Path) -> dict | None:
    """Return one de-identified order row when the user names an order hash/display ID."""
    text = (question or "").upper()
    if not text or not pred_path.exists():
        return None

    try:
        df = load_cached_predictions(pred_path)
    except Exception:
        return None

    for _, row in df.iterrows():
        order_hash = str(row.get("order_id_hash", ""))
        display_id = display_order_id(order_hash)
        hash_token = re.sub(r"[^a-zA-Z0-9]", "", order_hash).upper()
        if display_id in text or (hash_token and hash_token[:8] in text):
            p_late = float(row.get("p_late") or 0)
            return {
                "order_id_hash": order_hash,
                "display_order_id": display_id,
                "shipping_mode": row.get("shipping_mode"),
                "order_region": row.get("order_region"),
                "order_date": row.get("order_date"),
                "p_late": p_late,
                "risk_bucket": row.get("risk_bucket"),
                "expected_penalty": float(row.get("expected_penalty") or 0),
                "upgrade_cost": float(row.get("upgrade_cost") or 0),
            }
    return None


def build_llm_safe_payload(
    optimization_result: dict,
    max_sample_orders: int = 3,
    order_context: dict | None = None,
) -> dict:
    """Keep the LLM boundary limited to de-identified and aggregate fields."""
    manager_analysis = optimization_result.get("manager_analysis", {}) or {}
    samples = []
    for item in manager_analysis.get("sample_order_explanations", [])[:max(0, max_sample_orders)]:
        samples.append({
            "order_id_hash": item.get("order_id_hash"),
            "risk_bucket": item.get("risk_bucket"),
            "p_late": item.get("p_late"),
            "recommended_action": item.get("recommended_action"),
            "expected_penalty": item.get("expected_penalty"),
            "upgrade_cost": item.get("upgrade_cost"),
            "net_benefit": item.get("net_benefit"),
            "top_x_factors": item.get("top_x_factors", [])[:3],
            "manager_summary": item.get("manager_summary"),
        })

    return {
        "data_policy": {
            "de_identified_only": True,
            "excluded_fields": [
                "customer_name",
                "email",
                "phone",
                "address",
                "raw_order_id",
                "payment_info",
                "password",
            ],
        },
        "optimization": {
            "budget": optimization_result.get("budget"),
            "selected_count": optimization_result.get("selected_count"),
            "total_cost": optimization_result.get("total_cost"),
            "expected_total_saving": optimization_result.get("expected_total_saving"),
            "expected_total_penalty_avoided": optimization_result.get("expected_total_penalty_avoided"),
            "solver": optimization_result.get("solver"),
        },
        "manager_analysis": {
            "headline": manager_analysis.get("headline"),
            "recommended_policy": manager_analysis.get("recommended_policy"),
            "budget_usage_pct": manager_analysis.get("budget_usage_pct"),
            "sample_order_explanations": samples,
        },
        "requested_order": order_context,
    }


SLIDE_LLM_SYSTEM_PROMPT = """
你正在角色扮演 SLIDE 供應鏈物流智慧調度引擎裡的 AI 助理。

你熟悉這個介面：Dashboard、風險訂單列表、最佳化調度、AI 助理、模型效能、區域風險地圖、RBAC 權限、LLM 設定。使用者問怎麼操作時，你就像坐在旁邊帶他用系統一樣回答。

你也熟悉物流主管會關心的問題：哪些訂單可能延遲、為什麼風險高、預算有限時要先救哪些訂單、是否升級運送、單筆訂單目前狀況如何、模型和 X 因子代表什麼。

回答時請自然一點，不要每次固定三段式，也不要像文件。可以先簡短寒暄，再根據使用者問題給出清楚、可執行的說明。使用繁體中文。

若提供的資料裡有 requested_order 或 sample_order_explanations，就用它們回答單筆訂單或範例訂單；若資料不足，就用系統操作角度告訴使用者下一步可以去哪裡看或先做什麼。
""".strip()


def build_llm_prompt(safe_payload: dict, language: str = "zh-TW", question: str = "") -> str:
    question_text = question.strip() or "請用自然的方式說明目前這批訂單可以怎麼判讀。"
    return (
        "請進入 SLIDE AI 助理角色，直接回答使用者。"
        f"請使用語言：{language}。\n"
        f"使用者問題：{question_text}\n\n"
        f"目前可參考的系統資料：{json.dumps(safe_payload, ensure_ascii=False, default=str)}"
    )

def is_logistics_question(question: str) -> bool:
    """Return True when the user asks about EDIS logistics decision context."""
    text = (question or "").strip().lower()
    if not text:
        return True

    allowed_terms = [
        "物流", "訂單", "延遲", "準時", "配送", "運送", "調度", "升級", "風險",
        "預測", "機率", "模型", "門檻", "預算", "成本", "罰金", "損失", "效益",
        "介面", "頁面", "使用", "操作", "設定", "權限", "助理", "儀表板",
        "風險清單", "模型效能", "區域風險", "地圖", "rbac",
        "roi", "sla", "x因子", "x 因子", "lime", "region", "shipping", "budget",
        "risk", "delay", "late", "delivery", "shipment", "order", "optimize",
        "optimization", "predict", "prediction", "model", "threshold", "penalty",
        "cost", "route", "dispatch", "upgrade", "dashboard", "settings", "permission",
        "viewer", "manager", "interface", "page",
    ]
    return any(term in text for term in allowed_terms)


def off_topic_llm_response(question: str) -> str:
    return (
        "我只能回答與目前訂單預測、延遲風險、物流調度、預算最佳化、模型門檻與 X 因子解釋相關的問題。\n"
        "請改問例如：「這批訂單哪些最該優先處理？」、「為什麼延遲風險高？」或「預算有限時該怎麼調度？」"
    )


def local_llm_fallback(safe_payload: dict, question: str = "") -> str:
    opt = safe_payload.get("optimization", {})
    analysis = safe_payload.get("manager_analysis", {})
    requested_order = safe_payload.get("requested_order") or {}
    q = (question or "").strip().lower()
    budget = float(opt.get("budget") or 0)
    selected_count = int(opt.get("selected_count") or 0)
    saving = float(opt.get("expected_total_saving") or 0)
    total_cost = float(opt.get("total_cost") or 0)

    if q in {"你好", "嗨", "hi", "hello", "哈囉"}:
        return (
            "嗨，我在。你可以直接問我這批訂單怎麼看、預算有限時怎麼排，"
            "或貼一個訂單編號，我會用目前系統裡的預測與最佳化結果幫你判斷。"
        )

    if requested_order:
        return (
            f"這筆 {requested_order.get('display_order_id')} 我會先看成需要留意的訂單。它目前預測延遲機率約 "
            f"{float(requested_order.get('p_late') or 0) * 100:.1f}%，"
            f"風險分級是 {requested_order.get('risk_bucket') or '未分級'}。"
            f"運送模式為 {requested_order.get('shipping_mode') or '未知'}，"
            f"目的地區域是 {requested_order.get('order_region') or '未知'}。"
            f"如果要不要升級，關鍵是拿預估延遲罰金 USD ${float(requested_order.get('expected_penalty') or 0):,.0f} "
            f"去和升級成本 USD ${float(requested_order.get('upgrade_cost') or 0):,.0f} 比；"
            "建議你再點開這筆訂單的 X 因子，看它是被運送模式、區域還是其他因素拉高。"
        )

    if any(term in q for term in ["預算", "budget", "有限", "調度", "怎麼排", "怎麼調"]):
        return (
            f"如果預算有限，我會先把錢放在「高延遲風險，而且升級後淨效益為正」的訂單上。"
            f"以目前設定來看，預算大約 USD ${budget:,.0f}，系統挑出 {selected_count} 筆可升級訂單，"
            f"會把預算用到約 USD ${total_cost:,.0f}，預估淨效益約 USD ${saving:,.0f}。\n\n"
            f"實務上我會建議你先不要平均分配，而是照延遲機率、預估罰金、升級成本三個條件排序；"
            f"如果預算再縮小，就從淨效益最低的訂單往後砍，保留最能保護 SLA 的那一批。"
        )

    return (
        f"目前這批訂單的方向是：{analysis.get('headline') or '先處理高風險且淨效益為正的訂單'}。"
        f"以 USD ${budget:,.0f} 的預算來看，系統會挑出 {selected_count} 筆訂單，"
        f"預估淨效益約 USD ${saving:,.0f}。"
        f"{analysis.get('recommended_policy') or '你可以接著到最佳化調度頁調整預算，看看少一點或多一點預算時名單怎麼變。'}"
    )


class _WinDataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.c_ulong),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _dpapi_protect(secret: str) -> str:
    data = secret.encode("utf-8")
    in_buffer = ctypes.create_string_buffer(data)
    in_blob = _WinDataBlob(len(data), ctypes.cast(in_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    out_blob = _WinDataBlob()

    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        "EDIS LLM API key",
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise RuntimeError("Windows DPAPI 加密失敗。")
    try:
        protected = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        return base64.b64encode(protected).decode("ascii")
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)


def _dpapi_unprotect(protected_b64: str) -> str:
    protected = base64.b64decode(protected_b64.encode("ascii"))
    in_buffer = ctypes.create_string_buffer(protected)
    in_blob = _WinDataBlob(len(protected), ctypes.cast(in_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    out_blob = _WinDataBlob()

    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise RuntimeError("Windows DPAPI 解密失敗。")
    try:
        data = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        return data.decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)


def _derive_secret_stream(secret: str, salt: bytes, length: int) -> bytes:
    stream = bytearray()
    counter = 0
    key = hashlib.sha256(secret.encode("utf-8")).digest()
    while len(stream) < length:
        counter_bytes = counter.to_bytes(4, "big")
        stream.extend(hmac.new(key, salt + counter_bytes, hashlib.sha256).digest())
        counter += 1
    return bytes(stream[:length])


def _env_secret_protect(secret: str) -> str:
    config_secret = os.environ.get("SLIDE_LLM_CONFIG_SECRET", "")
    if not config_secret:
        raise RuntimeError("非 Windows 環境需設定 SLIDE_LLM_CONFIG_SECRET 才能加密儲存 API key。")
    salt = os.urandom(16)
    data = secret.encode("utf-8")
    stream = _derive_secret_stream(config_secret, salt, len(data))
    cipher = bytes(a ^ b for a, b in zip(data, stream))
    tag = hmac.new(hashlib.sha256(config_secret.encode("utf-8")).digest(), salt + cipher, hashlib.sha256).digest()
    return base64.b64encode(salt + tag + cipher).decode("ascii")


def _env_secret_unprotect(protected_b64: str) -> str:
    config_secret = os.environ.get("SLIDE_LLM_CONFIG_SECRET", "")
    if not config_secret:
        raise RuntimeError("缺少 SLIDE_LLM_CONFIG_SECRET，無法解密 API key。")
    raw = base64.b64decode(protected_b64.encode("ascii"))
    salt, tag, cipher = raw[:16], raw[16:48], raw[48:]
    key = hashlib.sha256(config_secret.encode("utf-8")).digest()
    expected_tag = hmac.new(key, salt + cipher, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected_tag):
        raise RuntimeError("API key 加密資料驗證失敗。")
    stream = _derive_secret_stream(config_secret, salt, len(cipher))
    return bytes(a ^ b for a, b in zip(cipher, stream)).decode("utf-8")


def protect_api_key(api_key: str) -> dict:
    api_key = str(api_key or "").strip()
    if not api_key:
        return {}
    if os.name == "nt":
        return {
            "api_key_storage": "windows_dpapi_user",
            "api_key_protected": _dpapi_protect(api_key),
        }
    return {
        "api_key_storage": "env_secret_v1",
        "api_key_protected": _env_secret_protect(api_key),
    }


def unprotect_api_key(config: dict) -> str:
    protected = config.get("api_key_protected")
    storage = config.get("api_key_storage")
    if protected and storage == "windows_dpapi_user":
        return _dpapi_unprotect(str(protected))
    if protected and storage == "env_secret_v1":
        return _env_secret_unprotect(str(protected))
    return str(config.get("api_key") or "").strip()


def read_llm_runtime_config() -> dict:
    if not LLM_RUNTIME_CONFIG_PATH.exists():
        return {}
    try:
        with open(LLM_RUNTIME_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        try:
            data["api_key"] = unprotect_api_key(data)
        except Exception as e:
            print(f"[LLM Config] API Key 解密失敗（可能是 Windows 使用者帳號不同）：{e}")
            data["api_key"] = ""
            data["api_key_decrypt_error"] = str(e)
        if data.get("api_key") and not data.get("api_key_protected"):
            write_llm_runtime_config(data)
        return data
    except Exception:
        return {}


def write_llm_runtime_config(config: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    allowed = {"provider", "model", "api_url"}
    clean = {k: str(v or "").strip() for k, v in config.items() if k in allowed}
    clean.update(protect_api_key(str(config.get("api_key") or "")))
    with open(LLM_RUNTIME_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(clean, f, ensure_ascii=False, indent=2)


def mask_secret(value: str) -> str:
    value = str(value or "")
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def get_llm_config() -> dict:
    """
    Read the backend-wide LLM provider settings.

    Configure before starting uvicorn:
      SLIDE_LLM_PROVIDER=local|openai|openai_compatible|gemini|claude|ollama
      SLIDE_LLM_MODEL=<provider model name>
      SLIDE_LLM_API_KEY=<provider API key>
      SLIDE_LLM_API_URL=<optional custom endpoint>
    """
    runtime_config = read_llm_runtime_config()
    provider = (runtime_config.get("provider") or os.environ.get("SLIDE_LLM_PROVIDER", "")).strip().lower()
    if not provider:
        provider = "openai" if (os.environ.get("SLIDE_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")) else "local"

    provider_keys = {
        "openai": os.environ.get("OPENAI_API_KEY"),
        "openai_compatible": os.environ.get("OPENAI_API_KEY"),
        "gemini": os.environ.get("GEMINI_API_KEY"),
        "claude": os.environ.get("ANTHROPIC_API_KEY"),
        "ollama": "",
        "local": "",
    }
    api_key = runtime_config.get("api_key") or os.environ.get("SLIDE_LLM_API_KEY") or provider_keys.get(provider, "")

    default_models = {
        "openai": "gpt-4o-mini",
        "openai_compatible": "gpt-4o-mini",
        "gemini": "gemini-1.5-flash",
        "claude": "claude-3-haiku-20240307",
        "ollama": "llama3.1",
        "local": None,
    }
    default_urls = {
        "openai": "https://api.openai.com/v1/responses",
        "openai_compatible": "https://api.openai.com/v1/chat/completions",
        "gemini": None,
        "claude": "https://api.anthropic.com/v1/messages",
        "ollama": "http://localhost:11434/api/chat",
        "local": None,
    }

    configured_api_url = runtime_config.get("api_url") or os.environ.get("SLIDE_LLM_API_URL") or default_urls.get(provider)
    if provider == "openai" and configured_api_url == "https://api.openai.com/v1/chat/completions":
        configured_api_url = default_urls["openai"]

    return {
        "provider": provider,
        "api_key": api_key,
        "api_url": configured_api_url,
        "model": runtime_config.get("model") or os.environ.get("SLIDE_LLM_MODEL") or default_models.get(provider),
        "source": "manager_ui" if runtime_config else "environment",
    }


def get_public_llm_config() -> dict:
    config = get_llm_config()
    api_key_set = bool(config["api_key"]) and config["provider"] not in {"local", "ollama"}
    return {
        "provider": config["provider"],
        "model": config["model"],
        "api_url": config["api_url"] or "",
        "api_key_set": api_key_set,
        "api_key_masked": mask_secret(config["api_key"]) if api_key_set else "",
        "source": config.get("source", "environment"),
    }


def _llm_fallback(provider: str, model: str | None, fallback_text: str, error: str | None = None) -> dict:
    return {
        "used_external_llm": False,
        "provider": "local_fallback",
        "configured_provider": provider,
        "model": model,
        "response_id": None,
        "brief_text": fallback_text,
        "error": error,
    }


def call_configured_llm(prompt: str, fallback_text: str, max_tokens: int = 400) -> dict:
    config = get_llm_config()
    provider = config["provider"]
    api_key = config["api_key"]
    api_url = config["api_url"]
    model = config["model"]

    if provider == "local":
        return _llm_fallback(provider, model, fallback_text)
    if provider not in {"openai", "openai_compatible", "gemini", "claude", "ollama"}:
        return _llm_fallback(provider, model, fallback_text, f"不支援的 LLM provider：{provider}")
    if provider != "ollama" and not api_key:
        return _llm_fallback(provider, model, fallback_text, f"{provider} 未設定 API key。")

    try:
        from urllib.parse import quote
        from urllib.request import Request as UrlRequest, urlopen

        if provider == "openai":
            response_id = None
            body = json.dumps({
                "model": model,
                "input": [
                    {
                        "role": "system",
                        "content": SLIDE_LLM_SYSTEM_PROMPT,
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.7,
                "max_output_tokens": max_tokens,
            }).encode("utf-8")
            req = UrlRequest(
                api_url,
                data=body,
                method="POST",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
            with urlopen(req, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
            response_id = payload.get("id")
            text = payload.get("output_text", "").strip()
            if not text:
                chunks = []
                for item in payload.get("output", []):
                    for content in item.get("content", []):
                        if content.get("type") in {"output_text", "text"}:
                            chunks.append(content.get("text", ""))
                text = "".join(chunks).strip()

        elif provider == "openai_compatible":
            response_id = None
            body = json.dumps({
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": SLIDE_LLM_SYSTEM_PROMPT,
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
                "max_tokens": max_tokens,
            }).encode("utf-8")
            req = UrlRequest(
                api_url,
                data=body,
                method="POST",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
            with urlopen(req, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
            response_id = payload.get("id")
            text = payload["choices"][0]["message"]["content"].strip()

        elif provider == "gemini":
            response_id = None
            gemini_url = api_url or f"https://generativelanguage.googleapis.com/v1beta/models/{quote(model)}:generateContent?key={api_key}"
            body = json.dumps({
                "systemInstruction": {"parts": [{"text": SLIDE_LLM_SYSTEM_PROMPT}]},
                "contents": [
                    {"parts": [{"text": prompt}]}
                ],
                "generationConfig": {"temperature": 0.2, "maxOutputTokens": max_tokens},
            }).encode("utf-8")
            req = UrlRequest(
                gemini_url,
                data=body,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urlopen(req, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
            text = payload["candidates"][0]["content"]["parts"][0]["text"].strip()

        elif provider == "claude":
            response_id = None
            body = json.dumps({
                "model": model,
                "max_tokens": max_tokens,
                "temperature": 0.2,
                "system": SLIDE_LLM_SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": prompt}],
            }).encode("utf-8")
            req = UrlRequest(
                api_url,
                data=body,
                method="POST",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": os.environ.get("SLIDE_LLM_ANTHROPIC_VERSION", "2023-06-01"),
                    "Content-Type": "application/json",
                },
            )
            with urlopen(req, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
            response_id = payload.get("id")
            text = "".join(block.get("text", "") for block in payload.get("content", [])).strip()

        else:  # ollama
            response_id = None
            body = json.dumps({
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": SLIDE_LLM_SYSTEM_PROMPT,
                    },
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "options": {"num_predict": max_tokens},
            }).encode("utf-8")
            req = UrlRequest(
                api_url,
                data=body,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urlopen(req, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            text = payload["message"]["content"].strip()

        return {
            "used_external_llm": True,
            "provider": provider,
            "configured_provider": provider,
            "model": model,
            "response_id": response_id,
            "brief_text": text,
            "error": None,
        }
    except Exception as e:
        error_text = str(e)
        if hasattr(e, "read"):
            try:
                body_text = e.read().decode("utf-8", errors="replace")
                if body_text:
                    error_text = f"{error_text} | {body_text[:600]}"
            except Exception:
                pass
        return _llm_fallback(provider, model, fallback_text, f"LLM 呼叫失敗：{error_text}")


# ── AI 助理意圖路由 ───────────────────────────────────────────────────────────

_ORD_RE = re.compile(r"ORD-[A-Z0-9]{8}", re.IGNORECASE)
_TOP_N_RE = re.compile(r"前\s*(\d+)|top\s*(\d+)", re.IGNORECASE)


def route_assistant_intent(question: str) -> tuple[str, dict]:
    q = question.strip().lower()

    if _ORD_RE.search(question):
        return ("order_lookup", {"raw_question": question})

    if any(t in q for t in ["高風險", "風險最高", "前幾", "最可能", "延遲最高", "優先", "排行", "排序", "top"]):
        m = _TOP_N_RE.search(question)
        n = int(m.group(1) or m.group(2)) if m else 10
        return ("risk_ranking", {"top_n": n})

    if any(t in q for t in ["預算", "budget", "最佳化", "省錢", "有限", "怎麼排", "怎麼調", "調度"]):
        return ("budget_optimize", {})

    _region_names = [
        "east asia", "northern europe", "south asia", "north america", "latin america",
        "western europe", "western us", "eastern us", "central america", "africa",
        "oceania", "middle east",
        "亞洲", "歐洲", "美洲", "非洲", "中東", "南亞", "東亞", "北美",
    ]
    if any(t in q for t in ["地區", "區域", "region", "篩選", "shipping", "運送方式", "類別"] + _region_names):
        return ("filter", {"raw_question": question})

    return ("general", {"raw_question": question})


def fetch_intent_payload(intent: str, params: dict, pred_path: "Path", request) -> dict:
    if intent == "risk_ranking":
        df = load_cached_predictions(pred_path)
        top_n = params.get("top_n", 10)
        high_risk = df[df["p_late"] >= 0.5].nlargest(top_n, "p_late")
        total_high = int((df["p_late"] >= 0.5).sum())
        orders = [
            {
                "display_id": display_order_id(str(row.get("order_id_hash", ""))),
                "p_late": round(float(row.get("p_late", 0)), 3),
                "order_region": row.get("order_region"),
                "shipping_mode": row.get("shipping_mode"),
                "expected_penalty": round(float(row.get("expected_penalty", 0)), 2),
                "upgrade_cost": round(float(row.get("upgrade_cost", 0)), 2),
            }
            for _, row in high_risk.iterrows()
        ]
        return {"intent": "risk_ranking", "top_n": top_n, "total_high_risk": total_high, "orders": orders}

    if intent == "order_lookup":
        order_ctx = find_order_context_for_question(params.get("raw_question", ""), pred_path)
        return {"intent": "order_lookup", "order": order_ctx}

    if intent == "budget_optimize":
        opt = build_optimization_result(request, pred_path, save_results=False)
        analysis = opt.get("manager_analysis", {}) or {}
        return {
            "intent": "budget_optimize",
            "budget": opt.get("budget"),
            "selected_count": opt.get("selected_count"),
            "total_cost": opt.get("total_cost"),
            "expected_total_saving": opt.get("expected_total_saving"),
            "headline": analysis.get("headline"),
            "recommended_policy": analysis.get("recommended_policy"),
            "budget_usage_pct": analysis.get("budget_usage_pct"),
        }

    if intent == "filter":
        df = load_cached_predictions(pred_path)
        q = params.get("raw_question", "").lower()
        mask = df["order_region"].notna()
        for kw in ["east asia", "northern europe", "south asia", "north america", "latin america"]:
            if kw in q:
                mask = df["order_region"].str.lower().str.contains(kw, na=False)
                break
        else:
            for kw in ["亞洲", "歐洲", "美洲", "非洲"]:
                if kw in q:
                    mask = df["order_region"].str.contains(kw, na=False)
                    break
        filtered = df[mask]
        top10 = filtered.nlargest(10, "p_late")
        orders = [
            {
                "display_id": display_order_id(str(row.get("order_id_hash", ""))),
                "p_late": round(float(row.get("p_late", 0)), 3),
                "order_region": row.get("order_region"),
                "expected_penalty": round(float(row.get("expected_penalty", 0)), 2),
            }
            for _, row in top10.iterrows()
        ]
        return {"intent": "filter", "total": len(filtered), "orders": orders}

    return {"intent": "general", "raw_question": params.get("raw_question", "")}


def format_intent_card(intent: str, data: dict) -> str:
    if intent == "risk_ranking":
        total = data.get("total_high_risk", 0)
        orders = data.get("orders", [])
        lines = [f"【結論】目前高風險訂單共 {total:,} 筆（p≥0.5），建議優先處理前 {len(orders)} 筆：", "【清單】"]
        for i, o in enumerate(orders, 1):
            lines.append(
                f"  {i}. {o['display_id']}  p={o['p_late']:.2f}  {o.get('order_region', '')}  "
                f"罰款${o['expected_penalty']:,.0f}  → 建議升級"
            )
        remaining = total - len(orders)
        if remaining > 0:
            lines.append(f"  …（另有 {remaining:,} 筆未列）")
        lines.append(f"【下一步】輸入預算可直接給最佳分配方案，或說「East Asia 前 5」篩選。")
        return "\n".join(lines)

    if intent == "order_lookup":
        o = data.get("order")
        if not o:
            return "【結論】找不到該訂單，請確認 ORD- 格式是否正確。\n【下一步】試試直接貼上 ORD-XXXXXXXX 格式的編號。"
        action = "建議升級" if float(o.get("upgrade_cost", 0)) < float(o.get("expected_penalty", 0)) else "暫不升級（升級成本較高）"
        return (
            f"【結論】{o['display_id']} 延遲機率 {float(o['p_late']) * 100:.1f}%，"
            f"風險等級：{o.get('risk_bucket', '未知')}。\n"
            f"【明細】地區：{o.get('order_region')}  運送：{o.get('shipping_mode')}\n"
            f"        罰款預估 ${float(o.get('expected_penalty', 0)):,.0f}  "
            f"升級成本 ${float(o.get('upgrade_cost', 0)):,.0f}  → {action}\n"
            f"【下一步】點開該訂單 X 因子可看延遲主因，或詢問其他訂單。"
        )

    if intent == "budget_optimize":
        return (
            f"【結論】預算 ${float(data.get('budget') or 0):,.0f}，"
            f"系統挑出 {data.get('selected_count', 0)} 筆可升級，"
            f"預估淨效益 ${float(data.get('expected_total_saving') or 0):,.0f}。\n"
            f"【明細】{data.get('headline', '')}\n"
            f"【下一步】{data.get('recommended_policy', '可至最佳化頁調整預算看名單變化。')}"
        )

    if intent == "filter":
        orders = data.get("orders", [])
        total = data.get("total", 0)
        lines = [f"【結論】共 {total:,} 筆符合條件，顯示前 {len(orders)} 筆：", "【清單】"]
        for i, o in enumerate(orders, 1):
            lines.append(
                f"  {i}. {o['display_id']}  p={o['p_late']:.2f}  "
                f"{o.get('order_region', '')}  罰款${o['expected_penalty']:,.0f}"
            )
        lines.append("【下一步】可進一步指定預算或其他條件縮小範圍。")
        return "\n".join(lines)

    return (
        "【結論】我可以回答以下類型的問題：\n"
        "【清單】\n"
        "  1. 高風險排序：「前10筆最可能延遲的訂單」\n"
        "  2. 預算最佳化：「預算有限時怎麼調度？」\n"
        "  3. 訂單查詢：貼上 ORD-XXXXXXXX 格式編號\n"
        "  4. 條件篩選：「East Asia 高風險訂單」\n"
        "【下一步】請換一種方式描述，或直接貼訂單編號。"
    )


# ── 路由 ──────────────────────────────────────────────────────────────────────


# ── 登入驗證 ──────────────────────────────────────────────────────────────────
from auth import init_db, verify_user, generate_token

init_db()

class LoginRequest(BaseModel):
    username: str
    password: str


class SingleOrderPredictRequest(BaseModel):
    """即時單筆訂單延遲預測請求模型。"""
    shipping_mode: str = "Standard Class"      # First Class / Same Day / Second Class / Standard Class
    order_region: str = "Western Europe"       # 23 個區域之一
    order_country: str = "Francia"             # 國家（選填，預設法國）
    days_for_shipment: float = 4.0             # 預計配送天數
    product_price: float = 59.99              # 商品單價（USD）
    order_item_quantity: int = 1               # 訂購數量
    customer_segment: str = "Consumer"        # Consumer / Corporate / Home Office
    department_name: str = "Fan Shop"         # 部門名稱（選填）
    market: str = "Europe"                    # Africa / Europe / LATAM / Pacific Asia / USCA
    category_name: Optional[str] = None       # 品類名稱（選填，What-if 傳入）
    order_date: Optional[str] = None          # 訂單日期（YYYY-MM-DD，選填）
    order_item_discount_rate: Optional[float] = None   # 折扣率（0~1，選填）
    order_item_profit_ratio: Optional[float] = None    # 利潤率（選填）
    order_profit_per_order: Optional[float] = None     # 每單利潤（選填）


@app.post("/api/predict-single")
def predict_single_order(
    body: SingleOrderPredictRequest,
    x_role: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """
    [Viewer/Manager] 即時單筆訂單延遲機率預測。
    接收關鍵訂單欄位，其餘特徵以 serving_artifacts.json 訓練中位數填補，
    使用 XGBoost 模型推論，回傳延遲機率、風險等級與預估罰金。
    """
    try:
        import xgboost as xgb
    except ImportError:
        raise HTTPException(status_code=500, detail="XGBoost 未安裝，無法執行預測。")

    # 讀取特徵對應表
    mapping_path = BASE_DIR / "models" / "feature_mapping.json"
    artifact_path = BASE_DIR / "models" / "serving_artifacts.json"
    model_path    = BASE_DIR / "models" / "xgboost_model.json"

    if not mapping_path.exists() or not model_path.exists():
        raise HTTPException(status_code=500, detail="模型檔案不存在，請先執行 model_pipeline.py。")

    with open(mapping_path, "r", encoding="utf-8") as f:
        mappings = json.load(f)

    serving_medians: dict = {}
    serving_label_classes: dict = {}
    if artifact_path.exists():
        try:
            with open(artifact_path, "r", encoding="utf-8") as f:
                _art = json.load(f)
            serving_medians = _art.get("feature_medians", {}) or {}
            serving_label_classes = _art.get("label_classes", {}) or {}
        except Exception:
            pass

    feature_cols: list = mappings.get("feature_columns", [])

    # ── 建立特徵向量（與 preprocessor.py 邏輯一致）──────────────────
    import numpy as np
    X: dict = {}

    # 1. 數值特徵（缺值用訓練中位數填補）
    num_defaults = {
        "Days for shipment (scheduled)": body.days_for_shipment,
        "Product Price":                  body.product_price,
        "Order Item Quantity":            float(body.order_item_quantity),
        "Order Item Discount Rate":       body.order_item_discount_rate
                                          if body.order_item_discount_rate is not None
                                          else serving_medians.get("Order Item Discount Rate", 0.1),
        "Order Item Profit Ratio":        body.order_item_profit_ratio
                                          if body.order_item_profit_ratio is not None
                                          else serving_medians.get("Order Item Profit Ratio", 0.27),
        "Order Profit Per Order":         body.order_profit_per_order
                                          if body.order_profit_per_order is not None
                                          else serving_medians.get("Order Profit Per Order", 31.52),
    }
    for col, val in num_defaults.items():
        X[col] = float(val if val is not None else serving_medians.get(col, 0.0))

    # 2. 時間特徵
    if body.order_date:
        try:
            dt = pd.to_datetime(body.order_date, errors="coerce")
            X["order_dayofweek"]  = int(dt.dayofweek)  if not pd.isnull(dt) else int(serving_medians.get("order_dayofweek", 3))
            X["order_month"]      = int(dt.month)      if not pd.isnull(dt) else int(serving_medians.get("order_month", 6))
            X["order_hour"]       = int(dt.hour)       if not pd.isnull(dt) else int(serving_medians.get("order_hour", 11))
            X["order_is_weekend"] = int(dt.dayofweek >= 5) if not pd.isnull(dt) else 0
        except Exception:
            X["order_dayofweek"]  = int(serving_medians.get("order_dayofweek", 3))
            X["order_month"]      = int(serving_medians.get("order_month", 6))
            X["order_hour"]       = int(serving_medians.get("order_hour", 11))
            X["order_is_weekend"] = 0
    else:
        X["order_dayofweek"]  = int(serving_medians.get("order_dayofweek", 3))
        X["order_month"]      = int(serving_medians.get("order_month", 6))
        X["order_hour"]       = int(serving_medians.get("order_hour", 11))
        X["order_is_weekend"] = 0

    # 3. Label Encoded 特徵
    label_cols_map = {
        "Order Region":   body.order_region,
        "Category Name":  body.category_name or "Accessories",
        "Order Country":  body.order_country,
    }
    for col, val in label_cols_map.items():
        classes = serving_label_classes.get(col, mappings.get(col, []))
        val_to_idx = {v: i for i, v in enumerate(classes)}
        fallback = int(serving_medians.get(f"{col}_encoded", 0))
        X[f"{col}_encoded"] = int(val_to_idx.get(str(val), fallback))

    # 4. One-Hot 特徵（先全部初始為 0）
    for col in feature_cols:
        if col not in X:
            X[col] = 0

    # Shipping Mode
    sm_key = f"Shipping Mode_{body.shipping_mode}"
    if sm_key in X:
        X[sm_key] = 1

    # Customer Segment
    cs_key = f"Customer Segment_{body.customer_segment}"
    if cs_key in X:
        X[cs_key] = 1

    # Department Name
    dept_key = f"Department Name_{body.department_name}"
    if dept_key in X:
        X[dept_key] = 1

    # Market
    mkt_key = f"Market_{body.market}"
    if mkt_key in X:
        X[mkt_key] = 1

    # Type — 用訓練中位數（預設 Type_PAYMENT=0 等全部為 0，一致）
    # （表單未收集，保持全 0 or median）

    # ── 組成 DataFrame 並對齊特徵順序 ─────────────────────────────────
    import pandas as _pd
    row_df = _pd.DataFrame([X])[feature_cols].fillna(0)

    # ── 模型推論（cached model：避免每次請求重載，What-if 掃描可重用）──
    model = _get_delay_xgb_model(model_path)
    p_late = float(model.predict_proba(row_df)[:, 1][0])

    # ── 後處理 ───────────────────────────────────────────────────────
    if p_late >= 0.7:
        risk_bucket = "High"
    elif p_late >= 0.4:
        risk_bucket = "Medium"
    else:
        risk_bucket = "Low"

    delay_penalty   = 250.0
    expected_penalty = round(p_late * delay_penalty, 2)

    # 動態升級成本（與 preprocessor.py 一致的費率表）
    shipping_base_costs = {
        "Standard Class": 50.0,
        "Second Class":   80.0,
        "First Class":   120.0,
        "Same Day":      180.0,
    }
    region_multipliers = {
        "Western Europe":    1.1,
        "Central America":   0.9,
        "South America":     0.95,
        "Northern Europe":   1.25,
        "Eastern Europe":    1.05,
        "East of USA":       1.15,
        "Eastern Asia":      1.2,
        "Oceania":           1.3,
    }
    base_cost = shipping_base_costs.get(body.shipping_mode, 80.0)
    mult      = region_multipliers.get(body.order_region, 1.0)
    upgrade_cost    = round(base_cost * mult, 2)
    net_benefit     = round(expected_penalty - upgrade_cost, 2)

    return {
        "p_late":           round(p_late, 4),
        "risk_bucket":      risk_bucket,
        "expected_penalty": expected_penalty,
        "upgrade_cost":     upgrade_cost,
        "net_benefit_if_upgrade": net_benefit,
        "recommend_upgrade": net_benefit > 0,
    }


@app.post("/api/login")
async def login(request: LoginRequest):
    result = verify_user(request.username, request.password)
    if result["success"]:
        import uuid
        token = generate_token(request.username, result["role"])
        session_id = uuid.uuid4().hex[:12]
        return {
            "success": True,
            "role": result["role"],
            "token": token,
            "session_id": session_id
        }
    raise HTTPException(
        status_code=401,
        detail={"success": False, "message": "帳號或密碼錯誤"}
    )

@app.get("/")
async def root():
    """回傳前端 Dashboard 首頁。"""
    from fastapi.responses import FileResponse
    index_path = BASE_DIR / "static" / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path), media_type="text/html")
    return {"system": "SLIDE", "version": "1.0.0", "docs": "/docs"}


@app.post("/api/upload")
async def upload_csv(
    file: UploadFile = File(...),
    x_session_id: Optional[str] = Header(default=None)
):
    """
    [公開/Manager] 上傳訂單 CSV 檔案以進行延遲機率預測，並更新寫入 predictions_[session_id].csv。
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

        # ── C：上傳驗證閘門 ──────────────────────────────────────────────
        # 用『原始表頭』偵測重複欄/非訂單資料，不過直接回 400（在標準化之前先擋）。
        if validate_upload_columns is not None:
            import csv as _csv
            text = contents.decode("latin-1", errors="replace")
            header_line = text.splitlines()[0] if text.strip() else ""
            original_cols = next(_csv.reader([header_line])) if header_line.strip() else []
            validate_upload_columns(original_cols)

        mapping_path = BASE_DIR / "models" / "feature_mapping.json"
        model_path = BASE_DIR / "models" / "xgboost_model.json"

        df_predicted = predict_uploaded_csv(
            io.BytesIO(contents),
            mapping_path=mapping_path,
            model_path=model_path
        )

        if x_session_id:
            safe_id = "".join(c for c in x_session_id if c.isalnum() or c in ("-", "_"))
            save_path = DATA_DIR / f"predictions_session_{safe_id}.csv"
        else:
            save_path = PREDICTIONS_PATH

        df_predicted.to_csv(save_path, index=False)

        return {
            "success": True,
            "message": f"成功處理 {len(df_predicted)} 筆訂單資料，並已更新延遲預測結果！",
            "count": len(df_predicted)
        }
    except HTTPException:
        raise
    except UploadValidationError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"CSV 檔案處理或預測失敗：{str(e)}")


@app.post("/api/upload-training")
async def upload_training_csv(
    file: UploadFile = File(...),
    x_role: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """
    [Manager 限定] 上傳『可進訓練』的訂單資料（乙）。
    必須含真實標籤 Late_delivery_risk；通過 C 驗證後去除 PII，並『累積』到訓練資料庫，
    供日後重訓一併使用（仍走 adopt/discard 決定保留或捨棄）。
    """
    role = get_role(x_role, authorization)
    require_manager(role)

    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="請上傳 .csv 格式的檔案。")
    if append_training_csv is None:
        raise HTTPException(status_code=500, detail="系統內部錯誤：無法載入訓練資料模組 (training_store.py)。")

    try:
        contents = await file.read()
        store_path = BASE_DIR / "data" / "training_store" / "accumulated.csv"
        result = append_training_csv(io.BytesIO(contents), store_path)
        return {
            "success": True,
            "message": f"已累積 {result['added']} 筆訓練資料（總計 {result['total']} 筆）。下次重訓將一併使用。",
            **result,
        }
    except HTTPException:
        raise
    except (UploadValidationError, TrainingDataError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"訓練資料上傳失敗：{str(e)}")


@app.post("/api/reset-orders")
async def reset_orders(
    x_role: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
    x_session_id: Optional[str] = Header(default=None),
):
    """[Manager 限定] 重置目前 session 的上傳資料，回復為預設驗證集。"""
    role = get_role(x_role, authorization)
    require_manager(role)
    
    pred_path = get_predictions_path(x_session_id)
    if pred_path.exists() and pred_path != PREDICTIONS_PATH:
        try:
            os.remove(pred_path)
            return {"success": True, "message": "已成功重置為預設驗證集。"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"重置失敗：{str(e)}")
    return {"success": True, "message": "使用預設驗證集，無需重置。"}


@app.get("/api/metrics")

async def get_metrics(
    threshold: float = 0.5,
    x_session_id: Optional[str] = Header(default=None)
):
    """
    [公開] 回傳模型 KPI 指標，支援動態門檻值計算。
    """
    # 預設載入靜態指標
    metrics = {}
    if METRICS_PATH.exists():
        with open(METRICS_PATH, "r", encoding="utf-8") as f:
            metrics = json.load(f)

    pred_path = get_predictions_path(x_session_id)
    # 如果 predictions.csv 存在，則根據輸入的 threshold 動態重新計算混淆矩陣與指標
    if pred_path.exists():
        try:
            df = pd.read_csv(pred_path)
            if "p_late" in df.columns:
                probability = pd.to_numeric(df["p_late"], errors="coerce").fillna(0.0)
                predicted = (probability >= threshold).astype(int)
                high_risk_orders = int(predicted.sum())
                expected_penalty_sum = (
                    float(df.loc[predicted == 1, "expected_penalty"].sum())
                    if "expected_penalty" in df.columns
                    else 0.0
                )
                total_orders = int(len(df))

            if "true_label" in df.columns and "p_late" in df.columns:
                actual = df["true_label"].astype(int)

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
                    "has_ground_truth": True,
                    "is_active": pred_path != PREDICTIONS_PATH,
                }
            if "p_late" in df.columns:
                return {
                    "roc_auc": metrics.get("roc_auc", 0.803),
                    "f1": metrics.get("f1", 0.0),
                    "recall": metrics.get("recall", 0.0),
                    "precision": metrics.get("precision", 0.0),
                    "late_rate": round(float(predicted.mean()), 4),
                    "high_risk_orders": high_risk_orders,
                    "expected_penalty_sum": round(expected_penalty_sum, 2),
                    "total_orders": total_orders,
                    "confusion_matrix": None,
                    "monthly_trends": [],
                    "feature_importance": metrics.get("feature_importance"),
                    "has_ground_truth": False,
                    "is_active": pred_path != PREDICTIONS_PATH,
                    "metric_note": "目前 session 資料尚未回填真實 Y；Precision/Recall/F1 顯示基準模型指標，營運 KPI 以預測機率計算。",
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
        "has_ground_truth": True,
        "is_active": False,
    }


@app.get("/api/threshold-tuning")
async def get_threshold_tuning(
    current_threshold: float = 0.5,
    start: float = 0.1,
    stop: float = 0.9,
    step: float = 0.05,
    upgrade_cost: float = 80.0,
    delay_penalty: float = 250.0,
    x_session_id: Optional[str] = Header(default=None)
):
    """
    Return threshold candidates and recommendations for the dashboard slider.
    """
    if step <= 0:
        raise HTTPException(status_code=400, detail="step must be greater than 0.")
    if start < 0 or stop > 1 or start > stop:
        raise HTTPException(status_code=400, detail="threshold range must stay within 0..1.")
    
    pred_path = PREDICTIONS_PATH
    if not pred_path.exists():
        raise HTTPException(status_code=404, detail="predictions.csv not found.")

    df = pd.read_csv(pred_path)
    data_basis = "default_validation"

    if "true_label" not in df.columns or "p_late" not in df.columns:
        raise HTTPException(status_code=400, detail="threshold tuning requires labeled validation predictions.")

    actual = df["true_label"].astype(int)
    probability = pd.to_numeric(df["p_late"], errors="coerce").fillna(0.0)

    thresholds = []
    threshold = start
    while threshold <= stop + 1e-9:
        thresholds.append(round(threshold, 10))
        threshold += step

    rows = [
        _threshold_metrics(actual, probability, threshold, upgrade_cost, delay_penalty)
        for threshold in thresholds
    ]
    current = _threshold_metrics(actual, probability, current_threshold, upgrade_cost, delay_penalty)
    best_f1 = max(rows, key=lambda row: (row["f1"], row["recall"], row["precision"]))
    best_expected_cost = min(rows, key=lambda row: (row["expected_cost"], row["fn"], row["fp"]))

    return {
        "row_count": int(len(df)),
        "current": current,
        "best_f1": best_f1,
        "best_expected_cost": best_expected_cost,
        "thresholds": rows,
        "data_basis": data_basis,
        "basis_note": "門檻建議固定使用預設驗證集計算；回填已知結果並採用新模型後才會更新基準。",
        "cost_model": {
            "upgrade_cost": upgrade_cost,
            "delay_penalty": delay_penalty,
        },
    }


@app.get("/api/predict")
def get_predictions(
    x_role: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
    x_session_id: Optional[str] = Header(default=None),
    limit: int = 50,
    page: int = 1,
    search: Optional[str] = None,
    risk: Optional[str] = None,
    shipping: Optional[str] = None,
    region: Optional[str] = None,
    threshold: Optional[float] = None,
    error_only: Optional[bool] = None,
    month: Optional[str] = None,
):
    """
    [Viewer / Manager] 回傳去識別化的訂單延遲風險列表。

    排序：依 p_late 由高到低（緊急程度），讓最該關注的訂單排在最前，
    避免高低風險交錯。可用 month=YYYY-MM 篩選單一月份（搭配前端月份 flipper）。
    回應含 available_months 供前端建立月份切換器。
    """
    role = get_role(x_role, authorization)
    threshold_val = threshold if threshold is not None else 0.5
    pred_path = get_predictions_path(x_session_id)

    if not pred_path.exists():

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
            "available_months": [],
            "active_month": month,
            "note": "示範資料（請先執行 model_pipeline.py）",
        }

    df = load_cached_predictions(pred_path)


    # 動態計算 predicted_late、actual_late 和 is_correct
    if "p_late" in df.columns:
        df["predicted_late"] = (df["p_late"] >= threshold_val).astype(int)
        if "true_label" in df.columns:
            df["actual_late"] = df["true_label"].astype(int)
            df["is_correct"] = (df["actual_late"] == df["predicted_late"])
        else:
            df["actual_late"] = None
            df["is_correct"] = None

    # 由 order_date 推導月份（YYYY-MM）。order_date 為美式 M/D/YYYY 格式，
    # 須以 to_datetime 正確解析，不可直接截字串。available_months 取自全量資料，
    # 讓前端月份 flipper 穩定（不隨其他篩選變動）。
    available_months: list[str] = []
    if "order_date" in df.columns:
        parsed = pd.to_datetime(df["order_date"], errors="coerce")
        df["__month"] = parsed.dt.strftime("%Y-%m")
        available_months = sorted(m for m in df["__month"].dropna().unique())

    # 應用過濾器
    if month and "__month" in df.columns:
        df = df[df["__month"] == month]
    if search:
        # 正規化搜尋字串：去掉 ORD- 前綴與非英數字、轉小寫，再比對小寫雜湊。
        # 讓「畫面上的 ID（ORD-XXXXXXXX）」與「純雜湊片段」都搜得到（顯示=搜尋一致）。
        search_norm = re.sub(
            r"[^a-z0-9]", "",
            re.sub(r"^ord[-_]?", "", search.strip(), flags=re.IGNORECASE).lower(),
        )
        if search_norm:
            df = df[df["order_id_hash"].astype(str).str.lower().str.contains(search_norm, na=False)]
    if risk:
        df = df[df["risk_bucket"] == risk]
    if shipping:
        df = df[df["shipping_mode"] == shipping]
    if region:
        df = df[df["order_region"] == region]
    if threshold is not None:
        df = df[df["p_late"] >= threshold]
    if error_only:
        if "true_label" in df.columns:
            df = df[df["is_correct"] == False]
        else:
            df = df.iloc[0:0]

    # 依緊急程度排序：p_late 由高到低，最該關注的訂單排最前（避免高低風險交錯）
    if "p_late" in df.columns:
        df = df.sort_values("p_late", ascending=False, kind="stable")

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
            "display_order_id": make_display_order_id(rec.get("order_id_hash")),
            "shipping_mode": rec.get("shipping_mode"),
            "order_region": rec.get("order_region"),
            "p_late": rec.get("p_late"),
            "risk_bucket": rec.get("risk_bucket"),
            "upgrade_cost": rec.get("upgrade_cost"),
            "expected_penalty": rec.get("expected_penalty"),
            "actual_late": rec.get("actual_late"),
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
        "available_months": available_months,
        "active_month": month,
    }


@app.get("/api/summary")
def get_summary(
    by: str = "shipping_mode",
    x_session_id: Optional[str] = Header(default=None)
):
    """[公開] 依指定維度彙總訂單數量與平均延遲機率。"""
    allowed = {"shipping_mode", "order_region", "risk_bucket"}
    if by not in allowed:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"by 必須為: {', '.join(allowed)}")

    pred_path = get_predictions_path(x_session_id)
    if not pred_path.exists():
        return []

    df = load_cached_predictions(pred_path)

    grouped = (
        df.groupby(by)
        .agg(count=(by, "count"), avg_p_late=("p_late", "mean"))
        .reset_index()
    )
    grouped["avg_p_late"] = grouped["avg_p_late"].round(4)
    grouped = grouped.sort_values("count", ascending=False)
    return grouped.rename(columns={by: "label"}).to_dict(orient="records")


@app.get("/api/executive-summary")
def get_executive_summary(
    threshold: float = 0.5,
    upgrade_cost: float = 80.0,
    delay_penalty: float = 250.0,
    x_session_id: Optional[str] = Header(default=None)
):
    """
    [公開] 高階經理人決策摘要。

    將模型預測轉成營運語言：服務水準風險、財務曝險、建議預算、
    以及優先處理的區域與運送模式。
    """
    pred_path = get_predictions_path(x_session_id)
    if not pred_path.exists():

        total_orders = 2
        at_risk_orders = 1
        expected_penalty_exposure = 205.0
        positive_roi_orders = 1
        return {
            "total_orders": total_orders,
            "at_risk_orders": at_risk_orders,
            "at_risk_rate": 0.5,
            "service_level_target": 0.9,
            "estimated_service_level": 0.5,
            "expected_penalty_exposure": expected_penalty_exposure,
            "positive_roi_orders": positive_roi_orders,
            "recommended_budget": 80.0,
            "net_savings": 125.0,
            "recommended_action": "先升級高風險且 ROI 為正的訂單，避免延遲罰金擴大。",
            "top_regions": [{"label": "Western Europe", "count": 1, "avg_p_late": 0.82}],
            "top_shipping_modes": [{"label": "Standard Class", "count": 1, "avg_p_late": 0.82}],
            "data_quality_note": "示範資料，請先產生 predictions.csv。",
        }

    df = load_cached_predictions(pred_path)

    if df.empty or "p_late" not in df.columns:
        raise HTTPException(status_code=500, detail="predictions.csv 缺少 p_late 或資料為空。")

    working = df.copy()
    working["p_late"] = pd.to_numeric(working["p_late"], errors="coerce").fillna(0.0)
    if "expected_penalty" not in working.columns:
        working["expected_penalty"] = (working["p_late"] * delay_penalty).round(2)
    if "upgrade_cost" not in working.columns:
        working["upgrade_cost"] = upgrade_cost

    total_orders = int(len(working))
    at_risk = working[working["p_late"] >= threshold].copy()
    at_risk_orders = int(len(at_risk))
    at_risk_rate = (at_risk_orders / total_orders) if total_orders else 0.0
    estimated_service_level = 1.0 - at_risk_rate
    exposure = float(at_risk["expected_penalty"].sum()) if not at_risk.empty else 0.0

    at_risk["net_benefit"] = (
        pd.to_numeric(at_risk["expected_penalty"], errors="coerce").fillna(0.0)
        - pd.to_numeric(at_risk["upgrade_cost"], errors="coerce").fillna(upgrade_cost)
    )
    positive_roi = at_risk[at_risk["net_benefit"] > 0]
    positive_roi_orders = int(len(positive_roi))
    recommended_budget = float(positive_roi["upgrade_cost"].sum()) if not positive_roi.empty else 0.0
    # 真正的淨節省：只計入「值得升級」訂單的淨效益總和（expected_penalty - upgrade_cost），
    # 不可用「全部曝險 - 建議預算」概算，否則會把未升級訂單的罰金也誤算成節省。
    net_savings = float(positive_roi["net_benefit"].sum()) if not positive_roi.empty else 0.0

    def top_breakdown(column: str) -> list[dict]:
        if column not in at_risk.columns or at_risk.empty:
            return []
        grouped = (
            at_risk.groupby(column)
            .agg(count=("p_late", "count"), avg_p_late=("p_late", "mean"))
            .reset_index()
            .sort_values(["count", "avg_p_late"], ascending=False)
            .head(5)
        )
        grouped["avg_p_late"] = grouped["avg_p_late"].round(4)
        return grouped.rename(columns={column: "label"}).to_dict(orient="records")

    if at_risk_rate >= 0.35:
        action = "建議優先優化高風險訂單。"
    elif positive_roi_orders > 0:
        action = "建議優化推薦升級訂單。"
    else:
        action = "建議維持原配送策略。"

    return {
        "total_orders": total_orders,
        "at_risk_orders": at_risk_orders,
        "at_risk_rate": round(at_risk_rate, 4),
        "service_level_target": 0.9,
        "estimated_service_level": round(estimated_service_level, 4),
        "expected_penalty_exposure": round(exposure, 2),
        "positive_roi_orders": positive_roi_orders,
        "recommended_budget": round(recommended_budget, 2),
        "net_savings": round(net_savings, 2),
        "recommended_action": action,
        "top_regions": top_breakdown("order_region"),
        "top_shipping_modes": top_breakdown("shipping_mode"),
        "data_quality_note": "（數據每日更新核對）",
    }


@app.get("/api/scenario-analysis")
def get_scenario_analysis(
    budgets: str = "1000,3000,5000,10000",
    upgrade_cost: float = 80.0,
    delay_penalty: float = 250.0,
    x_session_id: Optional[str] = Header(default=None)
):
    """
    [公開] 預算情境比較。

    使用與正式最佳化相同的 PuLP MILP solver，讓主管比較不同預算下
    可升級訂單數、預估淨效益、避免罰金與預算使用率。
    """
    pred_path = get_predictions_path(x_session_id)
    if not pred_path.exists():

        return {
            "scenarios": [
                {
                    "budget": 1000.0,
                    "selected_count": 12,
                    "total_cost": 960.0,
                    "expected_total_saving": 1890.0,
                    "expected_total_penalty_avoided": 2850.0,
                    "budget_usage_pct": 96.0,
                    "solver": "demo response",
                }
            ],
            "recommended_budget": 1000.0,
            "recommendation": "示範資料：此預算可覆蓋高風險且 ROI 為正的訂單。",
        }

    if ShippingOptimizer is None:
        raise HTTPException(status_code=500, detail="optimizer.py 載入失敗，無法執行情境分析。")

    parsed_budgets: list[float] = []
    for raw in budgets.split(","):
        try:
            value = float(raw.strip())
        except ValueError:
            continue
        if value > 0:
            parsed_budgets.append(value)
    parsed_budgets = sorted(set(parsed_budgets))[:6]
    if not parsed_budgets:
        raise HTTPException(status_code=400, detail="budgets 至少需包含一個正數，例如 1000,3000,5000。")

    df = load_cached_predictions(pred_path)
    scenarios = []
    for budget in parsed_budgets:
        optimizer = ShippingOptimizer(
            budget=budget,
            upgrade_cost=upgrade_cost,
            delay_penalty=delay_penalty,
            max_candidates=500,
        )
        result = optimizer.run(
            predictions_path_or_df=df,
            output_dir=str(DATA_DIR),
            save_results=False,
        ).to_dict()

        scenarios.append({
            "budget": budget,
            "selected_count": result.get("selected_count", len(result.get("selected_orders", []))),
            "total_cost": round(float(result.get("total_cost", 0.0)), 2),
            "expected_total_saving": round(float(result.get("expected_total_saving", 0.0)), 2),
            "expected_total_penalty_avoided": round(float(result.get("expected_total_penalty_avoided", 0.0)), 2),
            "budget_usage_pct": round((float(result.get("total_cost", 0.0)) / budget * 100.0) if budget else 0.0, 2),
            "solver": result.get("solver", "PuLP MILP"),
        })

    positive = [s for s in scenarios if s["expected_total_saving"] > 0]
    best = max(positive or scenarios, key=lambda s: (s["expected_total_saving"], s["selected_count"]))
    recommendation = (
        f"建議至少保留 USD ${best['budget']:,.0f} 的升級預算；"
        f"此情境可處理 {best['selected_count']} 筆訂單，"
        f"預估淨效益 USD ${best['expected_total_saving']:,.0f}。"
    )

    return {
        "scenarios": scenarios,
        "recommended_budget": best["budget"],
        "recommendation": recommendation,
    }


@app.post("/api/optimize")
def run_optimization(
    request: OptimizeRequest,
    x_role: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
    x_session_id: Optional[str] = Header(default=None),
):
    """
    [僅限 Logistics_Manager] 執行最佳化調度。
    """
    role = get_role(x_role, authorization)

    # ── RBAC 核心：403 檢查 ──────────────────────────────────────────────
    require_manager(role)
    # ─────────────────────────────────────────────────────────────────────

    pred_path = get_predictions_path(x_session_id)
    result_dict = build_optimization_result(request, pred_path, save_results=True)

    return {
        "role": role,
        **result_dict,
    }


@app.get("/api/llm/settings")
def get_llm_settings(
    x_role: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """[Manager 限定] 讀取目前 LLM 設定摘要，不回傳完整 API key。"""
    role = get_role(x_role, authorization)
    require_manager(role)
    return {
        "role": role,
        "settings": get_public_llm_config(),
        "providers": ["local", "openai", "openai_compatible", "gemini", "claude", "ollama"],
    }


@app.put("/api/llm/settings")
def update_llm_settings(
    request: LLMSettingsRequest,
    x_role: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """[Manager 限定] 儲存 runtime LLM provider/model/API key 設定。"""
    role = get_role(x_role, authorization)
    require_manager(role)

    provider = request.provider.strip().lower()
    if provider not in {"local", "openai", "openai_compatible", "gemini", "claude", "ollama"}:
        raise HTTPException(status_code=400, detail=f"不支援的 LLM provider：{request.provider}")

    current = read_llm_runtime_config()
    api_key = request.api_key.strip()
    if provider in {"local", "ollama"}:
        api_key = ""
    elif api_key == "__KEEP_EXISTING__" and current.get("provider") == provider:
        api_key = current.get("api_key", "")
    elif api_key == "__KEEP_EXISTING__":
        api_key = ""

    write_llm_runtime_config({
        "provider": provider,
        "model": request.model.strip(),
        "api_key": api_key,
        "api_url": request.api_url.strip(),
    })
    return {
        "role": role,
        "message": "LLM 設定已儲存。",
        "settings": get_public_llm_config(),
    }


@app.post("/api/llm/manager-brief")
def generate_manager_llm_brief(
    request: LLMBriefRequest,
    x_role: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
    x_session_id: Optional[str] = Header(default=None),
):
    """[Manager 限定] 意圖路由 AI 助理：0 token 資料卡片 + 必要時才呼叫 LLM。"""
    role = get_role(x_role, authorization)
    require_manager(role)

    # 離題快速攔截（0 token）；ORD- 訂單查詢直接放行不做離題檢查
    if not _ORD_RE.search(request.question) and not is_logistics_question(request.question):
        return {
            "role": role,
            "brief_text": off_topic_llm_response(request.question),
            "intent": "off_topic",
            "llm": {"used_external_llm": False, "provider": "none", "configured_provider": "none",
                    "model": "none", "response_id": None, "error": None},
        }

    pred_path = get_predictions_path(x_session_id)

    # 意圖分類
    intent, params = route_assistant_intent(request.question)

    # 快取命中（非 general/order_lookup 才快取）
    cache_key = (intent, json.dumps(params, sort_keys=True), str(pred_path))
    if intent not in ("order_lookup", "general") and cache_key in ASSISTANT_CACHE:
        cached = dict(ASSISTANT_CACHE[cache_key])
        cached["from_cache"] = True
        cached["role"] = role
        return cached

    # 取最小資料
    data = fetch_intent_payload(intent, params, pred_path, request)

    # 格式化固定卡片
    card = format_intent_card(intent, data)

    # 只有 order_lookup 或 general 才呼叫 LLM 潤飾
    needs_llm = intent in ("order_lookup", "general")
    if needs_llm:
        minimal_json = json.dumps(data, ensure_ascii=False, default=str)
        prompt = (
            "你是 EDIS 物流決策助理，只回答延遲風險、預算最佳化、升級調度。\n"
            "規則：1.只用<資料>內容回答，禁止推算沒有的數字。"
            "2.固定輸出：【結論】1句→【明細】按<資料>數字→【下一步】1句建議。"
            "3.繁體中文，精簡，全文≤120字。4.數字直接引用，不自行計算或加總。\n"
            f"<資料>{minimal_json}\n<問題>{request.question}"
        )
        llm_result = call_configured_llm(prompt, card, max_tokens=400)
        brief_text = llm_result["brief_text"]
    else:
        llm_result = {
            "used_external_llm": False, "provider": "card", "configured_provider": "card",
            "model": "card", "response_id": None, "error": None,
        }
        brief_text = card

    result = {
        "role": role,
        "brief_text": brief_text,
        "intent": intent,
        "llm": {
            "used_external_llm": llm_result["used_external_llm"],
            "provider": llm_result.get("provider"),
            "configured_provider": llm_result.get("configured_provider", llm_result.get("provider")),
            "model": llm_result.get("model"),
            "response_id": llm_result.get("response_id"),
            "error": llm_result.get("error"),
        },
    }

    if intent not in ("order_lookup", "general"):
        ASSISTANT_CACHE[cache_key] = result

    return result


@app.get("/api/explain/{order_id_hash}")
def get_order_explanation(
    order_id_hash: str,
    x_role: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
    x_session_id: Optional[str] = Header(default=None),
):
    """
    [Viewer / Manager] 回傳特定訂單的 LIME-style 可解釋性分析。
    """
    role = get_role(x_role, authorization)

    pred_path = get_predictions_path(x_session_id)
    if not pred_path.exists():
        raise HTTPException(status_code=404, detail="預測資料不存在，請先執行 pipeline。")

    df = load_cached_predictions(pred_path)

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
def get_region_risk(
    x_session_id: Optional[str] = Header(default=None)
):
    """計算並回傳各區域的平均延遲率排行。"""
    pred_path = get_predictions_path(x_session_id)
    if not pred_path.exists():
        return [
            {"order_region": "Western Europe", "p_late": 0.82, "count": 2},
            {"order_region": "Central America", "p_late": 0.45, "count": 1},
        ]
    df = load_cached_predictions(pred_path)

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


# ── 月份診斷端點 ──────────────────────────────────────────────────────────────

def add_analysis_period(df: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """Add a real month when dates exist, otherwise stable sequential data batches."""
    result = df.copy()
    if "order_date" in result.columns:
        parsed_dates = pd.to_datetime(result["order_date"], errors="coerce")
        if parsed_dates.notna().any():
            result = result.loc[parsed_dates.notna()].copy()
            result["month"] = parsed_dates.loc[parsed_dates.notna()].dt.to_period("M").astype(str)
            return result, "calendar_month"

    batch_count = min(12, max(1, len(result)))
    batch_size = max(1, (len(result) + batch_count - 1) // batch_count)
    batch_numbers = (pd.Series(range(len(result)), index=result.index) // batch_size) + 1
    result["month"] = batch_numbers.clip(upper=batch_count).map(lambda value: f"資料批次 {value:02d}")
    return result, "data_batch"

@app.get("/api/chart/monthly")
def get_monthly_chart(
    x_session_id: Optional[str] = Header(default=None)
):
    """回傳所有月份的預測延遲率與實際延遲率，供前端 Flipper 使用。"""
    pred_path = get_predictions_path(x_session_id)
    if not pred_path.exists():
        raise HTTPException(status_code=404, detail="predictions.csv 不存在。")
    df = load_cached_predictions(pred_path)

    if "p_late" not in df.columns:
        raise HTTPException(status_code=500, detail="predictions.csv 缺少 p_late 欄位。")

    df, period_mode = add_analysis_period(df)
    has_ground_truth = "true_label" in df.columns
    if has_ground_truth:
        df["actual_late"] = df["true_label"].astype(int)

    agg_map = {
        "avg_p_late": ("p_late", "mean"),
        "total_orders": ("p_late", "count"),
    }
    if has_ground_truth:
        agg_map["actual_late_rate"] = ("actual_late", "mean")
    grouped = df.groupby("month").agg(**agg_map).reset_index().sort_values("month")

    records = []
    for _, row in grouped.iterrows():
        records.append({
            "month":            row["month"],
            "avg_p_late":       round(float(row["avg_p_late"]), 4),
            "actual_late_rate": round(float(row["actual_late_rate"]), 4) if has_ground_truth else None,
            "total_orders":     int(row["total_orders"]),
            "has_ground_truth":  has_ground_truth,
        })
    return {
        "data": records,
        "period_mode": period_mode,
        "has_ground_truth": has_ground_truth,
        "period_note": (
            "依原始訂單日期彙整月份。"
            if period_mode == "calendar_month" and has_ground_truth
            else "目前資料尚未回填真實 Y；此圖僅顯示預測延遲率，Y 與誤差診斷需等待實際配送結果。"
            if period_mode == "calendar_month"
            else "目前預測檔未包含訂單日期，改以固定資料批次呈現；若尚未回填真實 Y，僅顯示預測延遲率。"
        ),
    }


@app.get("/api/diagnose/monthly")
def diagnose_monthly(
    month: str,
    error_threshold: float = 0.05,
    x_session_id: Optional[str] = Header(default=None)
):
    """對指定月份跑 LIME 聚合分析，回傳誤差來源特徵。"""
    pred_path = get_predictions_path(x_session_id)
    if not pred_path.exists():
        raise HTTPException(status_code=404, detail="predictions.csv 不存在。")

    df = load_cached_predictions(pred_path)

    if "p_late" not in df.columns:
        raise HTTPException(status_code=500, detail="predictions.csv 缺少 p_late 欄位。")
    df, period_mode = add_analysis_period(df)
    month_df = df[df["month"] == month].copy()
    if month_df.empty:
        raise HTTPException(status_code=404, detail=f"找不到 {month} 的資料。")

    threshold_val = 0.5
    has_ground_truth = "true_label" in month_df.columns
    if has_ground_truth:
        month_df["actual_late"]    = month_df["true_label"].astype(int)
        month_df["predicted_late"] = (month_df["p_late"] >= threshold_val).astype(int)
        month_df["is_correct"]     = month_df["actual_late"] == month_df["predicted_late"]
    else:
        month_df["is_correct"] = None

    avg_p_late        = float(month_df["p_late"].mean())
    actual_late_rate  = float(month_df["actual_late"].mean()) if has_ground_truth else None
    error             = abs(avg_p_late - actual_late_rate) if has_ground_truth else None
    error_orders      = month_df[month_df["is_correct"] == False] if has_ground_truth else month_df.iloc[0:0]

    # Use saved model importance for an immediate aggregate diagnosis. Running
    # per-order explanation repeatedly here can block the single API worker.
    top_factors = []
    try:
        metrics_data = {}
        if METRICS_PATH.exists():
            with open(METRICS_PATH, "r", encoding="utf-8") as f:
                metrics_data = json.load(f)
        feature_importance = metrics_data.get("feature_importance", {})
        ranked_factors = sorted(feature_importance.items(), key=lambda item: -float(item[1]))[:5]
        max_weight = max((float(weight) for _, weight in ranked_factors), default=1.0)
        top_factors = [
            {
                "feature": feature,
                "count": len(error_orders),
                "direction": "model influence",
                "pct": round(float(weight) / max_weight * 100, 1),
            }
            for feature, weight in ranked_factors
        ]
    except Exception:
        pass

    # 讀取已有的外部事件標記
    flags_path = DATA_DIR / "event_flags.json"
    event_flag = None
    if flags_path.exists():
        with open(flags_path, "r", encoding="utf-8") as f:
            flags = json.load(f)
        event_flag = flags.get(month)

    return {
        "month":                 month,
        "avg_p_late":            round(avg_p_late, 4),
        "actual_late_rate":      round(actual_late_rate, 4) if has_ground_truth else None,
        "error":                 round(error, 4) if has_ground_truth else None,
        "error_exceeds_threshold": error > error_threshold if has_ground_truth else False,
        "total_orders":          len(month_df),
        "error_orders_count":    len(error_orders),
        "top_factors":           top_factors,
        "event_flag":            event_flag,
        "period_mode":           period_mode,
        "has_ground_truth":      has_ground_truth,
    }


@app.post("/api/diagnose/monthly/flag")
def flag_monthly_event(
    body: FlagEventRequest,
    x_role: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """[Manager 限定] 將某月份標記為外部偶發事件。"""
    role = get_role(x_role, authorization)
    require_manager(role)

    month      = body.month.strip()
    event_type = body.event_type.strip()
    note       = body.note.strip()

    if not month or not event_type:
        raise HTTPException(status_code=400, detail="month 與 event_type 為必填。")

    flags_path = DATA_DIR / "event_flags.json"
    flags: dict = {}
    if flags_path.exists():
        with open(flags_path, "r", encoding="utf-8") as f:
            flags = json.load(f)

    from datetime import datetime
    flags[month] = {
        "type":       event_type,
        "note":       note,
        "flagged_at": datetime.utcnow().isoformat(),
        "flagged_by": role,
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(flags_path, "w", encoding="utf-8") as f:
        json.dump(flags, f, ensure_ascii=False, indent=2)

    return {"success": True, "month": month, "event_type": event_type, "note": note}


@app.post("/api/retrain")
async def retrain_model(
    body: RetrainRequest,
    background_tasks: BackgroundTasks,
    x_role: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """
    [Manager 限定] 排除指定特徵後非同步重新訓練 XGBoost。
    回傳 task_id，以便前端進行狀態輪詢。
    """
    role = get_role(x_role, authorization)
    require_manager(role)

    import uuid
    task_id = uuid.uuid4().hex[:12]
    
    RETRAIN_TASKS[task_id] = {
        "status": "running",
        "progress": 0,
        "log": "任務初始化中，已排入排程...",
        "result": None,
        "error": None,
        "base_model_hash": ""
    }
    
    background_tasks.add_task(run_retrain_task, task_id, body.excluded_features)
    
    return {"success": True, "task_id": task_id}


@app.get("/api/tasks/{task_id}/status")
def get_task_status(task_id: str):
    """查詢模型重訓背景任務的最新狀態與訓練進度。"""
    if task_id not in RETRAIN_TASKS:
        raise HTTPException(status_code=404, detail="找不到指定的任務。")
    return RETRAIN_TASKS[task_id]


@app.post("/api/retrain/adopt")
def adopt_retrain(
    body: RetrainSessionRequest,
    x_role: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """[Manager 限定] 採用新模型，覆蓋現有 xgboost_model.json 與 model_metrics.json。"""
    role = get_role(x_role, authorization)
    require_manager(role)

    # 1. 併發防禦：校驗 Adopt 時的基礎模型雜湊值是否與重訓開始時一致
    target_task = None
    for tid, t in RETRAIN_TASKS.items():
        if t["result"] and t["result"]["session_id"] == body.session_id:
            target_task = t
            break

    if target_task:
        model_path = BASE_DIR / "models" / "xgboost_model.json"
        current_hash = get_file_hash(model_path)
        base_hash = target_task.get("base_model_hash", "")
        if base_hash and current_hash != base_hash:
            raise HTTPException(
                status_code=409,
                detail="模型採用失敗：基礎模型已被其他管理員重訓並覆蓋，請重新診斷。"
            )

    try:
        from retrainer import ModelRetrainer
    except ImportError:
        raise HTTPException(status_code=500, detail="retrainer.py 載入失敗。")

    retrainer = ModelRetrainer(base_dir=BASE_DIR)
    try:
        retrainer.adopt(body.session_id)
        
        # 2. 寫入 SQLite 管理員審計日誌
        try:
            import sqlite3
            from auth import DB_PATH
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            
            # 從 Token 解析用戶名
            username = "admin"
            if authorization:
                try:
                    if authorization.startswith("Bearer "):
                        token = authorization[7:]
                    else:
                        token = authorization
                    from auth import verify_token
                    res = verify_token(token)
                    if res["success"]:
                        username = res["username"]
                except Exception:
                    pass
                    
            log_detail = f"採用重訓後之新模型 (Session: {body.session_id})。"
            if target_task and target_task["result"]:
                dropped = target_task["result"].get("dropped_columns", [])
                log_detail += f" 排除之特徵欄位: {', '.join(dropped)}。"
                
            c.execute(
                "INSERT INTO audit_logs (operator, action, detail) VALUES (?, ?, ?)",
                (username, "ADOPT_MODEL", log_detail)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[Audit Log] 寫入日誌發生錯誤: {str(e)}")
            
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"採用失敗：{str(e)}")

    return {"success": True, "message": "新模型已採用並替換現有模型。"}


@app.post("/api/retrain/discard")
def discard_retrain(
    body: RetrainSessionRequest,
    x_role: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """[Manager 限定] 捨棄新模型，保留現有模型不變。"""
    role = get_role(x_role, authorization)
    require_manager(role)

    try:
        from retrainer import ModelRetrainer
    except ImportError:
        raise HTTPException(status_code=500, detail="retrainer.py 載入失敗。")

    retrainer = ModelRetrainer(base_dir=BASE_DIR)
    retrainer.discard(body.session_id)
    return {"success": True, "message": "已捨棄新模型，現有模型不變。"}



# ── 全域錯誤處理 ──────────────────────────────────────────────────────────────

def _load_profit_metrics() -> dict:
    if not PROFIT_METRICS_PATH.exists():
        return {}
    try:
        with open(PROFIT_METRICS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _load_profit_manifest() -> dict:
    if not PROFIT_MANIFEST_PATH.exists():
        return {}
    try:
        with open(PROFIT_MANIFEST_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


@app.get("/api/profit/metrics")
async def get_profit_metrics(
    x_role: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    metrics = _load_profit_metrics()
    manifest = _load_profit_manifest()
    if not metrics:
        return {
            "is_trained": False,
            "message": "Profit model metrics are not available yet. Run core/profit_model_pipeline.py after preprocessing is complete.",
            "expected_files": [
                str(PROFIT_METRICS_PATH.relative_to(BASE_DIR)),
                str(PROFIT_PREDICTIONS_PATH.relative_to(BASE_DIR)),
                str(PROFIT_MANIFEST_PATH.relative_to(BASE_DIR)),
            ],
        }

    return {
        "is_trained": True,
        "metrics": metrics,
        "manifest": {
            "target_column": manifest.get("target_column", metrics.get("target_column", "Order Profit Per Order")),
            "feature_count": len(manifest.get("feature_columns", [])) or metrics.get("feature_count", 0),
            "feature_columns": manifest.get("feature_columns", []),
            "model_path": manifest.get("model_path", "models/profit_lightgbm_model.txt"),
        },
    }


@app.get("/api/profit/feature-importance")
async def get_profit_feature_importance(
    x_role: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
    limit: int = 20,
):
    metrics = _load_profit_metrics()
    importance = metrics.get("feature_importance") or {}
    rows = [
        {"feature": feature, "importance": float(value)}
        for feature, value in importance.items()
    ]
    rows.sort(key=lambda row: row["importance"], reverse=True)
    return {
        "is_trained": bool(metrics),
        "data": rows[: max(1, min(limit, 100))],
    }


@app.get("/api/profit/predictions")
async def get_profit_predictions(
    x_role: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
    limit: int = 25,
    page: int = 1,
    sort: str = "abs_residual",
):
    if not PROFIT_PREDICTIONS_PATH.exists():
        return {
            "is_trained": False,
            "count": 0,
            "page": page,
            "limit": limit,
            "data": [],
            "message": "Profit predictions are not available yet.",
        }

    df = load_cached_predictions(PROFIT_PREDICTIONS_PATH)
    required = {"actual_profit", "predicted_profit", "residual"}
    if not required.issubset(df.columns):
        raise HTTPException(
            status_code=500,
            detail=f"profit_predictions.csv must contain columns: {sorted(required)}",
        )

    df = df.copy()
    for col in required:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=list(required))
    df["abs_residual"] = df["residual"].abs()

    if sort == "predicted_profit":
        df = df.sort_values("predicted_profit", ascending=False)
    elif sort == "actual_profit":
        df = df.sort_values("actual_profit", ascending=False)
    else:
        df = df.sort_values("abs_residual", ascending=False)

    limit = max(1, min(limit, 100))
    page = max(1, page)
    total = int(len(df))
    start = (page - 1) * limit
    end = start + limit
    rows = df.iloc[start:end].reset_index(drop=True)

    data = []
    for idx, row in rows.iterrows():
        absolute_index = start + idx
        data.append({
            "row_id": f"profit_test_{absolute_index + 1:05d}",
            "actual_profit": round(float(row["actual_profit"]), 4),
            "predicted_profit": round(float(row["predicted_profit"]), 4),
            "residual": round(float(row["residual"]), 4),
            "abs_residual": round(float(row["abs_residual"]), 4),
        })

    return {
        "is_trained": True,
        "count": total,
        "page": page,
        "limit": limit,
        "total_pages": int((total + limit - 1) // limit) if total else 1,
        "sort": sort,
        "data": data,
    }


# ════════════════════════════════════════════════════════════════════════════
# 最佳化ROI模擬器 + 模型診斷落地（SLIDE 決策框架點 1–4）
#   - 資料基礎：data/processed/decision_dataset.csv（scripts/build_decision_dataset.py 產出）
#   - 全部「新增」端點，不更動既有路由/資料來源（零衝突）。
#   - 重模型/資料一律 cache（mtime / 單例），避免每請求重載造成效能與重入問題。
# ════════════════════════════════════════════════════════════════════════════

DECISION_DATASET_PATH = DATA_DIR / "decision_dataset.csv"
DECISION_SUMMARY_PATH = DATA_DIR / "decision_dataset_summary.json"
DECISION_TRUST_PATH = DATA_DIR / "decision_trust_map.json"

_XGB_MODEL_CACHE: dict = {}
_PROFIT_RUNTIME: dict = {}


def _get_delay_xgb_model(model_path: Path):
    """以 mtime 快取載入 XGBoost 延遲模型（單例，供單筆預測與 What-if 重用）。"""
    import xgboost as xgb
    mtime = model_path.stat().st_mtime
    entry = _XGB_MODEL_CACHE.get(model_path)
    if entry is None or entry["mtime"] != mtime:
        model = xgb.XGBClassifier()
        model.load_model(str(model_path))
        _XGB_MODEL_CACHE[model_path] = {"mtime": mtime, "model": model}
        return model
    return entry["model"]


def _get_profit_runtime() -> dict:
    """單例載入收益模型 runtime（pipeline 編碼 + LightGBM booster + schema）。"""
    if not _PROFIT_RUNTIME:
        import lightgbm as lgb
        from profit_data_pipeline import ProfitDataPipeline

        artifacts_path = BASE_DIR / "models" / "profit" / "serving_artifacts.json"
        schema_path = DATA_DIR / "profit_feature_schema.json"
        model_path = BASE_DIR / "models" / "profit_lightgbm_model.txt"
        if not (artifacts_path.exists() and schema_path.exists() and model_path.exists()):
            raise HTTPException(status_code=503, detail="收益模型尚未就緒，請先執行收益管線與訓練。")

        with open(artifacts_path, encoding="utf-8") as f:
            artifacts = json.load(f)
        with open(schema_path, encoding="utf-8") as f:
            schema = json.load(f)
        pipe = ProfitDataPipeline()
        pipe.artifacts = artifacts
        _PROFIT_RUNTIME.update(
            pipe=pipe, schema=schema,
            booster=lgb.Booster(model_file=str(model_path)),
        )
    return _PROFIT_RUNTIME


def _load_decision_df() -> pd.DataFrame:
    """載入統一決策資料集（mtime 快取）。"""
    if not DECISION_DATASET_PATH.exists():
        raise HTTPException(
            status_code=404,
            detail="decision_dataset.csv 尚未產生，請先執行：python scripts/build_decision_dataset.py",
        )
    return load_cached_predictions(DECISION_DATASET_PATH)


def _apply_value_risk(df: pd.DataFrame, value_axis: str, risk_axis: str, penalty: float) -> pd.DataFrame:
    """依使用者選的價值/風險軸與罰金，計算 value/risk 欄（不污染快取，操作於 copy）。"""
    df = df.copy()
    # net_of_service 隨 penalty 重算（真延遲 true_label × 罰金）；profit_actual 不受罰金影響
    df["net_of_service"] = (df["profit_actual"] - df["true_label"] * penalty).round(4)
    df["value"] = df["net_of_service"] if value_axis == "net_of_service" else df["profit_actual"]
    df["risk"] = df["true_label"] if risk_axis == "true_label" else df["p_late"]
    return df


def _filter_decision(df: pd.DataFrame, segment, region, category, shipping, discount_band) -> pd.DataFrame:
    if segment:
        df = df[df["customer_segment"] == segment]
    if region:
        df = df[df["order_region"] == region]
    if category:
        df = df[df["category_name"] == category]
    if shipping:
        df = df[df["shipping_mode"] == shipping]
    if discount_band == "low":
        df = df[df["discount_rate"] < 0.10]
    elif discount_band == "mid":
        df = df[(df["discount_rate"] >= 0.10) & (df["discount_rate"] < 0.25)]
    elif discount_band == "high":
        df = df[df["discount_rate"] >= 0.25]
    return df


class ProfitSingleRequest(BaseModel):
    shipping_mode: str = "Standard Class"
    order_region: str = "Western Europe"
    category_name: str = "Cleats"
    customer_segment: str = "Consumer"
    market: str = "Europe"
    product_price: float = 59.99
    order_item_quantity: int = 1
    discount_rate: float = 0.1
    days_for_shipment: float = 4.0
    order_date: Optional[str] = None
    sales: Optional[float] = None


class WhatIfRequest(ProfitSingleRequest):
    discount_grid: list[float] = [0.0, 0.05, 0.1, 0.15, 0.2, 0.25]
    mode_grid: list[str] = ["Standard Class", "Second Class", "First Class", "Same Day"]
    penalty: float = 250.0


def _build_profit_raw_row(f: dict) -> pd.DataFrame:
    """把 What-if 槓桿組成「原始格式單列」，其餘欄位留空 → 由 pipeline 以 SSOT 中位數/Unknown 補。"""
    import numpy as np
    from profit_data_pipeline import (
        NUMERIC_FEATURES, CATEGORICAL_FEATURES, DATE_COLUMN, TARGET_COLUMN,
    )
    row = {c: np.nan for c in NUMERIC_FEATURES}
    row.update({c: np.nan for c in CATEGORICAL_FEATURES})
    row[DATE_COLUMN] = f.get("order_date") or "2017-06-15 12:00"
    row[TARGET_COLUMN] = np.nan
    if f.get("shipping_mode"):
        row["Shipping Mode"] = f["shipping_mode"]
    if f.get("customer_segment"):
        row["Customer Segment"] = f["customer_segment"]
    if f.get("order_region"):
        row["Order Region"] = f["order_region"]
    if f.get("category_name"):
        row["Category Name"] = f["category_name"]
    if f.get("market"):
        row["Market"] = f["market"]
    if f.get("discount_rate") is not None:
        row["Order Item Discount Rate"] = f["discount_rate"]
    if f.get("product_price") is not None:
        row["Product Price"] = f["product_price"]
        row["Order Item Product Price"] = f["product_price"]
    if f.get("order_item_quantity") is not None:
        row["Order Item Quantity"] = f["order_item_quantity"]
    if f.get("days_for_shipment") is not None:
        row["Days for shipment (scheduled)"] = f["days_for_shipment"]
    sales = f.get("sales")
    if sales is None and f.get("product_price") is not None and f.get("order_item_quantity") is not None:
        sales = float(f["product_price"]) * float(f["order_item_quantity"]) * (1 - float(f.get("discount_rate") or 0))
    if sales is not None:
        row["Sales"] = sales
        row["Order Item Total"] = sales
        row["Sales per customer"] = sales
    return pd.DataFrame([row])


def _predict_profit_single(features: dict) -> float:
    """收益模型單筆評分（沿用 ProfitDataPipeline.transform 編碼，零漂移）。"""
    rt = _get_profit_runtime()
    ready = rt["pipe"].transform(_build_profit_raw_row(features))
    cols = rt["schema"]["feature_columns"]
    cat = rt["schema"].get("categorical_columns", [])
    codes = rt["schema"].get("categorical_codes", {})
    X = ready[cols].copy()
    for c in cat:
        if c in X.columns:
            cc = codes.get(c)
            X[c] = pd.Categorical(X[c], categories=cc) if cc is not None else X[c].astype("category")
    numeric_cols = [c for c in X.columns if c not in cat]
    X[numeric_cols] = X[numeric_cols].astype(float)
    return float(rt["booster"].predict(X)[0])


@app.get("/api/roi/summary")
async def roi_summary(
    penalty: float = 250.0,
    x_role: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """ROI 模擬器頂部 KPI：帳載利潤 vs 真價值(net-of-service)、被服務侵蝕、假性賺錢比例、EPAR。"""
    df = _load_decision_df()
    penalty = max(0.0, float(penalty))
    nos = df["profit_actual"] - df["true_label"] * penalty
    fp = int(((df["profit_actual"] > 0) & (nos < 0)).sum())
    profit_pos = int((df["profit_actual"] > 0).sum())
    book = float(df["profit_actual"].sum())
    nos_total = float(nos.sum())
    by_seg = []
    for seg, g in df.groupby("customer_segment"):
        g_nos = g["profit_actual"] - g["true_label"] * penalty
        by_seg.append({
            "segment": str(seg),
            "orders": int(len(g)),
            "book_profit": round(float(g["profit_actual"].sum()), 2),
            "net_of_service": round(float(g_nos.sum()), 2),
            "epar": round(float(g["epar"].sum()), 2),
        })
    by_seg.sort(key=lambda r: r["net_of_service"])
    return {
        "rows_orders": int(len(df)),
        "penalty_basis": penalty,
        "book_profit_total": round(book, 2),
        "net_of_service_total": round(nos_total, 2),
        "service_erosion_total": round(book - nos_total, 2),
        "false_positive_value_orders": fp,
        "profit_positive_orders": profit_pos,
        "false_positive_value_pct": round(fp / profit_pos, 4) if profit_pos else 0.0,
        "epar_total": round(float(df["epar"].sum()), 2),
        "by_segment": by_seg,
    }


@app.get("/api/roi/portfolio")
async def roi_portfolio(
    value_axis: str = "net_of_service",
    risk_axis: str = "p_late",
    segment: Optional[str] = None,
    region: Optional[str] = None,
    category: Optional[str] = None,
    shipping: Optional[str] = None,
    discount_band: Optional[str] = None,
    penalty: float = 250.0,
    max_points: int = 1500,
    x_role: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """真價值-風險散點 + 預期在險利潤(EPAR)名單；支援軸切換與 faceted 篩選。"""
    df = _apply_value_risk(_load_decision_df(), value_axis, risk_axis, max(0.0, float(penalty)))
    df = _filter_decision(df, segment, region, category, shipping, discount_band)
    total = int(len(df))

    # 散點封頂取樣，避免巨量 payload 與前端卡頓（不是無效迴圈，是保護）
    max_points = max(100, min(int(max_points), 3000))
    sample = df.sample(n=max_points, random_state=42) if total > max_points else df
    points = [
        {
            "id": make_display_order_id(r.order_id_hash),
            "value": round(float(r.value), 2),
            "risk": round(float(r.risk), 4),
            "epar": round(float(r.epar), 2),
            "segment": str(r.customer_segment),
            "region": str(r.order_region),
            "fp": int(r.is_false_positive_value),
        }
        for r in sample.itertuples(index=False)
    ]

    at_risk = df.sort_values("epar", ascending=False).head(50)
    at_risk_list = [
        {
            "id": make_display_order_id(r.order_id_hash),
            "epar": round(float(r.epar), 2),
            "profit_actual": round(float(r.profit_actual), 2),
            "p_late": round(float(r.p_late), 4),
            "net_of_service": round(float(r.net_of_service), 2),
            "segment": str(r.customer_segment),
            "region": str(r.order_region),
            "risk_bucket": str(r.risk_bucket),
        }
        for r in at_risk.itertuples(index=False)
    ]

    return {
        "value_axis": value_axis,
        "risk_axis": risk_axis,
        "total_filtered": total,
        "points_returned": len(points),
        "truncated": total > max_points,
        "points": points,
        "at_risk_list": at_risk_list,
        "filters": {
            "segments": sorted(_load_decision_df()["customer_segment"].dropna().unique().tolist()),
            "regions": sorted(_load_decision_df()["order_region"].dropna().unique().tolist()),
        },
    }


@app.post("/api/roi/optimize")
def roi_optimize(
    body: OptimizeRequest,
    x_role: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """[Manager] 在決策資料集上跑 ROI 最佳化（重用既有 ShippingOptimizer），附 EPAR 與客戶層彙整。"""
    role = get_role(x_role, authorization)
    require_manager(role)
    if ShippingOptimizer is None:
        raise HTTPException(status_code=500, detail="optimizer.py 載入失敗，請確認 core/ 目錄存在。")

    df = _load_decision_df()
    optimizer = ShippingOptimizer(
        budget=body.budget,
        upgrade_cost=body.upgrade_cost,
        delay_penalty=body.delay_penalty,
        risk_threshold=body.risk_threshold,
    )
    result = optimizer.run(predictions_path_or_df=df, output_dir=str(DATA_DIR), save_results=False)
    res = result.to_dict()

    dmap = df.set_index("order_id_hash")
    rollup: dict = {}
    for o in res.get("selected_orders", []):
        h = o.get("order_id_hash")
        if h in dmap.index:
            r = dmap.loc[h]
            o["profit_actual"] = round(float(r["profit_actual"]), 2)
            o["epar"] = round(float(r["epar"]), 2)
            o["customer_segment"] = str(r["customer_segment"])
            o["display_order_id"] = make_display_order_id(h)
            cid = str(r["customer_id_hash"])
            c = rollup.setdefault(cid, {
                "customer": make_display_order_id(cid).replace("ORD-", "CUST-"),
                "orders": 0, "epar": 0.0, "net_benefit": 0.0, "upgrade_cost": 0.0,
            })
            c["orders"] += 1
            c["epar"] += float(r["epar"])
            c["net_benefit"] += float(o.get("net_benefit", o.get("expected_saving", 0)) or 0)
            c["upgrade_cost"] += float(o.get("upgrade_cost", 0) or 0)

    customers = sorted(rollup.values(), key=lambda x: x["epar"], reverse=True)[:20]
    for c in customers:
        c["epar"] = round(c["epar"], 2)
        c["net_benefit"] = round(c["net_benefit"], 2)
        c["upgrade_cost"] = round(c["upgrade_cost"], 2)

    res["role"] = role
    res["customer_rollup"] = customers
    res["candidate_pool"] = int((df["p_late"] >= body.risk_threshold).sum())
    return res


@app.post("/api/profit/predict-single")
def profit_predict_single(
    body: ProfitSingleRequest,
    x_role: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """收益模型單筆預測（What-if 基礎）。"""
    profit_pred = _predict_profit_single(body.dict())
    return {"predicted_profit": round(profit_pred, 2)}


@app.post("/api/roi/whatif")
def roi_whatif(
    body: WhatIfRequest,
    x_role: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """What-if 模擬：掃 折扣 × 運送 網格 → 預測收益 + 預測延遲 → 預期淨值；回最佳組合 + 熱圖。"""
    # 網格封頂，避免巨量組合造成過載（非無效迴圈，是上限保護）
    discounts = list(dict.fromkeys([round(float(d), 4) for d in body.discount_grid]))[:8]
    modes = list(dict.fromkeys([str(m) for m in body.mode_grid]))[:6]
    if not discounts or not modes:
        raise HTTPException(status_code=400, detail="discount_grid 與 mode_grid 不可為空。")
    penalty = max(0.0, float(body.penalty))

    base = body.dict()
    grid = []
    best = None
    for disc in discounts:
        for mode in modes:
            feat = {**base, "discount_rate": disc, "shipping_mode": mode}
            profit_pred = _predict_profit_single(feat)
            delay_req = SingleOrderPredictRequest(
                shipping_mode=mode,
                order_region=body.order_region,
                days_for_shipment=body.days_for_shipment,
                product_price=body.product_price,
                order_item_quantity=body.order_item_quantity,
                customer_segment=body.customer_segment,
                market=body.market,
                category_name=body.category_name,
                order_date=body.order_date,
                order_item_discount_rate=disc,
            )
            delay = predict_single_order(delay_req)   # 重用既有延遲單筆預測（cached model）
            p_late = float(delay["p_late"])
            net = profit_pred - p_late * penalty
            cell = {
                "discount_rate": disc,
                "shipping_mode": mode,
                "profit_pred": round(profit_pred, 2),
                "p_late": round(p_late, 4),
                "expected_net": round(net, 2),
            }
            grid.append(cell)
            if best is None or net > best["expected_net"]:
                best = cell

    decision = "接單 (Accept)" if best and best["expected_net"] > 0 else "婉拒/重議 (Decline/Renegotiate)"
    return {
        "best": best,
        "decision": decision,
        "penalty_basis": penalty,
        "grid": grid,
        "discounts": discounts,
        "modes": modes,
    }


@app.get("/api/roi/trust-map")
async def roi_trust_map(
    x_role: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """預測-vs-實際校準 trust map（樣本外；由 build_decision_dataset.py 預算）。"""
    if not DECISION_TRUST_PATH.exists():
        raise HTTPException(
            status_code=404,
            detail="decision_trust_map.json 尚未產生，請先執行 scripts/build_decision_dataset.py",
        )
    with open(DECISION_TRUST_PATH, encoding="utf-8") as f:
        return json.load(f)


@app.get("/api/diagnose/deterioration")
async def diagnose_deterioration(
    unit: str = "segment",
    penalty: float = 250.0,
    x_role: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """[診斷] 帳戶劣化趨勢：客群/區域 逐月真價值與延遲率 + 簡單線性外推下月。"""
    import numpy as np
    col = "customer_segment" if unit == "segment" else "order_region"
    df = _load_decision_df().copy()
    penalty = max(0.0, float(penalty))
    df["net_of_service"] = df["profit_actual"] - df["true_label"] * penalty
    dt = pd.to_datetime(df["order_date"], errors="coerce")
    df = df.assign(_month=dt.dt.to_period("M").astype(str)).dropna(subset=["_month"])
    df = df[df["_month"] != "NaT"]

    series = []
    deteriorating = []
    for name, g in df.groupby(col):
        monthly = g.groupby("_month").agg(
            net_of_service=("net_of_service", "sum"),
            late_rate=("true_label", "mean"),
            orders=("order_id_hash", "count"),
        ).reset_index().sort_values("_month")
        if len(monthly) < 3:
            continue
        months = monthly["_month"].tolist()
        nos_vals = monthly["net_of_service"].tolist()
        late_vals = monthly["late_rate"].tolist()
        x = np.arange(len(nos_vals), dtype=float)
        slope = float(np.polyfit(x, nos_vals, 1)[0])
        forecast = float(np.polyval(np.polyfit(x, nos_vals, 1), len(nos_vals)))
        series.append({
            "group": str(name),
            "months": months,
            "net_of_service": [round(float(v), 2) for v in nos_vals],
            "late_rate": [round(float(v), 4) for v in late_vals],
            "orders": [int(v) for v in monthly["orders"].tolist()],
            "trend_slope": round(slope, 2),
            "forecast_next": round(forecast, 2),
        })
        deteriorating.append({
            "group": str(name),
            "trend_slope": round(slope, 2),
            "last_net_of_service": round(float(nos_vals[-1]), 2),
            "forecast_next": round(forecast, 2),
        })

    deteriorating.sort(key=lambda r: r["trend_slope"])
    return {
        "unit": unit,
        "penalty_basis": penalty,
        "series": series,
        "deteriorating": deteriorating,
        "note": "forecast 為各群逐月真價值的線性趨勢外推（簡單法），僅供方向參考。",
    }


@app.get("/api/profit/leakage-audit")
async def profit_leakage_audit(
    x_role: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """[診斷] 洩漏守門狀態 + actual/pred 欄位標示（落地點 4 的檢視層）。"""
    try:
        from profit_data_pipeline import LEAKAGE_COLUMNS, PII_COLUMNS, ID_COLUMNS, NOISE_COLUMNS
    except Exception:
        LEAKAGE_COLUMNS, PII_COLUMNS, ID_COLUMNS, NOISE_COLUMNS = [], [], [], []

    manifest = _load_profit_manifest()
    schema_path = DATA_DIR / "profit_feature_schema.json"
    feature_cols = []
    if schema_path.exists():
        with open(schema_path, encoding="utf-8") as f:
            feature_cols = json.load(f).get("feature_columns", [])

    leaked_in_features = [c for c in (list(LEAKAGE_COLUMNS) + list(PII_COLUMNS) + list(ID_COLUMNS)) if c in feature_cols]
    return {
        "gate_status": "PASS" if not leaked_in_features else "FAIL",
        "blocked": {
            "leakage": list(LEAKAGE_COLUMNS),
            "pii": list(PII_COLUMNS),
            "id": list(ID_COLUMNS),
            "noise": list(NOISE_COLUMNS),
        },
        "whitelist": [
            {"column": "Order Item Profit Ratio", "reason": "下單時已知的定價 margin，非由結果反推 → 合法特徵"},
        ],
        "identity_corr_guard": {
            "rule": "對非白名單的乘積式恆等（|corr|>0.98）報錯，margin×total 白名單放行",
            "enforced_in": "core/profit_data_pipeline.py::_validate",
        },
        "leaked_in_features": leaked_in_features,
        "feature_count": len(feature_cols),
        "column_labeling": {
            "profit_actual": "真利潤（驗證集回填的實際 Order Profit Per Order）",
            "profit_pred": "收益模型預測值（前瞻估計，非實際）",
            "true_label / late_actual": "驗證集實際是否延遲",
            "p_late / late_pred": "延遲模型預測機率",
        },
        "note": "收益欄一律標 actual/pred，不混稱『預測收益』當前瞻賭注（SLIDE 落地點 4）。",
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

@app.get("/api/geojson/countries")
async def get_countries_geojson():
    """代理抓取 GeoJSON，解決前端 CORS 問題"""
    import httpx
    url = "https://raw.githubusercontent.com/datasets/geo-countries/master/data/countries.geojson"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.get(url)
            return JSONResponse(content=res.json())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"GeoJSON 載入失敗：{e}")
