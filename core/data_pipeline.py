"""
data_pipeline.py
EDIS — DataCo 物流延遲預測與最佳化調度系統

負責人：Lisa
功能：資料前處理管線（第一層 + 特徵工程）
  1. 載入 DataCo CSV 並隨機抽樣
  2. 強制呼叫 security_utils 進行去識別化
  3. 移除資料洩漏欄位
  4. 特徵工程（One-Hot、Label Encoding、日期提取）
  5. 輸出 train_ready.csv 供 model_pipeline.py 使用
  6. 輸出 EDA 摘要
"""

import os
import sys
import pandas as pd
import numpy as np
from pathlib import Path
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder

# 同目錄下的安全模組
sys.path.insert(0, str(Path(__file__).parent))
from security_utils import DeIdentifier, get_leakage_columns


# ── 常數 ──────────────────────────────────────────────────────────────────────

DEFAULT_SAMPLE_SIZE = None     # 預設不進行抽樣，使用完整資料集
RANDOM_STATE = 42
TARGET_COLUMN = "Late_delivery_risk"
DEFAULT_TRAIN_SIZE = 0.70
DEFAULT_VAL_SIZE = 0.15
DEFAULT_TEST_SIZE = 0.15
DEFAULT_MAX_TEST_ROWS = None

# 特徵工程中使用的原始欄位
NUMERICAL_FEATURES = [
    "Days for shipment (scheduled)",
    "Product Price",
    "Order Item Quantity",
    "Order Item Discount Rate",
    "Order Item Profit Ratio",
    "Order Profit Per Order",
]

ONE_HOT_FEATURES = [
    "Shipping Mode",
    "Customer Segment",
    "Type",
    "Department Name",
    "Market",
]

LABEL_ENCODE_FEATURES = [
    "Order Region",
    "Category Name",
    "Order Country",
]

DATE_COLUMN = "order date (DateOrders)"


# ── 資料管線主類別 ────────────────────────────────────────────────────────────

