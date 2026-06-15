"""
retrainer.py
EDIS — 模型重訓模組

功能：
  1. 從原始 CSV 重新跑特徵工程
  2. 排除指定特徵群組後訓練新 XGBoost
  3. 與現有模型對比評估指標
  4. 提供 adopt / discard 決策介面

重訓不會立即覆蓋現有模型，
新模型先存放在 data/processed/retrain_temp/<session_id>/，
Manager 確認指標後才呼叫 adopt() 正式替換。
"""

import json
import shutil
import uuid
from pathlib import Path

import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).parent))


# ── 顯示名稱 → 實際欄位群組 對應表 ─────────────────────────────────────────────
# LIME 診斷回傳的是 feature_mapping 欄位名，這裡對應到「哪些 feature_columns 要一起刪除」
# key = feature_mapping 中可能出現的原始/群組名稱前綴
# value = 要從 X 中 drop 的欄位名稱前綴 list
FEATURE_GROUP_MAP: dict[str, list[str]] = {
    "運送模式":              ["Shipping Mode_"],
    "Shipping Mode":         ["Shipping Mode_"],
    "承諾運送天數":           ["Days for shipment (scheduled)"],
    "Days for shipment":     ["Days for shipment (scheduled)"],
    "訂單交易型態":           ["Type_"],
    "Type":                  ["Type_"],
    "目的地區域":             ["Order Region"],
    "Order Region":          ["Order Region"],
    "客戶分群":               ["Customer Segment_"],
    "Customer Segment":      ["Customer Segment_"],
    "商品單價":               ["Product Price"],
    "Product Price":         ["Product Price"],
    "訂單數量":               ["Order Item Quantity"],
    "Order Item Quantity":   ["Order Item Quantity"],
    "折扣率":                 ["Order Item Discount Rate"],
    "Order Item Discount":   ["Order Item Discount Rate"],
    "利潤比":                 ["Order Item Profit Ratio"],
    "Profit Ratio":          ["Order Item Profit Ratio"],
    "訂單利潤":               ["Order Profit Per Order"],
    "Order Profit":          ["Order Profit Per Order"],
    "部門":                   ["Department Name_"],
    "Department Name":       ["Department Name_"],
    "市場":                   ["Market_"],
    "Market":                ["Market_"],
    "商品類別":               ["Category Name"],
    "Category Name":         ["Category Name"],
    "訂單國家":               ["Order Country"],
    "Order Country":         ["Order Country"],
}


