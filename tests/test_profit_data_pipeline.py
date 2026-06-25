import pandas as pd

from profit_data_pipeline import (
    CATEGORICAL_FEATURES,
    DATE_COLUMN,
    NUMERIC_FEATURES,
    ORDER_ID_COLUMN,
    POST_OUTCOME_COLUMNS,
    TARGET_COLUMN,
    ProfitDataPipeline,
)


def _raw_profit_frame(rows=8):
    records = []
    for i in range(rows):
        row = {
            DATE_COLUMN: f"2026-01-{i + 1:02d} 10:00:00",
            ORDER_ID_COLUMN: 1000 + i,
            TARGET_COLUMN: 20.0 + i,
            "Days for shipping (real)": 2 + (i % 3),
            "Late_delivery_risk": int(i % 2 == 0),
            "Delivery Status": "Late delivery" if i % 2 == 0 else "Advance shipping",
        }
        for col in NUMERIC_FEATURES:
            row.setdefault(col, float(i + 1))
        for col in CATEGORICAL_FEATURES:
            row.setdefault(col, f"{col}_{i % 2}")
        records.append(row)
    return pd.DataFrame(records)


def test_profit_data_pipeline_excludes_post_outcome_features_from_ready_schema():
    raw = _raw_profit_frame()
    pipeline = ProfitDataPipeline()
    artifacts = pipeline.fit(raw.iloc[:5])
    ready = pipeline.transform(raw.iloc[5:])

    forbidden = set(POST_OUTCOME_COLUMNS)
    assert forbidden.isdisjoint(artifacts["feature_columns"])
    assert forbidden.isdisjoint(artifacts["numeric_columns"])
    assert forbidden.isdisjoint(artifacts["categorical_columns"])
    assert forbidden.isdisjoint(ready.columns)
    assert artifacts["dropped_columns"]["post_outcome"] == POST_OUTCOME_COLUMNS

