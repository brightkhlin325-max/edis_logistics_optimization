"""
Profit regression model pipeline for the EDIS/DataCo project.

This module intentionally owns only the model layer. It expects another
preprocessing pipeline to produce train/validation/test CSV files with numeric,
model-ready features plus the target column.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

try:
    import lightgbm as lgb
except ImportError as exc:  # pragma: no cover - exercised only when dependency is missing
    raise ImportError(
        "LightGBM is required for ProfitModelPipeline. Install with: "
        "conda install -n AI -c conda-forge lightgbm"
    ) from exc


TARGET_COLUMN = "Order Profit Per Order"
DEFAULT_MODEL_PATH = "models/profit_lightgbm_model.txt"
DEFAULT_METRICS_PATH = "data/processed/profit_model_metrics.json"
DEFAULT_PREDICTIONS_PATH = "data/processed/profit_predictions.csv"
DEFAULT_MANIFEST_PATH = "models/profit_feature_manifest.json"

LEAKAGE_COLUMNS = {
    "Benefit per order",
    "Order Item Profit Ratio",
}

NON_MODEL_COLUMNS = {
    "Customer Email",
    "Customer Password",
    "Customer Fname",
    "Customer Lname",
    "Customer Street",
    "Customer Zipcode",
    "Customer Id",
    "Order Id",
    "Order Item Id",
    "Order Customer Id",
    "Category Id",
    "Department Id",
    "Product Card Id",
    "Product Category Id",
    "Order Item Cardprod Id",
    "Product Image",
    "Product Description",
    "Order Zipcode",
}

LIGHTGBM_REGRESSOR_PARAMS = {
    "objective": "regression",
    "metric": "rmse",
    "n_estimators": 1200,
    "learning_rate": 0.04,
    "num_leaves": 63,
    "max_depth": -1,
    "min_child_samples": 30,
    "subsample": 0.85,
    "subsample_freq": 1,
    "colsample_bytree": 0.85,
    "reg_alpha": 0.05,
    "reg_lambda": 1.5,
    "random_state": 42,
    "n_jobs": -1,
    "verbosity": -1,
}


class ProfitModelPipeline:
    """Train, evaluate, and save the profit regression model."""

    def __init__(
        self,
        params: dict | None = None,
        target_column: str = TARGET_COLUMN,
        leakage_policy: str = "raise",
    ):
        if leakage_policy not in {"raise", "drop"}:
            raise ValueError("leakage_policy must be either 'raise' or 'drop'")
        self.params = dict(params or LIGHTGBM_REGRESSOR_PARAMS)
        self.target_column = target_column
        self.leakage_policy = leakage_policy
        self.model: lgb.LGBMRegressor | lgb.Booster | None = None
        self.feature_names: list[str] = []
        self.eval_metrics: dict = {}

    def run(
        self,
        train_path: str,
        test_path: str,
        val_path: str | None = None,
        output_dir: str = "data/processed",
        model_dir: str = "models",
    ) -> dict:
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(model_dir, exist_ok=True)

        X_train, y_train = self._load_ready_frame(train_path)
        X_test, y_test = self._load_ready_frame(test_path)
        X_val, y_val = self._load_ready_frame(val_path) if val_path else (None, None)

        self._assert_same_features(X_train, X_test, dataset_name="test")
        if X_val is not None:
            self._assert_same_features(X_train, X_val, dataset_name="validation")

        self.feature_names = list(X_train.columns)
        self.train(X_train, y_train, X_val, y_val)
        self.eval_metrics = self.evaluate(X_test, y_test)

        model_path = Path(model_dir) / "profit_lightgbm_model.txt"
        metrics_path = Path(output_dir) / "profit_model_metrics.json"
        predictions_path = Path(output_dir) / "profit_predictions.csv"
        manifest_path = Path(model_dir) / "profit_feature_manifest.json"

        self.save(str(model_path))
        self._save_metrics(metrics_path)
        self._save_predictions(X_test, y_test, predictions_path)
        self._save_manifest(manifest_path)

        return self.eval_metrics

    def train(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: pd.DataFrame | None = None,
        y_val: pd.Series | None = None,
    ) -> None:
        self.model = lgb.LGBMRegressor(**self.params)
        fit_kwargs = {"X": X_train, "y": y_train}
        if X_val is not None and y_val is not None:
            fit_kwargs["eval_set"] = [(X_val, y_val)]
            fit_kwargs["eval_metric"] = "rmse"
            fit_kwargs["callbacks"] = [
                lgb.early_stopping(stopping_rounds=50, verbose=False),
                lgb.log_evaluation(period=0),
            ]
        self.model.fit(**fit_kwargs)

    def evaluate(self, X_test: pd.DataFrame, y_test: pd.Series) -> dict:
        y_pred = self.predict(X_test)
        rmse = float(np.sqrt(mean_squared_error(y_test, y_pred)))
        mae = mean_absolute_error(y_test, y_pred)
        r2 = r2_score(y_test, y_pred)

        residuals = y_test.to_numpy(dtype=float) - y_pred
        metrics = {
            "target_column": self.target_column,
            "row_count": int(len(y_test)),
            "feature_count": int(X_test.shape[1]),
            "rmse": round(float(rmse), 4),
            "mae": round(float(mae), 4),
            "r2": round(float(r2), 4),
            "residual_mean": round(float(np.mean(residuals)), 4),
            "residual_p95_abs": round(float(np.percentile(np.abs(residuals), 95)), 4),
            "model_type": "lightgbm_regressor",
            "leakage_policy": self.leakage_policy,
            "feature_importance": self._feature_importance(top_n=20),
        }
        return metrics

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        if self.model is None:
            raise RuntimeError("Model is not trained or loaded.")
        return self.model.predict(X)

    def save(self, path: str = DEFAULT_MODEL_PATH) -> None:
        if self.model is None:
            raise RuntimeError("Model is not trained.")
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.model.booster_.save_model(path)

    def load(self, path: str = DEFAULT_MODEL_PATH) -> None:
        self.model = lgb.Booster(model_file=path)

    def _load_ready_frame(self, path: str | None) -> tuple[pd.DataFrame, pd.Series]:
        if not path:
            raise ValueError("A CSV path is required.")
        df = pd.read_csv(path)
        if self.target_column not in df.columns:
            raise ValueError(f"Missing target column '{self.target_column}' in {path}")

        forbidden = sorted((LEAKAGE_COLUMNS | NON_MODEL_COLUMNS).intersection(df.columns))
        if forbidden and self.leakage_policy == "raise":
            raise ValueError(
                "Model input still contains forbidden columns: "
                + ", ".join(forbidden)
                + ". Ask the preprocessing owner to remove them, or rerun with "
                "--leakage-policy drop for an explicit defensive drop."
            )
        if forbidden:
            df = df.drop(columns=forbidden)

        y = pd.to_numeric(df[self.target_column], errors="raise")
        X = df.drop(columns=[self.target_column])

        non_numeric = sorted(X.select_dtypes(exclude=[np.number, "bool"]).columns)
        if non_numeric:
            raise ValueError(
                "ProfitModelPipeline expects preprocessed numeric features. "
                f"Non-numeric columns found: {', '.join(non_numeric)}"
            )
        X = X.astype(float)
        return X, y

    def _assert_same_features(
        self,
        X_train: pd.DataFrame,
        X_other: pd.DataFrame,
        dataset_name: str,
    ) -> None:
        train_cols = list(X_train.columns)
        other_cols = list(X_other.columns)
        if train_cols == other_cols:
            return
        missing = sorted(set(train_cols) - set(other_cols))
        extra = sorted(set(other_cols) - set(train_cols))
        raise ValueError(
            f"{dataset_name} features do not match training features. "
            f"Missing: {missing}. Extra: {extra}."
        )

    def _feature_importance(self, top_n: int = 20) -> dict:
        if self.model is None or not self.feature_names:
            return {}
        values = getattr(self.model, "feature_importances_", None)
        if values is None:
            return {}
        importance = pd.Series(values, index=self.feature_names).sort_values(ascending=False)
        return {name: round(float(value), 6) for name, value in importance.head(top_n).items()}

    def _save_metrics(self, path: Path) -> None:
        with path.open("w", encoding="utf-8") as f:
            json.dump(self.eval_metrics, f, ensure_ascii=False, indent=2)

    def _save_predictions(
        self,
        X_test: pd.DataFrame,
        y_test: pd.Series,
        path: Path,
    ) -> None:
        y_pred = self.predict(X_test)
        pred_df = pd.DataFrame(
            {
                "actual_profit": y_test.to_numpy(dtype=float),
                "predicted_profit": y_pred,
            }
        )
        pred_df["residual"] = pred_df["actual_profit"] - pred_df["predicted_profit"]
        pred_df.to_csv(path, index=False)

    def _save_manifest(self, path: Path) -> None:
        payload = {
            "target_column": self.target_column,
            "model_path": DEFAULT_MODEL_PATH,
            "feature_columns": self.feature_names,
            "leakage_columns_blocked": sorted(LEAKAGE_COLUMNS),
            "non_model_columns_blocked": sorted(NON_MODEL_COLUMNS),
            "model_type": "lightgbm_regressor",
            "model_params": self.params,
        }
        with path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train EDIS profit regression model.")
    parser.add_argument("--train", default="data/processed/profit_train_ready.csv")
    parser.add_argument("--val", default="data/processed/profit_val_ready.csv")
    parser.add_argument("--test", default="data/processed/profit_test_ready.csv")
    parser.add_argument("--output", default="data/processed")
    parser.add_argument("--model-dir", default="models")
    parser.add_argument("--target", default=TARGET_COLUMN)
    parser.add_argument("--leakage-policy", choices=["raise", "drop"], default="raise")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> dict:
    args = parse_args(argv)
    val_path = args.val if os.path.exists(args.val) else None
    pipeline = ProfitModelPipeline(
        target_column=args.target,
        leakage_policy=args.leakage_policy,
    )
    metrics = pipeline.run(
        train_path=args.train,
        val_path=val_path,
        test_path=args.test,
        output_dir=args.output,
        model_dir=args.model_dir,
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return metrics


if __name__ == "__main__":
    main()
