"""
model_pipeline.py
EDIS — DataCo 物流延遲預測與最佳化調度系統

負責人：子堯（協助撰寫：Lisa）
功能：XGBoost 延遲預測模型訓練、評估、預測輸出
  1. 讀取 train_ready.csv / test_ready.csv
  2. 訓練 XGBoost 二元分類器
  3. 評估（AUC-ROC、F1、Precision、Recall、混淆矩陣）
  4. 輸出 predictions.csv（含 order_id_hash、p_late、risk_bucket）
  5. 儲存模型 .json
"""

import os
import sys
import json
import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.metrics import (
    roc_auc_score,
    f1_score,
    precision_score,
    recall_score,
    confusion_matrix,
    classification_report,
)
try:
    import xgboost as xgb
except ImportError:
    raise ImportError(
        "XGBoost 未安裝。請執行：conda install -n Fastapp -c conda-forge xgboost"
    )


# ── 常數 ──────────────────────────────────────────────────────────────────────

TARGET_COLUMN = "Late_delivery_risk"
DEFAULT_MODEL_PATH = "models/xgboost_model.json"

XGBOOST_PARAMS = {
    "objective": "binary:logistic",
    "eval_metric": "logloss",
    "n_estimators": 300,
    "max_depth": 6,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 5,
    "reg_alpha": 0.1,
    "reg_lambda": 1.0,
    "random_state": 42,
    "n_jobs": -1,
}

# 延遲風險分桶閾值
RISK_THRESHOLDS = {
    "High": 0.7,
    "Medium": 0.4,
    "Low": 0.0,
}

# 預設升級成本（最佳化模組使用）
DEFAULT_UPGRADE_COST = 80.0
DEFAULT_DELAY_PENALTY = 250.0


# ── 模型管線主類別 ────────────────────────────────────────────────────────────

