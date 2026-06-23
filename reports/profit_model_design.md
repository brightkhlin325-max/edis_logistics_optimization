# Profit Prediction Model Design

## Scope

This design covers only the model layer for predicting `Order Profit Per Order`.
Data loading, cleaning, encoding, date features, train/validation/test splitting,
and missing-value handling are owned by the preprocessing team.

## Model Choice

Primary model: LightGBM regressor.

Reasoning:
- The DataCo feature space is tabular, mixed-source, and nonlinear after preprocessing.
- LightGBM is a strong default for large tabular datasets with mixed numeric and encoded
  categorical features.
- LightGBM supports early stopping, feature importance, and compact model export that fits
  the existing artifact pattern in `models/`.

## Expected Input Contract

Default files:
- `data/processed/profit_train_ready.csv`
- `data/processed/profit_val_ready.csv`
- `data/processed/profit_test_ready.csv`

Each file must contain:
- Numeric, model-ready feature columns.
- Target column: `Order Profit Per Order`.
- Identical feature columns across train, validation, and test.

The model layer rejects non-numeric features because category/date encoding belongs to
preprocessing.

## Leakage Guard And Margin Assumption

The model layer permanently blocks known direct profit leakage:
- `Benefit per order`

The team intentionally treats `Order Item Profit Ratio` as a known pricing-margin
feature at decision time. This is the assumption that makes the current profit model
useful as a pre-shipment predictor.

If a real deployment only knows margin after order fulfillment, `Order Item Profit Ratio`
must be removed and the module should be presented as retrospective profit analysis
instead of forward-looking prediction.

The model also blocks raw PII, IDs, and non-model fields listed in
`core/profit_model_pipeline.py`. Default behavior is `--leakage-policy raise`, which
fails fast and asks preprocessing to fix the ready files. Use `--leakage-policy drop`
only for an explicit defensive drop.

## Outputs

Default outputs:
- `models/profit_lightgbm_model.txt`
- `models/profit_feature_manifest.json`
- `data/processed/profit_model_metrics.json`
- `data/processed/profit_predictions.csv`

Metrics:
- RMSE
- MAE
- R2
- residual mean
- absolute residual p95
- top 20 feature importance values

Current demo metrics from the committed artifacts:

| Metric | Value |
|---|---:|
| RMSE | 61.6712 |
| MAE | 7.3617 |
| R2 | 0.8069 |
| Rows | 27,078 |
| Features | 37 |

## Run Command

```powershell
D:\anaconda_envs\AI\python.exe core\profit_model_pipeline.py `
  --train data\processed\profit_train_ready.csv `
  --val data\processed\profit_val_ready.csv `
  --test data\processed\profit_test_ready.csv `
  --output data\processed `
  --model-dir models
```
