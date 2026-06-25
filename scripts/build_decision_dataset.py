"""
build_decision_dataset.py
SLIDE — 統一決策資料集建置（最佳化ROI模擬器 / 模型診斷的資料基礎）

目的：把「收益(真利潤/預測) × 延遲(真延遲/預測) × 客戶維度」整合到「同一批訂單」上，
產出 data/processed/decision_dataset.csv（order-level，一訂單一列）。

不臆測、不自造回填：
  - 「真延遲」取自延遲驗證集 predictions.csv 的 true_label（驗證集真答案）。
  - 「真利潤」取自原始 DataCo CSV 的 Order Profit Per Order（帳載/實際利潤）。
  - 「收益預測」用既有 LightGBM 收益模型對同一批訂單評分（沿用既有 transform 編碼，零漂移）。

零衝突：本腳本只「讀」predictions.csv 與既有模型產物，不修改任何既有檔案；
        僅「新增」decision_dataset.csv 與 decision_dataset_summary.json。

對齊邏輯（已實測 22,544/22,544 命中）：
  延遲系統 order_id_hash = sha256("EDIS_2026:" + str(Order Id))   ← 見 core/security_utils.py
  以此把原始資料的真利潤與維度 join 回 predictions.csv 那批訂單。

粒度說明：
  predictions.csv 是「order-item」粒度且 order_id_hash 會重複（一訂單多明細）。
  決策單位為「訂單」：profit_actual 與 profit_pred 皆以「該訂單所有明細加總」計算，兩者可比。
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.profit_data_pipeline import ProfitDataPipeline, TARGET_COLUMN  # noqa: E402

RAW_PATH = BASE_DIR / "data" / "raw" / "DataCoSupplyChainDataset.csv"
PRED_PATH = BASE_DIR / "data" / "processed" / "predictions.csv"
SCHEMA_PATH = BASE_DIR / "data" / "processed" / "profit_feature_schema.json"
ARTIFACTS_PATH = BASE_DIR / "models" / "profit" / "serving_artifacts.json"
MODEL_PATH = BASE_DIR / "models" / "profit_lightgbm_model.txt"

OUT_CSV = BASE_DIR / "data" / "processed" / "decision_dataset.csv"
OUT_SUMMARY = BASE_DIR / "data" / "processed" / "decision_dataset_summary.json"
OUT_TRUST = BASE_DIR / "data" / "processed" / "decision_trust_map.json"

PROFIT_PRED_PATH = BASE_DIR / "data" / "processed" / "profit_predictions.csv"
PROFIT_TEST_META_PATH = BASE_DIR / "data" / "processed" / "profit_test_metadata.csv"
PROFIT_HASH_SALT = "SLIDE_PROFIT_2026"   # 對齊 profit_data_pipeline（注意：無冒號、取前16碼）

DELAY_HASH_SALT = "EDIS_2026"          # 對齊 core/security_utils.DeIdentifier
DEFAULT_PENALTY = 250.0                # 對齊 optimizer 的 delay_penalty 預設
HIGH_T, MED_T = 0.5, 0.3               # 對齊 model_pipeline RISK_THRESHOLDS

# 原始欄位名
COL_ORDER_ID = "Order Id"
COL_CUSTOMER_ID = "Customer Id"
COL_PROFIT = "Order Profit Per Order"
COL_SEGMENT = "Customer Segment"
COL_REGION = "Order Region"
COL_CATEGORY = "Category Name"
COL_SHIPPING = "Shipping Mode"
COL_DISCOUNT = "Order Item Discount Rate"
COL_DATE = "order date (DateOrders)"


def _delay_hash(order_id: str) -> str:
    return hashlib.sha256(f"{DELAY_HASH_SALT}:{order_id}".encode("utf-8")).hexdigest()


def _risk_bucket(p: float) -> str:
    if p >= HIGH_T:
        return "High"
    if p >= MED_T:
        return "Medium"
    return "Low"


def _require(path: Path, hint: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"缺少必要檔案：{path}\n  → {hint}")


def score_profit(raw_items: pd.DataFrame) -> np.ndarray:
    """用既有 LightGBM 收益模型對 raw 明細評分（沿用 ProfitDataPipeline.transform 編碼）。"""
    import lightgbm as lgb

    with open(ARTIFACTS_PATH, encoding="utf-8") as f:
        artifacts = json.load(f)
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        schema = json.load(f)

    pdp = ProfitDataPipeline()
    pdp.artifacts = artifacts
    ready = pdp.transform(raw_items)               # 全數值特徵 + 目標欄（整數類別碼）

    feature_columns = schema["feature_columns"]
    cat_cols = schema.get("categorical_columns", [])
    cat_codes = schema.get("categorical_codes", {})

    X = ready[feature_columns].copy()
    # 與 ProfitModelPipeline._load_ready_frame 完全一致：整數碼 → 固定 categories 的 category dtype
    for c in cat_cols:
        if c in X.columns:
            codes = cat_codes.get(c)
            X[c] = pd.Categorical(X[c], categories=codes) if codes is not None else X[c].astype("category")
    numeric_cols = [c for c in X.columns if c not in cat_cols]
    X[numeric_cols] = X[numeric_cols].astype(float)

    booster = lgb.Booster(model_file=str(MODEL_PATH))
    return booster.predict(X.values)


def _profit_hash(order_id: str) -> str:
    return hashlib.sha256((PROFIT_HASH_SALT + order_id).encode("utf-8")).hexdigest()[:16]


def _group_metrics(df: pd.DataFrame, by: str, kind: str, min_n: int = 30) -> list:
    """各群可信度指標。kind='delay' → AUC/late_rate；kind='profit' → MAE/RMSE/R2/resid。"""
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score, roc_auc_score

    rows = []
    for name, g in df.groupby(by):
        n = int(len(g))
        if n < min_n:
            continue
        if kind == "delay":
            y, p = g["true_label"].to_numpy(), g["p_late"].to_numpy()
            auc = float(roc_auc_score(y, p)) if len(set(y.tolist())) > 1 else None
            rows.append({
                "group": str(name), "n": n,
                "auc": round(auc, 4) if auc is not None else None,
                "late_rate": round(float(y.mean()), 4),
                "mean_p_late": round(float(p.mean()), 4),
            })
        else:
            a, pr = g["actual_profit"].to_numpy(float), g["predicted_profit"].to_numpy(float)
            r2 = float(r2_score(a, pr)) if n >= 2 and a.std() > 1e-9 else None
            rows.append({
                "group": str(name), "n": n,
                "mae": round(float(mean_absolute_error(a, pr)), 2),
                "rmse": round(float(np.sqrt(mean_squared_error(a, pr))), 2),
                "r2": round(r2, 4) if r2 is not None else None,
                "resid_mean": round(float((a - pr).mean()), 2),
            })
    rows.sort(key=lambda r: r["n"], reverse=True)
    return rows


def build_trust_map(decision_df: pd.DataFrame, raw: pd.DataFrame) -> dict:
    """預測-vs-實際校準 trust map（誠實：兩面都用各自的『樣本外』測試集）。

    - 延遲：用 decision_df 的 p_late/true_label（延遲隨機驗證集，對延遲模型樣本外）。
    - 收益：用 profit_predictions.csv（收益時間測試集，對收益模型樣本外），
            以 16 碼 profit hash join 回原始維度。
    """
    delay = {
        "by_segment": _group_metrics(decision_df, "customer_segment", "delay"),
        "by_region": _group_metrics(decision_df, "order_region", "delay"),
    }

    profit = {"by_segment": [], "by_region": [], "available": False}
    if PROFIT_PRED_PATH.exists() and PROFIT_TEST_META_PATH.exists():
        pp = pd.read_csv(PROFIT_PRED_PATH)
        meta = pd.read_csv(PROFIT_TEST_META_PATH)
        if len(pp) == len(meta):
            pp = pp.reset_index(drop=True)
            meta = meta.reset_index(drop=True)
            pp["order_id_hash16"] = meta["order_id_hash"].to_numpy()
            raw16 = raw.copy()
            raw16["order_id_hash16"] = raw16[COL_ORDER_ID].astype(str).map(_profit_hash)
            dims = raw16.groupby("order_id_hash16").agg(
                customer_segment=(COL_SEGMENT, "first"),
                order_region=(COL_REGION, "first"),
            ).reset_index()
            merged = pp.merge(dims, on="order_id_hash16", how="left").dropna(
                subset=["customer_segment", "order_region"])
            if len(merged):
                profit = {
                    "by_segment": _group_metrics(merged, "customer_segment", "profit"),
                    "by_region": _group_metrics(merged, "order_region", "profit"),
                    "available": True,
                    "rows": int(len(merged)),
                }

    return {
        "delay": delay,
        "profit": profit,
        "note": "delay=樣本外(延遲隨機驗證集); profit=樣本外(收益時間測試集)。"
                "決策資料集內的 profit_pred 多為樣本內，不用於本 trust map。",
    }


def build() -> dict:
    print("[1/6] 檢查輸入檔 ...")
    _require(RAW_PATH, "把 DataCoSupplyChainDataset.csv 放到 data/raw/")
    _require(PRED_PATH, "先跑延遲管線產出 predictions.csv")
    _require(MODEL_PATH, "先跑 profit_model_pipeline.py 產出收益模型")
    _require(SCHEMA_PATH, "先跑 profit_data_pipeline.py 產出 schema")
    _require(ARTIFACTS_PATH, "先跑 profit_data_pipeline.py 產出 serving_artifacts.json")

    print("[2/6] 載入 predictions.csv（延遲驗證集，order-item 粒度）...")
    pred = pd.read_csv(PRED_PATH)
    val_hashes = set(pred["order_id_hash"].unique())
    print(f"      明細 {len(pred):,} 列；唯一訂單 {len(val_hashes):,}")

    # 訂單層彙總：延遲面
    pred_grp = pred.groupby("order_id_hash")
    delay_order = pd.DataFrame({
        "p_late": pred_grp["p_late"].mean(),                 # 訂單代表延遲機率
        "true_label": pred_grp["true_label"].max(),          # 任一明細延遲 → 訂單延遲
        "upgrade_cost": pred_grp["upgrade_cost"].max(),      # 同訂單通常一致，取保守上限
        "shipping_mode": pred_grp["shipping_mode"].first(),
        "order_region": pred_grp["order_region"].first(),
        "order_date": pred_grp["order_date"].first(),
    }).reset_index()

    print("[3/6] 載入原始資料、重建延遲 hash、篩出驗證集那批訂單的所有明細 ...")
    raw = pd.read_csv(RAW_PATH, encoding="latin-1")
    raw["order_id_hash"] = raw[COL_ORDER_ID].astype(str).map(_delay_hash)
    raw_val = raw[raw["order_id_hash"].isin(val_hashes)].copy()
    print(f"      命中明細 {len(raw_val):,} 列（含同訂單非測試分割之明細，計入訂單帳載總利潤）")

    matched = raw_val["order_id_hash"].nunique()
    if matched != len(val_hashes):
        print(f"      ⚠️ 僅 {matched:,}/{len(val_hashes):,} 訂單在原始資料找到（差集將被剔除）")

    print("[4/6] 用收益模型對 raw 明細評分（item-level）...")
    raw_val["__profit_pred_item__"] = score_profit(raw_val)

    print("[5/6] 訂單層彙總：真利潤(加總) + 收益預測(加總) + 維度 ...")
    raw_grp = raw_val.groupby("order_id_hash")
    profit_order = pd.DataFrame({
        "profit_actual": raw_grp[COL_PROFIT].sum(),
        "profit_pred": raw_grp["__profit_pred_item__"].sum(),
        "customer_segment": raw_grp[COL_SEGMENT].first(),
        "category_name": raw_grp[COL_CATEGORY].first(),
        "discount_rate": raw_grp[COL_DISCOUNT].mean(),
        "customer_id_hash": raw_grp[COL_CUSTOMER_ID].first().astype(str).map(_delay_hash),
    }).reset_index()

    df = delay_order.merge(profit_order, on="order_id_hash", how="inner")

    # 衍生欄（PENALTY 預設 250，可被 API 端覆寫重算）
    df["expected_penalty"] = (df["p_late"] * DEFAULT_PENALTY).round(4)
    df["net_of_service"] = (df["profit_actual"] - df["true_label"] * DEFAULT_PENALTY).round(4)
    df["epar"] = (df["profit_actual"] * df["p_late"]).round(4)
    df["profit_resid"] = (df["profit_actual"] - df["profit_pred"]).round(4)
    df["is_false_positive_value"] = ((df["profit_actual"] > 0) & (df["net_of_service"] < 0)).astype(int)
    df["risk_bucket"] = df["p_late"].map(_risk_bucket)
    for col in ("p_late", "profit_actual", "profit_pred", "upgrade_cost", "discount_rate"):
        df[col] = df[col].round(4)

    cols = [
        "order_id_hash", "customer_id_hash", "order_date",
        "customer_segment", "order_region", "category_name", "shipping_mode",
        "discount_rate", "p_late", "true_label", "risk_bucket",
        "profit_actual", "profit_pred", "net_of_service", "epar", "profit_resid",
        "is_false_positive_value", "upgrade_cost", "expected_penalty",
    ]
    df = df[cols]

    # 完整性自檢（避免下游 overflow/NaN）
    assert df["order_id_hash"].is_unique, "order_id_hash 不唯一"
    null_cols = df.columns[df.isna().any()].tolist()
    if null_cols:
        raise ValueError(f"決策資料集出現 NaN 欄：{null_cols}")

    print(f"[6/6] 寫出 {OUT_CSV.name} ...")
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False)

    n = len(df)
    book = float(df["profit_actual"].sum())
    nos = float(df["net_of_service"].sum())
    fp = int(df["is_false_positive_value"].sum())
    profit_pos = int((df["profit_actual"] > 0).sum())
    summary = {
        "rows_orders": n,
        "book_profit_total": round(book, 2),
        "net_of_service_total": round(nos, 2),
        "service_erosion_total": round(book - nos, 2),
        "false_positive_value_orders": fp,
        "profit_positive_orders": profit_pos,
        "false_positive_value_pct_of_profitable": round(fp / profit_pos, 4) if profit_pos else 0.0,
        "epar_total": round(float(df["epar"].sum()), 2),
        "penalty_basis": DEFAULT_PENALTY,
        "profit_r2_on_decision_set": round(
            float(1 - (df["profit_resid"] ** 2).sum()
                  / (((df["profit_actual"] - df["profit_actual"].mean()) ** 2).sum() or 1.0)), 4),
    }
    with open(OUT_SUMMARY, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("[trust map] 計算預測-vs-實際校準（樣本外）...")
    trust = build_trust_map(df, raw)
    with open(OUT_TRUST, "w", encoding="utf-8") as f:
        json.dump(trust, f, ensure_ascii=False, indent=2)
    print(f"  delay segments={len(trust['delay']['by_segment'])}, "
          f"profit available={trust['profit'].get('available')}")

    print("\n=== 決策資料集摘要 ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n[完成] {OUT_CSV}\n        {OUT_SUMMARY}")
    return summary


if __name__ == "__main__":
    build()