class ModelPipeline:
    """
    XGBoost 延遲預測模型的訓練與推論管線。

    使用範例：
        mp = ModelPipeline()
        mp.run(
            train_path="data/processed/train_ready.csv",
            test_path="data/processed/test_ready.csv",
            output_dir="data/processed",
            model_dir="models",
        )
    """

    def __init__(self, params: dict = None):
        self.params = params or XGBOOST_PARAMS.copy()
        self.model: xgb.XGBClassifier = None
        self.feature_names: list = []
        self.eval_metrics: dict = {}

    # ── 公開方法 ───────────────────────────────────────────────────────────

    def run(
        self,
        train_path: str,
        test_path: str,
        output_dir: str = "data/processed",
        model_dir: str = "models",
    ) -> dict:
        """
        完整訓練流程：載入 → 訓練 → 評估 → 預測輸出 → 儲存

        Returns
        -------
        dict
            eval_metrics 評估指標字典
        """
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(model_dir, exist_ok=True)

        print("=" * 60)
        print("EDIS ModelPipeline — 開始執行")
        print("=" * 60)

        # 載入訓練/測試資料
        X_train, y_train = self._load_data(train_path)
        X_test, y_test = self._load_data(test_path)
        self.feature_names = list(X_train.columns)

        # 訓練
        self.train(X_train, y_train, X_test, y_test)

        # 評估
        self.eval_metrics = self.evaluate(X_test, y_test)

        # 輸出 predictions.csv
        pred_path = os.path.join(output_dir, "predictions.csv")
        self._save_predictions(X_test, y_test, pred_path)

        # 儲存模型
        model_path = os.path.join(model_dir, "xgboost_model.json")
        self.save(model_path)

        # 儲存評估指標
        metrics_path = os.path.join(output_dir, "model_metrics.json")
        with open(metrics_path, "w", encoding="utf-8") as f:
            json.dump(self.eval_metrics, f, ensure_ascii=False, indent=2)
        print(f"\n  評估指標已儲存：{metrics_path}")

        print("\n✓ ModelPipeline 完成")
        print("=" * 60)
        return self.eval_metrics

    def train(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: pd.DataFrame = None,
        y_val: pd.Series = None,
    ) -> None:
        """
        訓練 XGBoost 二元分類器。
        若提供驗證集，使用 early stopping（patience=20）。
        """
        print(f"\n[Train] 訓練 XGBoost，樣本：{len(X_train):,}，特徵：{X_train.shape[1]}")

        # 計算 scale_pos_weight（處理類別不平衡）
        neg = (y_train == 0).sum()
        pos = (y_train == 1).sum()
        scale = neg / pos if pos > 0 else 1.0
        self.params["scale_pos_weight"] = round(scale, 2)
        print(f"  類別比例（neg/pos）：{scale:.2f}")

        self.model = xgb.XGBClassifier(**self.params)

        fit_kwargs = {"X": X_train, "y": y_train}
        if X_val is not None and y_val is not None:
            fit_kwargs["eval_set"] = [(X_val, y_val)]
            fit_kwargs["verbose"] = False

        self.model.fit(**fit_kwargs)
        print(f"  訓練完成。使用樹數：{self.model.get_booster().num_boosted_rounds()}")

    def evaluate(self, X_test: pd.DataFrame, y_test: pd.Series) -> dict:
        """
        評估模型效能，回傳指標字典。
        """
        print("\n[Evaluate] 模型評估")
        y_prob = self.model.predict_proba(X_test)[:, 1]
        y_pred = (y_prob >= 0.5).astype(int)

        metrics = {
            "roc_auc": round(roc_auc_score(y_test, y_prob), 4),
            "f1": round(f1_score(y_test, y_pred), 4),
            "precision": round(precision_score(y_test, y_pred, zero_division=0), 4),
            "recall": round(recall_score(y_test, y_pred, zero_division=0), 4),
            "late_rate": round(float(y_test.mean()), 4),
            "high_risk_orders": int((y_prob >= RISK_THRESHOLDS["High"]).sum()),
        }

        cm = confusion_matrix(y_test, y_pred)
        metrics["confusion_matrix"] = cm.tolist()

        print(f"  ROC-AUC  : {metrics['roc_auc']}")
        print(f"  F1       : {metrics['f1']}")
        print(f"  Precision: {metrics['precision']}")
        print(f"  Recall   : {metrics['recall']}")
        print(f"\n  混淆矩陣：")
        print(f"  {cm}")
        print(f"\n  分類報告：")
        print(classification_report(y_test, y_pred, target_names=["準時(0)", "延遲(1)"]))

        # Feature importance（top 10）
        if self.feature_names:
            fi = pd.Series(
                self.model.feature_importances_,
                index=self.feature_names,
            ).sort_values(ascending=False)
            print("  Top 10 重要特徵：")
            print(fi.head(10).to_string())
            metrics["feature_importance"] = fi.head(10).to_dict()

        return metrics

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """
        回傳每筆訂單的延遲機率（shape: n_samples）。
        """
        if self.model is None:
            raise RuntimeError("模型尚未訓練，請先呼叫 train() 或 load()")
        return self.model.predict_proba(X)[:, 1]

    def save(self, path: str = DEFAULT_MODEL_PATH) -> None:
        """儲存模型為 XGBoost .json 格式。"""
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.model.save_model(path)
        print(f"  模型已儲存：{path}")

    def load(self, path: str = DEFAULT_MODEL_PATH) -> None:
        """從 .json 載入已訓練的模型。"""
        self.model = xgb.XGBClassifier()
        self.model.load_model(path)
        print(f"  模型已載入：{path}")

    # ── 私有方法 ───────────────────────────────────────────────────────────

    def _load_data(self, path: str) -> tuple:
        """載入 CSV，分離特徵矩陣與標籤。"""
        print(f"\n  載入：{path}")
        df = pd.read_csv(path)
        if TARGET_COLUMN not in df.columns:
            raise ValueError(f"找不到標籤欄位 '{TARGET_COLUMN}' 於 {path}")
        y = df[TARGET_COLUMN]
        X = df.drop(columns=[TARGET_COLUMN])
        print(f"  形狀：{X.shape}，標籤延遲率：{y.mean()*100:.1f}%")
        return X, y

    def _save_predictions(
        self,
        X_test: pd.DataFrame,
        y_test: pd.Series,
        output_path: str,
    ) -> None:
        """
        輸出 predictions.csv，包含：
        - order_id_hash（若存在）
        - p_late（延遲機率）
        - risk_bucket（High/Medium/Low）
        - true_label
        - expected_penalty（預期罰款 = p_late × DEFAULT_DELAY_PENALTY）
        - upgrade_cost（固定升級成本）
        """
        y_prob = self.predict_proba(X_test)

        pred_df = pd.DataFrame({
            "p_late": y_prob.round(4),
            "true_label": y_test.values,
        })

        # 加回 order_id_hash（如果存在於 X_test）
        if "Order Id_hash" in X_test.columns:
            pred_df.insert(0, "order_id_hash", X_test["Order Id_hash"].values)

        # 風險分桶
        pred_df["risk_bucket"] = pd.cut(
            pred_df["p_late"],
            bins=[-0.001, RISK_THRESHOLDS["Medium"], RISK_THRESHOLDS["High"], 1.001],
            labels=["Low", "Medium", "High"],
        )

        # 最佳化所需欄位
        pred_df["expected_penalty"] = (pred_df["p_late"] * DEFAULT_DELAY_PENALTY).round(2)
        pred_df["upgrade_cost"] = DEFAULT_UPGRADE_COST

        pred_df.to_csv(output_path, index=False)
        print(f"\n  predictions.csv 已儲存：{output_path}")
        print(f"  高風險訂單（p_late ≥ {RISK_THRESHOLDS['High']}）：{(pred_df['risk_bucket'] == 'High').sum()} 筆")


# ── 直接執行入口 ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="EDIS ModelPipeline")
    parser.add_argument("--train", default="data/processed/train_ready.csv")
    parser.add_argument("--test", default="data/processed/test_ready.csv")
    parser.add_argument("--output", default="data/processed")
    parser.add_argument("--model-dir", default="models")
    args = parser.parse_args()

    mp = ModelPipeline()
    mp.run(
        train_path=args.train,
        test_path=args.test,
        output_dir=args.output,
        model_dir=args.model_dir,
    )