class DataPipeline:
    """
    從原始 DataCo CSV 到訓練就緒資料集的完整管線。

    使用範例：
        pipeline = DataPipeline()
        pipeline.run(
            filepath="data/raw/DataCoSupplyChainDataset.csv",
            output_dir="data/processed"
        )
    """

    def __init__(
        self,
        sample_size: int = DEFAULT_SAMPLE_SIZE,
        random_state: int = RANDOM_STATE,
        hash_salt: str = "EDIS_2026",
        train_size: float = DEFAULT_TRAIN_SIZE,
        val_size: float = DEFAULT_VAL_SIZE,
        test_size: float = DEFAULT_TEST_SIZE,
        max_test_rows: int = DEFAULT_MAX_TEST_ROWS,
    ):
        self.sample_size = sample_size
        self.random_state = random_state
        total_split = train_size + val_size + test_size
        if abs(total_split - 1.0) > 1e-9:
            raise ValueError("train_size + val_size + test_size must equal 1.0")
        if min(train_size, val_size, test_size) <= 0:
            raise ValueError("train_size, val_size, and test_size must all be greater than 0")
        self.train_size = train_size
        self.val_size = val_size
        self.test_size = test_size
        self.max_test_rows = max_test_rows
        self.de_identifier = DeIdentifier(hash_salt=hash_salt)
        self.label_encoders: dict = {}

    # ── 公開方法 ───────────────────────────────────────────────────────────

    def run(self, filepath: str, output_dir: str = "data/processed") -> dict:
        """
        執行完整管線流程。

        Parameters
        ----------
        filepath : str
            DataCoSupplyChainDataset.csv 的路徑
        output_dir : str
            輸出目錄（train_ready.csv 儲存位置）

        Returns
        -------
        dict
            包含 X_train, X_test, y_train, y_test 的字典
        """
        os.makedirs(output_dir, exist_ok=True)

        print("=" * 60)
        print("EDIS DataPipeline — 開始執行")
        print("=" * 60)

        # Step 1：載入資料
        df = self.load(filepath)

        # Step 2：去識別化（必須最先執行）
        df = self.de_identify(df)

        # Step 3：EDA 摘要（在特徵工程前，保留原始分布）
        self.generate_eda_report(df)

        # Step 4：移除洩漏欄位，分離標籤
        df, y = self.extract_label_and_drop_leakage(df)

        # Step 5：保留展示與 API 需要的去識別化 metadata
        metadata = self.extract_metadata(df)

        # Step 6：特徵工程
        X = self.engineer_features(df)

        # Step 7：train/test split
        X_train_full, X_test, y_train_full, y_test, meta_train_full, meta_test = train_test_split(
            X, y, metadata,
            test_size=self.test_size,
            random_state=self.random_state,
            stratify=y,
        )
        X_train, X_val, y_train, y_val, meta_train, meta_val = train_test_split(
            X_train_full,
            y_train_full,
            meta_train_full,
            test_size=self.val_size / (self.train_size + self.val_size),
            random_state=self.random_state,
            stratify=y_train_full,
        )

        # Step 8：儲存
        self._save_processed(
            X_train,
            X_val,
            X_test,
            y_train,
            y_val,
            y_test,
            meta_train,
            meta_val,
            meta_test,
            output_dir,
            max_test_rows=self.max_test_rows,
        )

        print(f"\n✓ 管線完成。訓練集：{len(X_train)} 筆，驗證集：{len(X_val)} 筆，測試集：{len(X_test)} 筆")
        print(f"  輸出目錄：{os.path.abspath(output_dir)}")
        print("=" * 60)

        return {
            "X_train": X_train,
            "X_val": X_val,
            "X_test": X_test,
            "y_train": y_train,
            "y_val": y_val,
            "y_test": y_test,
            "meta_train": meta_train,
            "meta_val": meta_val,
            "meta_test": meta_test,
        }

    def load(self, filepath: str) -> pd.DataFrame:
        """
        載入 CSV 並隨機抽樣。
        嘗試 latin-1 編碼（DataCo 資料集常見格式）。
        """
        print(f"\n[Step 1] 載入資料：{filepath}")
        try:
            df = pd.read_csv(filepath, encoding="latin-1")
        except UnicodeDecodeError:
            df = pd.read_csv(filepath, encoding="utf-8")

        total = len(df)
        if self.sample_size and total > self.sample_size:
            df = df.sample(n=self.sample_size, random_state=self.random_state).reset_index(drop=True)
            print(f"  原始筆數：{total:,}，抽樣後：{len(df):,}")
        else:
            print(f"  載入 {total:,} 筆（未抽樣）")

        print(f"  欄位數：{df.shape[1]}")
        return df

    def de_identify(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        強制套用去識別化（第一層安全防護）。
        任何情況下，資料都必須先通過此步驟。
        """
        print("\n[Step 2] 去識別化（security_utils）")
        df = self.de_identifier.apply_all(df)
        print(f"  去識別化完成。剩餘欄位數：{df.shape[1]}")
        return df

    def extract_label_and_drop_leakage(self, df: pd.DataFrame) -> tuple:
        """
        1. 分離目標標籤 Late_delivery_risk
        2. 移除所有資料洩漏欄位
        """
        print("\n[Step 3] 移除洩漏欄位 & 分離標籤")

        # 確認標籤存在
        if TARGET_COLUMN not in df.columns:
            raise ValueError(f"找不到目標欄位 '{TARGET_COLUMN}'，請確認 CSV 欄位名稱。")

        y = df[TARGET_COLUMN].copy()
        print(f"  標籤分布：\n{y.value_counts().to_string()}")
        late_rate = y.mean() * 100
        print(f"  延遲率：{late_rate:.1f}%")

        # 移除標籤與洩漏欄位
        leakage = get_leakage_columns()
        cols_to_remove = [c for c in leakage if c in df.columns]
        df = df.drop(columns=cols_to_remove, errors="ignore")
        print(f"  已移除洩漏欄位：{cols_to_remove}")

        return df, y

    def engineer_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        特徵工程：
        - 數值特徵直接保留
        - One-Hot Encoding：Shipping Mode、Customer Segment
        - Label Encoding：Order Region
        - 日期提取：星期幾、月份
        """
        print("\n[Step 4] 特徵工程")
        feature_frames = []

        # 數值特徵
        num_cols = [c for c in NUMERICAL_FEATURES if c in df.columns]
        if num_cols:
            feature_frames.append(df[num_cols].reset_index(drop=True))
            print(f"  數值特徵：{num_cols}")

        # One-Hot Encoding
        for col in ONE_HOT_FEATURES:
            if col in df.columns:
                dummies = pd.get_dummies(df[col], prefix=col, drop_first=False)
                feature_frames.append(dummies.reset_index(drop=True))
                print(f"  One-Hot '{col}'：{list(dummies.columns)}")

        # Label Encoding
        for col in LABEL_ENCODE_FEATURES:
            if col in df.columns:
                le = LabelEncoder()
                encoded = le.fit_transform(df[col].astype(str))
                self.label_encoders[col] = le
                feature_frames.append(
                    pd.DataFrame({f"{col}_encoded": encoded})
                )
                print(f"  Label Encoding '{col}'：{len(le.classes_)} 類別")

        # 日期特徵
        if DATE_COLUMN in df.columns:
            date_series = pd.to_datetime(df[DATE_COLUMN], errors="coerce")
            feature_frames.append(pd.DataFrame({
                "order_dayofweek": date_series.dt.dayofweek.fillna(-1).astype(int),
                "order_month": date_series.dt.month.fillna(-1).astype(int),
                "order_hour": date_series.dt.hour.fillna(-1).astype(int),
                "order_is_weekend": (date_series.dt.dayofweek >= 5).fillna(0).astype(int),
            }))
            print(f"  日期提取：order_dayofweek、order_month、order_hour、order_is_weekend")

        X = pd.concat(feature_frames, axis=1)

        # 填補缺失值（數值用中位數）
        X = X.fillna(X.median(numeric_only=True))

        print(f"  最終特徵矩陣：{X.shape[0]} 筆 × {X.shape[1]} 特徵")
        print(f"  特徵欄位：{list(X.columns)}")
        return X

    def extract_metadata(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        保留不進入模型、但 API/Dashboard 需要展示的去識別化欄位。

        這些欄位不放進 XGBoost 特徵矩陣，避免字串 ID 造成訓練錯誤；
        但會跟 test set 同步切分，供 model_pipeline.py 輸出 predictions.csv。
        """
        metadata_cols = [
            "Order Id_hash",
            "Shipping Mode",
            "Order Region",
            "order date (DateOrders)",
        ]
        existing_cols = [c for c in metadata_cols if c in df.columns]
        metadata = df[existing_cols].copy() if existing_cols else pd.DataFrame(index=df.index)
        metadata = metadata.rename(columns={
            "Order Id_hash": "order_id_hash",
            "Shipping Mode": "shipping_mode",
            "Order Region": "order_region",
            "order date (DateOrders)": "order_date",
        })
        print(f"\n[Metadata] 保留展示欄位：{list(metadata.columns)}")
        return metadata.reset_index(drop=True)

    def generate_eda_report(self, df: pd.DataFrame) -> None:
        """
        輸出簡易 EDA 摘要至 console（延遲比例、分布統計）。
        """
        print("\n[EDA 摘要]")
        print(f"  資料形狀：{df.shape}")

        if TARGET_COLUMN in df.columns:
            late_rate = df[TARGET_COLUMN].mean() * 100
            print(f"  延遲率（Late_delivery_risk=1）：{late_rate:.1f}%")

        if "Shipping Mode" in df.columns:
            print("\n  Shipping Mode 分布：")
            print(df["Shipping Mode"].value_counts().to_string(header=False))

        if "Order Region" in df.columns:
            print("\n  Top 5 Order Region：")
            print(df["Order Region"].value_counts().head(5).to_string(header=False))

        if "Product Price" in df.columns:
            print(f"\n  Product Price 統計：")
            print(df["Product Price"].describe().to_string())

    # ── 私有方法 ───────────────────────────────────────────────────────────

    def _save_processed(
        self,
        X_train, X_val, X_test, y_train, y_val, y_test,
        meta_train, meta_val, meta_test,
        output_dir: str,
        max_test_rows: int = None,
    ) -> None:
        """將訓練/測試特徵與展示 metadata 儲存為 CSV。"""
        train_df = X_train.copy()
        train_df[TARGET_COLUMN] = y_train.values

        val_df = X_val.copy()
        val_df[TARGET_COLUMN] = y_val.values

        test_df = X_test.copy()
        test_df[TARGET_COLUMN] = y_test.values

        # Optional demo mode: cap test rows only when max_test_rows is provided.
        if max_test_rows and len(test_df) > max_test_rows:
            test_df = test_df.head(max_test_rows)
            meta_test = meta_test.head(max_test_rows)

        train_path = os.path.join(output_dir, "train_ready.csv")
        val_path = os.path.join(output_dir, "val_ready.csv")
        test_path = os.path.join(output_dir, "test_ready.csv")
        train_meta_path = os.path.join(output_dir, "train_metadata.csv")
        val_meta_path = os.path.join(output_dir, "val_metadata.csv")
        test_meta_path = os.path.join(output_dir, "test_metadata.csv")

        train_df.to_csv(train_path, index=False)
        val_df.to_csv(val_path, index=False)
        test_df.to_csv(test_path, index=False)
        meta_train.reset_index(drop=True).to_csv(train_meta_path, index=False)
        meta_val.reset_index(drop=True).to_csv(val_meta_path, index=False)
        meta_test.reset_index(drop=True).to_csv(test_meta_path, index=False)

        print(f"\n[Step 5] 儲存完成")
        print(f"  → {train_path}")
        print(f"  → {val_path}")
        print(f"  → {test_path}")
        print(f"  → {train_meta_path}")
        print(f"  → {val_meta_path}")
        print(f"  → {test_meta_path}")


# ── 直接執行入口 ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="EDIS DataPipeline")
    parser.add_argument(
        "--input",
        default="data/raw/DataCoSupplyChainDataset.csv",
        help="DataCo CSV 路徑",
    )
    parser.add_argument(
        "--output",
        default="data/processed",
        help="輸出目錄",
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=DEFAULT_SAMPLE_SIZE,
        help="抽樣筆數（預設 30000）",
    )
    parser.add_argument("--train-size", type=float, default=DEFAULT_TRAIN_SIZE)
    parser.add_argument("--val-size", type=float, default=DEFAULT_VAL_SIZE)
    parser.add_argument("--test-size", type=float, default=DEFAULT_TEST_SIZE)
    parser.add_argument("--max-test-rows", type=int, default=DEFAULT_MAX_TEST_ROWS)
    args = parser.parse_args()

    pipeline = DataPipeline(
        sample_size=args.sample,
        train_size=args.train_size,
        val_size=args.val_size,
        test_size=args.test_size,
        max_test_rows=args.max_test_rows,
    )
    pipeline.run(filepath=args.input, output_dir=args.output)
