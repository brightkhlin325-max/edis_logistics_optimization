import pandas as pd
import numpy as np
import json
from pathlib import Path
import hashlib

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
        meta_df["order_date"] = "6/10/2026 12:00"
        
    # Feature engineering for XGBoost
    X = pd.DataFrame(index=df.index)
    
    # 1. Numerical
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
        if match:
            X[col] = pd.to_numeric(df[match], errors="coerce")
        else:
            X[col] = 0.0
            
    # 2. Date features
    date_col = next((c for c in df.columns if "date" in c.lower()), None)
    if date_col:
        date_series = pd.to_datetime(df[date_col], errors="coerce")
        X["order_dayofweek"] = date_series.dt.dayofweek.fillna(0).astype(int)
        X["order_month"] = date_series.dt.month.fillna(6).astype(int)
        X["order_hour"] = date_series.dt.hour.fillna(12).astype(int)
        X["order_is_weekend"] = (date_series.dt.dayofweek >= 5).fillna(0).astype(int)
    else:
        X["order_dayofweek"] = 0
        X["order_month"] = 6
        X["order_hour"] = 12
        X["order_is_weekend"] = 0
        
    # 3. Label Encoded features
    label_cols = ["Order Region", "Category Name", "Order Country"]
    for col in label_cols:
        match = next((c for c in df.columns if c.lower() == col.lower()), None)
        classes = mappings[col]
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
        
    active_df["risk_bucket"] = pd.cut(
        active_df["p_late"],
        bins=[-0.001, 0.4, 0.7, 1.001],
        labels=["Low", "Medium", "High"]
    ).astype(str)
    
    active_df["expected_penalty"] = (active_df["p_late"] * 250.0).round(2)
    active_df["upgrade_cost"] = 80.0
    
    return active_df
