import pandas as pd
import numpy as np
import json
from pathlib import Path
import hashlib

from risk_policy import risk_bucket_for_probability


# ── 上傳資料驗證閘門（C）─────────────────────────────────────────────
class UploadValidationError(ValueError):
    """上傳資料未通過 schema 驗證（非訂單資料 / 欄位重複等）。由 API 轉成 400。"""


# 用來判斷「這是不是訂單資料」的已知欄位（一律小寫比對）
KNOWN_ORDER_COLUMNS = {
    "order id", "order id_hash", "order_id_hash",
    "order date (dateorders)", "order date", "order_date",
    "shipping mode", "order region", "order country", "category name",
    "customer segment", "type", "department name", "market",
    "days for shipment (scheduled)", "product price", "order item quantity",
    "order item discount rate", "order item profit ratio", "order profit per order",
    "late_delivery_risk",
}
MIN_KNOWN_COLUMNS = 3


def validate_upload_columns(columns) -> dict:
    """
    驗證上傳檔欄位是否像「有效訂單資料」。不通過則 raise UploadValidationError。
    請傳入『原始欄名列表』（含重複，未經 pandas 去重）以正確偵測重複欄。
    """
    raw = [str(c).strip() for c in columns]
    lower = [c.lower() for c in raw]

    # 1) 重複欄位（pandas 讀檔會靜默把第二個同名欄改名，故須在原始欄名上檢查）
    seen, dups = set(), set()
    for c in lower:
        if c in seen:
            dups.add(c)
        seen.add(c)
    if dups:
        raise UploadValidationError(
            f"偵測到重複欄位：{sorted(dups)}。請移除重複欄位後重新上傳。"
        )

    # 2) 是否像訂單資料（至少要對上 N 個已知欄位，否則視為非訂單資料）
    matched = [c for c in lower if c in KNOWN_ORDER_COLUMNS]
    if len(matched) < MIN_KNOWN_COLUMNS:
        raise UploadValidationError(
            f"這份檔不像有效的訂單資料：只辨識到 {len(matched)} 個已知欄位"
            f"（至少需 {MIN_KNOWN_COLUMNS} 個）。請確認包含如 "
            f"Order Id / Shipping Mode / Order Region / order date (DateOrders) 等欄位。"
        )

    return {"matched_known_columns": matched, "total_columns": len(raw)}