class ModelRetrainer:
    """
    排除問題特徵後重訓 XGBoost，並提供 adopt / discard 決策。

    使用範例：
        retrainer = ModelRetrainer(base_dir=Path("."))
        result = retrainer.run(excluded_features=["Shipping Mode_Standard Class"])
        # 確認改善後採用
        retrainer.adopt(result["session_id"])
    """

    def __init__(self, base_dir: Path):
        self.base_dir     = base_dir
        self.raw_path     = base_dir / "data" / "raw" / "DataCoSupplyChainDataset.csv"
        self.model_path   = base_dir / "models" / "xgboost_model.json"
        self.metrics_path = base_dir / "data" / "processed" / "model_metrics.json"
        self.pred_path    = base_dir / "data" / "processed" / "predictions.csv"
        self.mapping_path = base_dir / "models" / "feature_mapping.json"
        self.temp_dir     = base_dir / "data" / "processed" / "retrain_temp"
        # 乙：累積的上傳訓練資料（append 累積，供重訓一起使用）
        self.training_store_path = base_dir / "data" / "training_store" / "accumulated.csv"

    # ── 公開方法 ───────────────────────────────────────────────────────────────

    def run(self, excluded_features: list[str]) -> dict:
        """
        執行重訓流程：
          1. 讀原始 CSV → 特徵工程（重用 DataPipeline）
          2. 展開 excluded_features 到實際欄位名稱
          3. 訓練新模型
          4. 評估新舊模型
          5. 儲存至 temp 目錄，回傳比對結果

        Parameters
        ----------
        excluded_features : list[str]
            要排除的特徵名稱（支援顯示名稱或實際欄位名稱前綴）

        Returns
        -------
        dict  包含 session_id、old_metrics、new_metrics、dropped_columns
        """
        try:
            import xgboost as _xgb  # noqa: F401
        except ImportError:
            raise RuntimeError("XGBoost 未安裝，無法重訓。請先執行：conda install -n Fastapp -c conda-forge xgboost")
        from data_pipeline import DataPipeline
        from model_pipeline import ModelPipeline

        if not self.raw_path.exists():
            raise FileNotFoundError(f"找不到原始資料：{self.raw_path}")

        # 乙：若有累積的上傳訓練資料，合併『原始 + 累積』一起重訓（模型才會隨新資料進步）
        from training_store import build_combined_training_file
        combined_path = self.base_dir / "data" / "processed" / "_combined_training_input.csv"
        merge_info = build_combined_training_file(self.raw_path, self.training_store_path, combined_path)
        train_source = combined_path if merge_info["accumulated"] > 0 else self.raw_path
        print(f"[Retrain] 訓練資料來源：原始 {merge_info['raw']} + 累積 {merge_info['accumulated']} = {merge_info['total']} 筆")

        # Step 1：資料前處理（重用現有 DataPipeline，但不存檔）
        pipeline = DataPipeline()
        splits = pipeline.run(
            filepath=str(train_source),
            output_dir=str(self.base_dir / "data" / "processed"),
        )
        X_train: pd.DataFrame = splits["X_train"]
        X_test:  pd.DataFrame = splits["X_test"]
        y_train: pd.Series    = splits["y_train"]
        y_test:  pd.Series    = splits["y_test"]

        # Step 2：把 excluded_features 展開到實際欄位名稱
        cols_to_drop = self._resolve_columns(excluded_features, X_train.columns.tolist())
        X_train_new = X_train.drop(columns=cols_to_drop, errors="ignore")
        X_test_new  = X_test.drop(columns=cols_to_drop,  errors="ignore")

        # Step 3：訓練新模型
        mp = ModelPipeline()
        mp.train(X_train_new, y_train, X_test_new, y_test)

        # Step 4：評估新模型
        new_metrics = mp.evaluate(X_test_new, y_test)
        new_metrics["feature_count"] = X_train_new.shape[1]
        new_metrics["dropped_columns"] = cols_to_drop

        # Step 5：讀取舊模型指標
        old_metrics = self._load_old_metrics()

        # Step 6：存到 temp 目錄
        session_id = uuid.uuid4().hex[:12]
        session_dir = self.temp_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        mp.save(str(session_dir / "xgboost_model.json"))

        # 同時存 feature list（adopt 時需要更新 feature_mapping.json）
        new_feature_cols = X_train_new.columns.tolist()
        with open(session_dir / "new_metrics.json", "w", encoding="utf-8") as f:
            json.dump(new_metrics, f, ensure_ascii=False, indent=2)
        with open(session_dir / "new_feature_columns.json", "w", encoding="utf-8") as f:
            json.dump({"feature_columns": new_feature_cols}, f, ensure_ascii=False, indent=2)

        return {
            "session_id":      session_id,
            "old_metrics":     old_metrics,
            "new_metrics":     new_metrics,
            "dropped_columns": cols_to_drop,
            "excluded_input":  excluded_features,
        }

    def adopt(self, session_id: str) -> None:
        """
        採用新模型：
          - 將 temp 模型複製到 models/xgboost_model.json（覆蓋）
          - 更新 data/processed/model_metrics.json
          - 更新 models/feature_mapping.json 的 feature_columns
          - 清除 temp 目錄
        """
        session_dir = self.temp_dir / session_id
        if not session_dir.exists():
            raise FileNotFoundError(f"找不到 session：{session_id}")

        # 覆蓋模型
        shutil.copy2(session_dir / "xgboost_model.json", self.model_path)

        # 更新 metrics
        with open(session_dir / "new_metrics.json", "r", encoding="utf-8") as f:
            new_metrics = json.load(f)
        with open(self.metrics_path, "w", encoding="utf-8") as f:
            json.dump(new_metrics, f, ensure_ascii=False, indent=2)

        # 更新 feature_mapping.json
        with open(session_dir / "new_feature_columns.json", "r", encoding="utf-8") as f:
            fc_data = json.load(f)
        if self.mapping_path.exists():
            with open(self.mapping_path, "r", encoding="utf-8") as f:
                mapping = json.load(f)
            mapping["feature_columns"] = fc_data["feature_columns"]
            with open(self.mapping_path, "w", encoding="utf-8") as f:
                json.dump(mapping, f, ensure_ascii=False, indent=2)

        # 清除 temp
        shutil.rmtree(session_dir, ignore_errors=True)

    def discard(self, session_id: str) -> None:
        """捨棄新模型，只刪除 temp 目錄，現有模型不動。"""
        session_dir = self.temp_dir / session_id
        shutil.rmtree(session_dir, ignore_errors=True)

    # ── 私有方法 ───────────────────────────────────────────────────────────────

    def _resolve_columns(self, excluded: list[str], all_cols: list[str]) -> list[str]:
        """
        把使用者輸入的特徵名稱（顯示名/部分名稱）展開為要刪除的實際欄位列表。

        查找順序：
          1. FEATURE_GROUP_MAP 查顯示名稱 → 前綴 list → 找 all_cols 中符合的欄位
          2. 直接比對欄位名稱（精確或 startswith）
        """
        to_drop = set()
        for name in excluded:
            resolved = False

            # 先試 FEATURE_GROUP_MAP
            for key, prefixes in FEATURE_GROUP_MAP.items():
                if key.lower() in name.lower() or name.lower() in key.lower():
                    for prefix in prefixes:
                        for col in all_cols:
                            if col.startswith(prefix) or col == prefix.rstrip():
                                to_drop.add(col)
                    resolved = True

            # 再試直接比對
            if not resolved:
                for col in all_cols:
                    if col == name or col.startswith(name):
                        to_drop.add(col)

        return sorted(to_drop)

    def _load_old_metrics(self) -> dict:
        """讀取現有模型指標，若不存在回傳空字典。"""
        if self.metrics_path.exists():
            with open(self.metrics_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}
