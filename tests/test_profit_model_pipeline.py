import json

import pandas as pd
import pytest

pytest.importorskip("lightgbm")

from profit_model_pipeline import ProfitModelPipeline


def _model_params():
    return {
        "objective": "regression",
        "metric": "rmse",
        "n_estimators": 12,
        "num_leaves": 7,
        "max_depth": -1,
        "learning_rate": 0.2,
        "subsample": 1.0,
        "colsample_bytree": 1.0,
        "random_state": 42,
        "n_jobs": 1,
        "verbosity": -1,
    }


def _ready_frame(rows=24):
    records = []
    for i in range(rows):
        quantity = 1 + (i % 5)
        price = 20.0 + i
        discount = (i % 3) * 0.05
        scheduled_days = 2 + (i % 4)
        profit = price * quantity * (0.18 - discount / 2) - scheduled_days
        records.append(
            {
                "Product Price": price,
                "Order Item Quantity": quantity,
                "Order Item Discount Rate": discount,
                "Days for shipment (scheduled)": scheduled_days,
                "Market_Europe": int(i % 2 == 0),
                "Market_USCA": int(i % 2 == 1),
                "Order Profit Per Order": profit,
            }
        )
    return pd.DataFrame(records)


def test_profit_model_pipeline_trains_and_writes_artifacts(tmp_path):
    df = _ready_frame()
    train_path = tmp_path / "profit_train_ready.csv"
    val_path = tmp_path / "profit_val_ready.csv"
    test_path = tmp_path / "profit_test_ready.csv"
    df.iloc[:14].to_csv(train_path, index=False)
    df.iloc[14:19].to_csv(val_path, index=False)
    df.iloc[19:].to_csv(test_path, index=False)

    pipeline = ProfitModelPipeline(params=_model_params())
    metrics = pipeline.run(
        train_path=str(train_path),
        val_path=str(val_path),
        test_path=str(test_path),
        output_dir=str(tmp_path),
        model_dir=str(tmp_path),
    )

    assert metrics["model_type"] == "lightgbm_regressor"
    assert metrics["target_column"] == "Order Profit Per Order"
    assert metrics["feature_count"] == 6
    assert "rmse" in metrics
    assert (tmp_path / "profit_lightgbm_model.txt").exists()
    assert (tmp_path / "profit_model_metrics.json").exists()
    assert (tmp_path / "profit_predictions.csv").exists()

    manifest = json.loads((tmp_path / "profit_feature_manifest.json").read_text())
    # 團隊決策：Order Item Profit Ratio 視為已知 margin（合法特徵），只有 Benefit per order
    # 仍為純洩漏（見 reports/profit_data_pipeline_decisions_2026-06-23.md §11.6）。
    assert "Benefit per order" in manifest["leakage_columns_blocked"]
    assert "Order Item Profit Ratio" not in manifest["leakage_columns_blocked"]
    assert manifest["feature_columns"] == [
        "Product Price",
        "Order Item Quantity",
        "Order Item Discount Rate",
        "Days for shipment (scheduled)",
        "Market_Europe",
        "Market_USCA",
    ]


def test_profit_model_pipeline_rejects_leakage_columns(tmp_path):
    df = _ready_frame(8)
    df["Benefit per order"] = 0.2   # 純洩漏欄（== 利潤本身）仍須被擋
    path = tmp_path / "profit_train_ready.csv"
    df.to_csv(path, index=False)

    pipeline = ProfitModelPipeline(params=_model_params())
    with pytest.raises(ValueError, match="forbidden columns"):
        pipeline._load_ready_frame(str(path))


def test_profit_model_pipeline_can_defensively_drop_leakage(tmp_path):
    df = _ready_frame(8)
    df["Benefit per order"] = df["Order Profit Per Order"]
    path = tmp_path / "profit_train_ready.csv"
    df.to_csv(path, index=False)

    pipeline = ProfitModelPipeline(params=_model_params(), leakage_policy="drop")
    X, y = pipeline._load_ready_frame(str(path))

    assert "Benefit per order" not in X.columns
    assert y.name == "Order Profit Per Order"


def test_profit_model_pipeline_requires_numeric_preprocessed_features(tmp_path):
    df = _ready_frame(8)
    df["Shipping Mode"] = "Standard Class"
    path = tmp_path / "profit_train_ready.csv"
    df.to_csv(path, index=False)

    pipeline = ProfitModelPipeline(params=_model_params())
    with pytest.raises(ValueError, match="Non-numeric columns"):
        pipeline._load_ready_frame(str(path))
