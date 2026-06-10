import pandas as pd
import json
from sklearn.preprocessing import LabelEncoder
from pathlib import Path

def main():
    print("Building feature mappings...")
    raw_path = Path("data/raw/DataCoSupplyChainDataset.csv")
    train_ready_path = Path("data/processed/train_ready.csv")
    
    if not raw_path.exists():
        print(f"Error: Raw dataset not found at {raw_path}")
        return
        
    if not train_ready_path.exists():
        print(f"Error: train_ready.csv not found at {train_ready_path}")
        return
        
    try:
        df_raw = pd.read_csv(raw_path, encoding="latin-1")
    except UnicodeDecodeError:
        df_raw = pd.read_csv(raw_path, encoding="utf-8")
        
    mappings = {}
    for col in ["Order Region", "Category Name", "Order Country"]:
        le = LabelEncoder()
        le.fit(df_raw[col].astype(str))
        mappings[col] = list(le.classes_)
        print(f"  {col}: {len(le.classes_)} classes mapped")
        
    train_ready = pd.read_csv(train_ready_path, nrows=5)
    feature_cols = [c for c in train_ready.columns if c != "Late_delivery_risk"]
    mappings["feature_columns"] = feature_cols
    print(f"  Feature columns: {len(feature_cols)} features mapped")
    
    output_path = Path("models/feature_mapping.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(mappings, f, ensure_ascii=False, indent=2)
        
    print(f"✓ Feature mappings built successfully at {output_path}")

if __name__ == "__main__":
    main()
