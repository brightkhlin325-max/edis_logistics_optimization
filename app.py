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
import re
from pathlib import Path
from typing import Optional

try:
    from fastapi import FastAPI, HTTPException, Header, Request, UploadFile, File, BackgroundTasks
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

# DataFrame 快取機制
PREDICTIONS_CACHE = {}

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


@app.on_event("startup")
async def startup_event():
    """啟動背景磁碟清理任務，每小時清理過期 24 小時的暫存檔"""
    init_db()
    import asyncio
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

    asyncio.create_task(cleanup_loop())


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


def build_llm_safe_payload(optimization_result: dict, max_sample_orders: int = 3) -> dict:
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
    }


def build_llm_prompt(safe_payload: dict, language: str = "zh-TW", question: str = "") -> str:
    question_text = question.strip() or "請產生本批物流調度的主管摘要。"
    return (
        "你是物流決策助理。請只根據下列去識別化資料，產出主管可直接閱讀的摘要。"
        "不得推測或要求任何個資，也不得還原雜湊識別碼。"
        f"輸出語言：{language}。"
        f"使用者問題：{question_text}。"
        "請用三段：1. 決策建議 2. 主要風險原因 3. 預算與下一步。"
        f"\n\n資料：{json.dumps(safe_payload, ensure_ascii=False, default=str)}"
    )


def is_logistics_question(question: str) -> bool:
    """Return True when the user asks about EDIS logistics decision context."""
    text = (question or "").strip().lower()
    if not text:
        return True

    allowed_terms = [
        "物流", "訂單", "延遲", "準時", "配送", "運送", "調度", "升級", "風險",
        "預測", "機率", "模型", "門檻", "預算", "成本", "罰金", "損失", "效益",
        "roi", "sla", "x因子", "x 因子", "lime", "region", "shipping", "budget",
        "risk", "delay", "late", "delivery", "shipment", "order", "optimize",
        "optimization", "predict", "prediction", "model", "threshold", "penalty",
        "cost", "route", "dispatch", "upgrade",
    ]
    return any(term in text for term in allowed_terms)


def off_topic_llm_response(question: str) -> str:
    return (
        "我只能回答與目前訂單預測、延遲風險、物流調度、預算最佳化、模型門檻與 X 因子解釋相關的問題。\n"
        "請改問例如：「這批訂單哪些最該優先處理？」、「為什麼延遲風險高？」或「預算有限時該怎麼調度？」"
    )


def local_llm_fallback(safe_payload: dict) -> str:
    opt = safe_payload.get("optimization", {})
    analysis = safe_payload.get("manager_analysis", {})
    return (
        f"決策建議：{analysis.get('headline') or '建議優先處理高風險且淨效益為正的訂單。'}\n"
        f"主要風險原因：{analysis.get('recommended_policy') or '延遲機率、運送模式與區域風險是主要判斷依據。'}\n"
        f"預算與下一步：本次預算 USD ${float(opt.get('budget') or 0):,.0f}，"
        f"選出 {int(opt.get('selected_count') or 0)} 筆訂單，"
        f"預估淨效益 USD ${float(opt.get('expected_total_saving') or 0):,.0f}；"
        "若無外部 LLM API key，系統會使用此本地摘要作為安全 fallback。"
    )


def get_llm_config() -> dict:
    """
    Read the backend-wide LLM provider settings.

    Configure before starting uvicorn:
      EDIS_LLM_PROVIDER=local|openai|openai_compatible|gemini|claude|ollama
      EDIS_LLM_MODEL=<provider model name>
      EDIS_LLM_API_KEY=<provider API key>
      EDIS_LLM_API_URL=<optional custom endpoint>
    """
    provider = os.environ.get("EDIS_LLM_PROVIDER", "").strip().lower()
    if not provider:
        provider = "openai" if (os.environ.get("EDIS_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")) else "local"

    provider_keys = {
        "openai": os.environ.get("OPENAI_API_KEY"),
        "openai_compatible": os.environ.get("OPENAI_API_KEY"),
        "gemini": os.environ.get("GEMINI_API_KEY"),
        "claude": os.environ.get("ANTHROPIC_API_KEY"),
        "ollama": "",
        "local": "",
    }
    api_key = os.environ.get("EDIS_LLM_API_KEY") or provider_keys.get(provider, "")

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

    return {
        "provider": provider,
        "api_key": api_key,
        "api_url": os.environ.get("EDIS_LLM_API_URL") or default_urls.get(provider),
        "model": os.environ.get("EDIS_LLM_MODEL") or default_models.get(provider),
    }


def _llm_fallback(provider: str, model: str | None, fallback_text: str, error: str | None = None) -> dict:
    return {
        "used_external_llm": False,
        "provider": "local_fallback",
        "configured_provider": provider,
        "model": model,
        "brief_text": fallback_text,
        "error": error,
    }