def predict_uploaded_csv(file_path_or_buffer, mapping_path: Path, model_path: Path) -> pd.DataFrame:
    """
    Parses a raw CSV file containing new orders, maps categorical fields using 
    feature_mapping.json, aligns features with train_ready.csv column order, 
    and predicts delay probabilities using xgboost_model.json.
    """
    try:
        import xgboost as xgb
    except Exception as exc:
        raise RuntimeError(
            "xgboost/OpenMP runtime is unavailable. On macOS, install libomp "
            "before using CSV upload prediction."
        ) from exc

    # Load mappings
    with open(mapping_path, "r", encoding="utf-8") as f:
        mappings = json.load(f)
        
    # Load raw dataframe
    try:
        df = pd.read_csv(file_path_or_buffer, encoding="latin-1")
    except UnicodeDecodeError:
        df = pd.read_csv(file_path_or_buffer, encoding="utf-8")
        
    # Columns we need to preserve for metadata
    col_mapping = {
        "Order Id": "order_id_hash",
        "Order Id_hash": "order_id_hash",
        "order_id_hash": "order_id_hash",
        "Shipping Mode": "shipping_mode",
        "Order Region": "order_region",
        "order date (DateOrders)": "order_date",
        "Order Date": "order_date",
        "order_date": "order_date",
    }
    
    meta_df = pd.DataFrame(index=df.index)
    for orig_col, target_col in col_mapping.items():
        match = next((c for c in df.columns if c.lower() == orig_col.lower()), None)
        if match:
            meta_df[target_col] = df[match]
            
    # Fallback missing metadata
    if "order_id_hash" not in meta_df.columns:
        meta_df["order_id_hash"] = [hashlib.sha256(f"upload_order_{i}".encode()).hexdigest()[:32] for i in range(len(df))]
    else:
        meta_df["order_id_hash"] = meta_df["order_id_hash"].apply(
            lambda x: hashlib.sha256(str(x).encode()).hexdigest()[:32] if len(str(x)) < 24 else str(x)
        )
        
    if "shipping_mode" not in meta_df.columns:
        meta_df["shipping_mode"] = "Standard Class"
    if "order_region" not in meta_df.columns:
        meta_df["order_region"] = "Western Europe"
    if "order_date" not in meta_df.columns:
        # 不捏造日期：缺日期就留空(NaT)，避免假月份污染月份統計
        meta_df["order_date"] = pd.NaT
        
    # Feature engineering for XGBoost
    X = pd.DataFrame(index=df.index)

    # 載入服務一致化產物（與訓練相同的中位數/編碼器類別）；無則回退舊行為（問題四 bug 1/2）
    serving_medians, serving_label_classes = {}, {}
    artifact_path = Path(mapping_path).parent / "serving_artifacts.json"
    if artifact_path.exists():
        try:
            with open(artifact_path, "r", encoding="utf-8") as f:
                _art = json.load(f)
            serving_medians = _art.get("feature_medians", {}) or {}
            serving_label_classes = _art.get("label_classes", {}) or {}
        except Exception:
            pass

    # 1. Numerical（缺值用『訓練中位數』填補，與訓練一致；無產物時回退 0）
    num_features = [
        "Days for shipment (scheduled)",
        "Product Price",
        "Order Item Quantity",
        "Order Item Discount Rate",
        "Order Item Profit Ratio",
        "Order Profit Per Order"
    ]
    for col in num_features:
        match = next((c for c in df.columns if c.lower() == col.lower()), None)
        fill_val = serving_medians.get(col, 0.0)
        if match:
            X[col] = pd.to_numeric(df[match], errors="coerce").fillna(fill_val)
        else:
            X[col] = fill_val
            
    # 2. Date features
    date_col = next((c for c in df.columns if "date" in c.lower()), None)
    if date_col:
        date_series = pd.to_datetime(df[date_col], errors="coerce")
        # 與訓練端(data_pipeline)一致：缺值哨兵用 -1（原本服務端用 0/6/12 造成訓練/服務不一致）
        X["order_dayofweek"] = date_series.dt.dayofweek.fillna(-1).astype(int)
        X["order_month"] = date_series.dt.month.fillna(-1).astype(int)
        X["order_hour"] = date_series.dt.hour.fillna(-1).astype(int)
        X["order_is_weekend"] = (date_series.dt.dayofweek >= 5).fillna(0).astype(int)
    else:
        X["order_dayofweek"] = -1
        X["order_month"] = -1
        X["order_hour"] = -1
        X["order_is_weekend"] = 0
        
    # 3. Label Encoded features
    label_cols = ["Order Region", "Category Name", "Order Country"]
    for col in label_cols:
        match = next((c for c in df.columns if c.lower() == col.lower()), None)
        classes = serving_label_classes.get(col, mappings[col])
        if match:
            val_to_idx = {val: idx for idx, val in enumerate(classes)}
            X[f"{col}_encoded"] = df[match].astype(str).map(val_to_idx).fillna(0).astype(int)
        else:
            X[f"{col}_encoded"] = 0
            
    # 4. One-Hot encoded features
    one_hot_groups = ["Shipping Mode", "Customer Segment", "Type", "Department Name", "Market"]
    for col in mappings["feature_columns"]:
        if col not in X.columns:
            X[col] = False
            
    for group in one_hot_groups:
        match = next((c for c in df.columns if c.lower() == group.lower()), None)
        if match:
            for i, val in enumerate(df[match]):
                dummy_col = f"{group}_{val}"
                if dummy_col in X.columns:
                    X.loc[i, dummy_col] = True
                    
    # Reorder columns & align
    X = X[mappings["feature_columns"]]
    X = X.fillna(0)
    
    # Load model and predict
    model = xgb.XGBClassifier()
    model.load_model(str(model_path))
    y_prob = model.predict_proba(X)[:, 1]
    
    # Build final dataframe
    active_df = meta_df.copy()
    active_df["p_late"] = y_prob.round(4)
    
    # Ground truth label matching
    target_match = next((c for c in df.columns if c.lower() == "late_delivery_risk"), None)
    if target_match:
        active_df["true_label"] = df[target_match].astype(int)
    else:
        # Fallback to pseudo ground truth
        active_df["true_label"] = (active_df["p_late"] >= 0.5).astype(int)
        
    active_df["risk_bucket"] = active_df["p_late"].map(risk_bucket_for_probability)
    
    active_df["expected_penalty"] = (active_df["p_late"] * 250.0).round(2)
    
    # 實作 SSOT Rate Card 動態運費計費
    shipping_base_costs = {
        "Standard Class": 50.0,
        "Second Class": 80.0,
        "First Class": 120.0,
        "Same Day": 180.0,
    }
    region_multipliers = {
        "Western Europe": 1.1,
        "Central America": 0.9,
        "South America": 0.95,
        "Northern Europe": 1.25,
        "Eastern Europe": 1.05,
        "North America": 1.15,
        "East Asia": 1.2,
        "Oceania": 1.3,
    }
    def get_dynamic_upgrade_cost(row):
        mode = row.get("shipping_mode", "Standard Class")
        region = row.get("order_region", "Unknown")
        base = shipping_base_costs.get(mode, 80.0)
        mult = region_multipliers.get(region, 1.0)
        return round(base * mult, 2)
        
    active_df["upgrade_cost"] = active_df.apply(get_dynamic_upgrade_cost, axis=1)
    
    return active_df
