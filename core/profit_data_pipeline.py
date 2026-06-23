"""
profit_data_pipeline.py
SLIDE — 收益（利潤）預測：資料處理管線（完全獨立，不碰現有延遲分類管線）

負責範圍：Step 1→5（讀檔 → 清洗 → 洩漏移除 → 特徵工程 → 缺失 SSOT → 時間切分）

與模型組員整合（見 reports/profit_data_pipeline_decisions_2026-06-23.md §11）：
  - 輸出對齊他的 `profit_model_pipeline.py` 契約：
      data/processed/profit_{train,val,test}_ready.csv（全數值，含目標）
  - 類別欄輸出「整數代碼」（train 學 mapping、SSOT、未見/缺失 → 0）；
    另出 data/processed/profit_feature_schema.json 標明哪些欄是「類別欄」，
    讓他的 pipeline 用 LightGBM 原生類別（astype category + categorical_feature）。
  - is_outlier 與 join key 不進 ready CSV（避免被當特徵洩漏），改放 metadata：
      data/processed/profit_{split}_metadata.csv（hash Order Id + order date + is_outlier）

設計原則：
  - 完全獨立、全向量化（類別/欄位層級走小迴圈，無逐列遞迴）。
  - SSOT：缺失統計、類別 mapping、離群界線「只由 train 計算」存 artifact。
  - 誠實：負/零利潤與離群值保留（離群只標註於 metadata，不竄改）。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# ── 常數 ──────────────────────────────────────────────────────────────────────

RANDOM_STATE = 42
TRAIN_SIZE = 0.70
VAL_SIZE = 0.15
TEST_SIZE = 0.15

TARGET_COLUMN = "Order Profit Per Order"
DATE_COLUMN = "order date (DateOrders)"
ORDER_ID_COLUMN = "Order Id"
HASH_SALT = "SLIDE_PROFIT_2026"          # 與延遲系統 join 時若需一致，另行對齊（見 MD §11）

_SORT_KEY = "__order_dt__"               # 內部排序鍵，不輸出
UNKNOWN_CODE = 0                         # 類別未見/缺失的保留碼

# 平衡警告門檻（§5）
NEG_PCT_WARN_ABS = 0.07
MEAN_REL_WARN = 0.50

# ── 欄位分類（精準對齊 CSV 53 欄）───────────────────────────────────────────────

# Benefit per order == 利潤本身（corr=1.0，純恆等式）→ 永遠丟棄。
# Order Item Profit Ratio（毛利率）：依團隊決策視為「下單時已知的定價 margin」→ 合法特徵，
#   不列洩漏（見 reports/profit_data_pipeline_decisions_2026-06-23.md §11.6）。
LEAKAGE_COLUMNS = ["Benefit per order"]
PII_COLUMNS = [
    "Customer Email", "Customer Fname", "Customer Lname",
    "Customer Password", "Customer Street", "Customer Zipcode",
]
ID_COLUMNS = [
    "Category Id", "Customer Id", "Department Id", "Order Customer Id",
    "Order Id", "Order Item Cardprod Id", "Order Item Id",
    "Product Card Id", "Product Category Id",
]
NOISE_COLUMNS = ["Order Zipcode", "Product Description", "Product Image"]
REDUNDANT_DATE_COLUMNS = ["shipping date (DateOrders)"]

NUMERIC_FEATURES = [
    "Days for shipping (real)", "Days for shipment (scheduled)",
    "Sales per customer", "Late_delivery_risk", "Latitude", "Longitude",
    "Order Item Discount", "Order Item Discount Rate",
    "Order Item Profit Ratio",   # 視為下單時已知的定價 margin（見 MD §11.6）
    "Order Item Product Price", "Order Item Quantity",
    "Sales", "Order Item Total", "Product Price", "Product Status",
]
CATEGORICAL_FEATURES = [
    "Type", "Delivery Status", "Category Name", "Customer City",
    "Customer Country", "Customer Segment", "Customer State",
    "Department Name", "Market", "Order City", "Order Country",
    "Order Region", "Order State", "Order Status", "Product Name", "Shipping Mode",
]
DATE_FEATURES = [
    "order_year", "order_month", "order_day",
    "order_dayofweek", "order_hour", "order_is_weekend",
]

# 同義欄互填群組（§4.4）：只在「同義且非洩漏」輸入欄間互填，永不回填目標
SYNONYM_FILL_GROUPS = [
    ["Sales", "Order Item Total", "Sales per customer"],
    ["Product Price", "Order Item Product Price"],
]


class ProfitDataPipelineError(RuntimeError):
    """收益資料管線錯誤（缺檔、欄位缺失、邏輯自檢失敗等）。"""


class ProfitDataPipeline:
    """從原始 DataCo CSV 到收益預測「訓練就緒」資料集的完整管線。"""

    def __init__(
        self,
        random_state: int = RANDOM_STATE,
        train_size: float = TRAIN_SIZE,
        val_size: float = VAL_SIZE,
        test_size: float = TEST_SIZE,
    ):
        if abs(train_size + val_size + test_size - 1.0) > 1e-9:
            raise ProfitDataPipelineError("train/val/test 比例加總必須為 1.0")
        self.random_state = random_state
        self.train_size = train_size
        self.val_size = val_size
        self.test_size = test_size
        self.artifacts: dict | None = None

    # ── Step 1：載入 ─────────────────────────────────────────────────────────
    def load(self, filepath: str | Path) -> pd.DataFrame:
        path = Path(filepath)
        if not path.exists():
            raise ProfitDataPipelineError(
                f"找不到資料集：{path}\n"
                "（此檔被 .gitignore 排除、不在 GitHub；請各自將 "
                "DataCoSupplyChainDataset.csv 放到 data/raw/ 後再執行。）"
            )
        df = pd.read_csv(path, encoding="latin-1")
        required = NUMERIC_FEATURES + CATEGORICAL_FEATURES + [TARGET_COLUMN, DATE_COLUMN]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ProfitDataPipelineError(f"資料集缺少必要欄位：{missing}")
        return df

    # ── Step 4a：日期特徵（向量化）───────────────────────────────────────────
    @staticmethod
    def _extract_date_features(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        dt = pd.to_datetime(df[DATE_COLUMN], errors="coerce")
        df[_SORT_KEY] = dt
        df["order_year"] = dt.dt.year
        df["order_month"] = dt.dt.month
        df["order_day"] = dt.dt.day
        df["order_dayofweek"] = dt.dt.dayofweek
        df["order_hour"] = dt.dt.hour
        df["order_is_weekend"] = (dt.dt.dayofweek >= 5).astype("Int64")
        return df

    # ── Step 4b：同義欄互填（向量化，§4.4）──────────────────────────────────
    @staticmethod
    def _synonym_fill(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        for group in SYNONYM_FILL_GROUPS:
            cols = [c for c in group if c in df.columns]
            if len(cols) < 2:
                continue
            base = df[cols].bfill(axis=1).iloc[:, 0]   # 群組內第一個非空值
            for c in cols:
                df[c] = df[c].fillna(base)
        return df

    # ── fit：只由 train 計算 SSOT 統計 ──────────────────────────────────────
    def fit(self, train_df: pd.DataFrame) -> dict:
        df = self._extract_date_features(train_df)
        df = self._synonym_fill(df)

        numeric_medians = {
            c: float(pd.to_numeric(df[c], errors="coerce").median())
            for c in NUMERIC_FEATURES
        }
        # 類別整數 mapping：類別 → 1..N（排序穩定）；未見/缺失保留 UNKNOWN_CODE(0)
        categorical_mappings: dict[str, dict] = {}
        categorical_codes: dict[str, list] = {}
        for c in CATEGORICAL_FEATURES:
            cats = sorted(df[c].dropna().astype(str).unique().tolist())
            mapping = {cat: i + 1 for i, cat in enumerate(cats)}
            categorical_mappings[c] = mapping
            categorical_codes[c] = [UNKNOWN_CODE] + list(range(1, len(cats) + 1))

        y = pd.to_numeric(df[TARGET_COLUMN], errors="coerce")
        outlier_bounds = {"lower": float(y.quantile(0.01)), "upper": float(y.quantile(0.99))}

        feature_columns = NUMERIC_FEATURES + CATEGORICAL_FEATURES + DATE_FEATURES

        self.artifacts = {
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "random_state": self.random_state,
            "split_ratio": {"train": self.train_size, "val": self.val_size, "test": self.test_size},
            "target_column": TARGET_COLUMN,
            "feature_columns": feature_columns,
            "numeric_columns": NUMERIC_FEATURES,
            "categorical_columns": CATEGORICAL_FEATURES,
            "date_features": DATE_FEATURES,
            "numeric_medians": numeric_medians,
            "categorical_mappings": categorical_mappings,
            "categorical_codes": categorical_codes,
            "unknown_code": UNKNOWN_CODE,
            "synonym_fill_groups": SYNONYM_FILL_GROUPS,
            "outlier_bounds": outlier_bounds,
            "metadata_columns": ["order_id_hash", "order_date", "is_outlier"],
            "dropped_columns": {
                "leakage": LEAKAGE_COLUMNS, "pii": PII_COLUMNS, "id": ID_COLUMNS,
                "noise": NOISE_COLUMNS,
                "redundant_date": REDUNDANT_DATE_COLUMNS + [DATE_COLUMN],
            },
        }
        return self.artifacts

    # ── transform：套用 train 學到的 SSOT，輸出全數值特徵 + 目標 ──────────────
    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        if self.artifacts is None:
            raise ProfitDataPipelineError("尚未 fit；請先用 train 呼叫 fit()。")
        a = self.artifacts
        df = self._extract_date_features(df)
        df = self._synonym_fill(df)

        out = pd.DataFrame(index=df.index)
        # 數值：補 train 中位數（SSOT）
        for c in a["numeric_columns"]:
            out[c] = pd.to_numeric(df[c], errors="coerce").fillna(a["numeric_medians"][c])
        # 類別：整數碼（未見/缺失 → UNKNOWN_CODE）
        for c in a["categorical_columns"]:
            codes = df[c].astype(str).map(a["categorical_mappings"][c])
            out[c] = codes.fillna(UNKNOWN_CODE).astype(int)
        # 日期：補 0、轉 int
        for c in a["date_features"]:
            out[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)

        out = out[a["feature_columns"]]
        out[TARGET_COLUMN] = pd.to_numeric(df[TARGET_COLUMN], errors="coerce")
        return out

    # ── metadata（join key + is_outlier；不進 ready CSV）─────────────────────
    def build_metadata(self, raw_split: pd.DataFrame) -> pd.DataFrame:
        a = self.artifacts
        y = pd.to_numeric(raw_split[TARGET_COLUMN], errors="coerce")
        lo, hi = a["outlier_bounds"]["lower"], a["outlier_bounds"]["upper"]
        oid = raw_split[ORDER_ID_COLUMN].astype(str)
        order_id_hash = oid.map(
            lambda x: hashlib.sha256((HASH_SALT + x).encode("utf-8")).hexdigest()[:16]
        )
        return pd.DataFrame({
            "order_id_hash": order_id_hash.to_numpy(),
            "order_date": raw_split[DATE_COLUMN].to_numpy(),
            "is_outlier": ((y < lo) | (y > hi)).astype(int).to_numpy(),
        })

    # ── Step 5：時間切分（C 混合）───────────────────────────────────────────
    def time_split(self, df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        df = self._extract_date_features(df)
        df = df.sort_values(_SORT_KEY, kind="stable").reset_index(drop=True)
        n = len(df)
        n_train = int(round(n * self.train_size))
        n_val = int(round(n * self.val_size))
        return (df.iloc[:n_train], df.iloc[n_train:n_train + n_val], df.iloc[n_train + n_val:])

    # ── 分布平衡報告（§5）───────────────────────────────────────────────────
    @staticmethod
    def _profit_stats(df: pd.DataFrame) -> dict:
        y = pd.to_numeric(df[TARGET_COLUMN], errors="coerce")
        dt = pd.to_datetime(df[_SORT_KEY], errors="coerce")
        return {
            "n": int(len(df)),
            "profit_mean": round(float(y.mean()), 4),
            "profit_median": round(float(y.median()), 4),
            "profit_std": round(float(y.std()), 4),
            "neg_pct": round(float((y < 0).mean()), 4),
            "zero_pct": round(float((y == 0).mean()), 4),
            "skew": round(float(y.skew()), 4),
            "date_min": str(dt.min()), "date_max": str(dt.max()),
        }

    def _build_split_report(self, full, train, val, test) -> dict:
        full = self._extract_date_features(full)
        overall = self._profit_stats(full)
        parts = {"train": self._profit_stats(train), "val": self._profit_stats(val),
                 "test": self._profit_stats(test)}
        warnings: list[str] = []
        for name, st in parts.items():
            if abs(st["neg_pct"] - overall["neg_pct"]) > NEG_PCT_WARN_ABS:
                warnings.append(f"[{name}] 虧損比例 {st['neg_pct']:.2%} 與全體 "
                                f"{overall['neg_pct']:.2%} 差異 > {NEG_PCT_WARN_ABS:.0%}")
            denom = abs(overall["profit_mean"]) or 1.0
            if abs(st["profit_mean"] - overall["profit_mean"]) / denom > MEAN_REL_WARN:
                warnings.append(f"[{name}] 利潤均值 {st['profit_mean']} 與全體 "
                                f"{overall['profit_mean']} 相對差異 > {MEAN_REL_WARN:.0%}")
        return {"overall": overall, "splits": parts, "balance_warnings": warnings}

    # ── 邏輯正確性自檢（§7）─────────────────────────────────────────────────
    def _validate(self, full, train, val, test, train_t, val_t, test_t) -> dict:
        errors: list[str] = []
        a = self.artifacts
        feat = a["feature_columns"]

        if len(train) + len(val) + len(test) != len(full):
            errors.append("切分筆數加總 != 原始筆數")

        tr_max = pd.to_datetime(train[_SORT_KEY]).max()
        va_min = pd.to_datetime(val[_SORT_KEY]).min()
        va_max = pd.to_datetime(val[_SORT_KEY]).max()
        te_min = pd.to_datetime(test[_SORT_KEY]).min()
        if not (tr_max <= va_min and va_max <= te_min):
            errors.append(f"時間順序違反：train_max={tr_max}, val=({va_min}~{va_max}), test_min={te_min}")

        leaked = [c for c in (LEAKAGE_COLUMNS + PII_COLUMNS + ID_COLUMNS) if c in feat]
        if leaked:
            errors.append(f"洩漏/個資/ID 欄出現在特徵中：{leaked}")

        for name, t in (("train", train_t), ("val", val_t), ("test", test_t)):
            if int(t[feat].isna().sum().sum()):
                errors.append(f"[{name}] 特徵仍有缺失值")
            non_numeric = t[feat].select_dtypes(exclude=[np.number]).columns.tolist()
            if non_numeric:
                errors.append(f"[{name}] ready CSV 出現非數值特徵欄：{non_numeric}")

        cols_train = list(train_t[feat].columns)
        for name, t in (("val", val_t), ("test", test_t)):
            if list(t[feat].columns) != cols_train:
                errors.append(f"[{name}] 特徵欄位順序/集合與 train 不一致")

        if errors:
            raise ProfitDataPipelineError("邏輯自檢失敗：\n  - " + "\n  - ".join(errors))
        return {"checks_passed": [
            "split_counts_sum_equals_total", "temporal_order_no_leakage",
            "no_leakage_in_features", "no_missing_in_features",
            "all_features_numeric", "feature_columns_consistent",
        ]}

    # ── 主流程 ──────────────────────────────────────────────────────────────
    def run(
        self,
        filepath: str | Path = "data/raw/DataCoSupplyChainDataset.csv",
        output_dir: str | Path = "data/processed",
        artifacts_dir: str | Path = "models/profit",
    ) -> dict:
        output_dir = Path(output_dir)
        artifacts_dir = Path(artifacts_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        print(f"[Step 1] 載入 {filepath} ...")
        full = self.load(filepath)
        print(f"  原始：{len(full):,} 筆 × {full.shape[1]} 欄")

        print("[Step 5] 時間切分（C 混合）...")
        train, val, test = self.time_split(full)
        print(f"  train={len(train):,}  val={len(val):,}  test={len(test):,}")

        print("[Step 4] fit SSOT（只由 train）...")
        self.fit(train)

        print("[Step 4] transform（全數值特徵）...")
        splits = {"train": train, "val": val, "test": test}
        ready = {k: self.transform(v) for k, v in splits.items()}
        meta = {k: self.build_metadata(v) for k, v in splits.items()}

        print("[自檢] 邏輯正確性驗證 ...")
        checks = self._validate(full, train, val, test, ready["train"], ready["val"], ready["test"])

        print("[報告] 分布平衡 ...")
        report = self._build_split_report(full, train, val, test)
        report["validation"] = checks
        for w in report["balance_warnings"]:
            print(f"  ⚠️ {w}")
        if not report["balance_warnings"]:
            print("  ✓ 各段分布在門檻內")

        # 輸出 ready CSV（他的命名）+ metadata
        for k in ("train", "val", "test"):
            ready[k].to_csv(output_dir / f"profit_{k}_ready.csv", index=False)
            meta[k].to_csv(output_dir / f"profit_{k}_metadata.csv", index=False)

        # 給模型端讀的 schema（哪些欄是類別欄 → 原生類別處理）
        schema = {
            "target_column": TARGET_COLUMN,
            "feature_columns": self.artifacts["feature_columns"],
            "categorical_columns": self.artifacts["categorical_columns"],
            "categorical_codes": self.artifacts["categorical_codes"],
            "numeric_columns": self.artifacts["numeric_columns"],
            "date_features": self.artifacts["date_features"],
            "unknown_code": UNKNOWN_CODE,
        }
        with open(output_dir / "profit_feature_schema.json", "w", encoding="utf-8") as f:
            json.dump(schema, f, ensure_ascii=False, indent=2)
        with open(output_dir / "profit_split_report.json", "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        with open(artifacts_dir / "serving_artifacts.json", "w", encoding="utf-8") as f:
            json.dump(self.artifacts, f, ensure_ascii=False, indent=2)

        print(f"[完成] ready/metadata/schema → {output_dir}；artifacts → {artifacts_dir}")
        return report


def main():
    ProfitDataPipeline().run()


if __name__ == "__main__":
    main()