def call_configured_llm(prompt: str, fallback_text: str) -> dict:
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
        return _llm_fallback(provider, model, fallback_text, f"{provider} 未設定 API key，已使用本地摘要 fallback。")

    try:
        from urllib.parse import quote
        from urllib.request import Request as UrlRequest, urlopen

        if provider == "openai":
            body = json.dumps({
                "model": model,
                "input": [
                    {
                        "role": "system",
                        "content": "You produce concise logistics executive briefs from de-identified data only.",
                    },
                    {"role": "user", "content": prompt},
                ],
                "reasoning": {"effort": "low"},
                "text": {"verbosity": "low"},
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
            text = payload.get("output_text", "").strip()
            if not text:
                output = payload.get("output", [])
                chunks = []
                for item in output:
                    for content in item.get("content", []):
                        if content.get("type") in {"output_text", "text"}:
                            chunks.append(content.get("text", ""))
                text = "".join(chunks).strip()

        elif provider == "openai_compatible":
            body = json.dumps({
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": "You produce concise logistics executive briefs from de-identified data only.",
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
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
            text = payload["choices"][0]["message"]["content"].strip()

        elif provider == "gemini":
            gemini_url = api_url or f"https://generativelanguage.googleapis.com/v1beta/models/{quote(model)}:generateContent?key={api_key}"
            body = json.dumps({
                "contents": [
                    {"parts": [{"text": prompt}]}
                ],
                "generationConfig": {"temperature": 0.2},
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
            body = json.dumps({
                "model": model,
                "max_tokens": 800,
                "temperature": 0.2,
                "messages": [{"role": "user", "content": prompt}],
            }).encode("utf-8")
            req = UrlRequest(
                api_url,
                data=body,
                method="POST",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": os.environ.get("EDIS_LLM_ANTHROPIC_VERSION", "2023-06-01"),
                    "Content-Type": "application/json",
                },
            )
            with urlopen(req, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
            text = "".join(block.get("text", "") for block in payload.get("content", [])).strip()

        else:  # ollama
            body = json.dumps({
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": "You produce concise logistics executive briefs from de-identified data only.",
                    },
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
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
            "brief_text": text,
            "error": None,
        }
    except Exception as e:
        return _llm_fallback(provider, model, fallback_text, f"LLM 呼叫失敗，已使用本地摘要 fallback：{str(e)}")



# ── 路由 ──────────────────────────────────────────────────────────────────────


# ── 登入驗證 ──────────────────────────────────────────────────────────────────
from auth import init_db, verify_user, generate_token

init_db()

class LoginRequest(BaseModel):
    username: str
    password: str

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
    return {"system": "EDIS", "version": "1.0.0", "docs": "/docs"}


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
):
    """
    [Viewer / Manager] 回傳去識別化的訂單延遲風險列表。
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

    # 應用過濾器
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
        action = "立即啟動升級調度；高風險訂單比例偏高，需優先保護 SLA 與客戶承諾。"
    elif positive_roi_orders > 0:
        action = "選擇性升級 ROI 為正的高風險訂單，並每日追蹤區域與運送模式異常。"
    else:
        action = "維持原配送策略，將高風險訂單列入監控清單。"

    return {
        "total_orders": total_orders,
        "at_risk_orders": at_risk_orders,
        "at_risk_rate": round(at_risk_rate, 4),
        "service_level_target": 0.9,
        "estimated_service_level": round(estimated_service_level, 4),
        "expected_penalty_exposure": round(exposure, 2),
        "positive_roi_orders": positive_roi_orders,
        "recommended_budget": round(recommended_budget, 2),
        "recommended_action": action,
        "top_regions": top_breakdown("order_region"),
        "top_shipping_modes": top_breakdown("shipping_mode"),
        "data_quality_note": "以目前 predictions.csv 計算；實務上應每日更新並與真實到貨結果回寫比對。",
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


@app.post("/api/llm/manager-brief")
def generate_manager_llm_brief(
    request: LLMBriefRequest,
    x_role: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
    x_session_id: Optional[str] = Header(default=None),
):
    """
    [Manager 限定] 以去識別化最佳化結果產生 LLM 主管摘要。

    使用 EDIS_LLM_PROVIDER / EDIS_LLM_MODEL / EDIS_LLM_API_KEY 後台設定。
    未設定、呼叫失敗，或 provider=local 時，回傳本地規則摘要作為 demo-safe fallback。
    """
    role = get_role(x_role, authorization)
    require_manager(role)

    if not is_logistics_question(request.question):
        config = get_llm_config()
        brief_text = off_topic_llm_response(request.question)
        return {
            "role": role,
            "data_boundary": {
                "de_identified_only": True,
                "sent_fields": [],
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
            "llm": {
                "used_external_llm": False,
                "provider": "guardrail",
                "configured_provider": config["provider"],
                "model": config["model"],
                "error": None,
            },
            "guard_triggered": True,
            "brief_text": brief_text,
            "safe_prompt": "",
            "safe_payload": {},
            "manager_analysis": {},
        }

    pred_path = get_predictions_path(x_session_id)
    optimization_result = build_optimization_result(request, pred_path, save_results=False)
    safe_payload = build_llm_safe_payload(
        optimization_result,
        max_sample_orders=request.max_sample_orders,
    )
    prompt = build_llm_prompt(safe_payload, language=request.language, question=request.question)
    fallback_text = local_llm_fallback(safe_payload)
    llm_result = call_configured_llm(prompt, fallback_text)

    return {
        "role": role,
        "data_boundary": {
            "de_identified_only": True,
            "sent_fields": [
                "order_id_hash",
                "risk_bucket",
                "p_late",
                "recommended_action",
                "expected_penalty",
                "upgrade_cost",
                "net_benefit",
                "top_x_factors",
                "aggregate_optimization_metrics",
            ],
            "excluded_fields": safe_payload["data_policy"]["excluded_fields"],
        },
        "llm": {
            "used_external_llm": llm_result["used_external_llm"],
            "provider": llm_result["provider"],
            "configured_provider": llm_result.get("configured_provider", llm_result["provider"]),
            "model": llm_result["model"],
            "error": llm_result["error"],
        },
        "brief_text": llm_result["brief_text"],
        "safe_prompt": prompt,
        "safe_payload": safe_payload,
        "manager_analysis": optimization_result.get("manager_analysis", {}),
    }


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
