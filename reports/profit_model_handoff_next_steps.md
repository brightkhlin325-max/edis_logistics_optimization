# Profit Model Handoff / Next Steps

> Date: 2026-06-24  
> Purpose: Preserve enough context for the next Codex/session to continue the profit model work without relying on chat history.  
> Current direction: use a forward-looking profit model plus a separate delay model, then combine both outputs in the decision/optimization layer.

---

## 1. Product / Modeling Decision

The system should support decisions for an order whose delay and profit are not yet known:

```text
new order features
  -> delay model predicts p_late
  -> profit model predicts accounting/product profit
  -> decision layer combines profit_pred and p_late
```

Recommended decision-layer formula:

```text
expected_penalty = p_late * delay_penalty
risk_adjusted_profit = profit_pred - expected_penalty
```

For rescue/upgrade optimization:

```text
expected_saved_value = p_late * avoidable_penalty
net_benefit = expected_saved_value - upgrade_cost
```

Profit prediction and delay prediction should remain separate models. The delay model output should not be casually fed into the profit model unless a future explicit "net profit after service" target is created and double-counting is avoided.

---

## 2. Completed In This Session

### 2.1 Profit Predictions Now Support Join Key

Modified:

```text
core/profit_model_pipeline.py
app.py
static/profit_prediction.js
tests/test_profit_model_pipeline.py
```

Behavior:

- `ProfitModelPipeline.run()` now looks for:

```text
data/processed/profit_test_metadata.csv
```

- If metadata exists, it is merged into:

```text
data/processed/profit_predictions.csv
```

- New expected output columns:

```text
order_id_hash
order_date
is_outlier
actual_profit
predicted_profit
residual
```

- Validation added:
  - metadata must contain `order_id_hash`, `order_date`, `is_outlier`
  - metadata row count must match test prediction row count
  - `order_id_hash` must not be empty

Why this matters:

`order_id_hash` lets profit predictions and delay predictions align to the same order. Without it, `profit_pred` from one order could be accidentally combined with `p_late` from another order.

### 2.2 Profit Model No Longer Uses Known Delay Outcome Features

Modified:

```text
core/profit_data_pipeline.py
core/profit_model_pipeline.py
tests/test_profit_data_pipeline.py
tests/test_profit_model_pipeline.py
```

Removed from profit model features:

```text
Days for shipping (real)
Late_delivery_risk
Delivery Status
```

These are post-outcome fields. They are valid for historical closed-order analysis, but not valid for forward-looking profit prediction.

Added:

```python
POST_OUTCOME_COLUMNS = [
    "Days for shipping (real)",
    "Late_delivery_risk",
    "Delivery Status",
]
```

Protection exists at two layers:

- `ProfitDataPipeline` no longer emits these columns into ready CSV feature columns.
- `ProfitModelPipeline` rejects old ready CSVs that still contain these columns.

---

## 3. Current Known Local Constraints

The current workspace does not contain the raw DataCo CSV:

```text
data/raw/DataCoSupplyChainDataset.csv
```

So processed CSVs and model artifacts were not regenerated during this session.

Current environment also lacks some test/runtime dependencies:

```text
lightgbm
fastapi
```

Observed verification:

```text
pytest tests/test_profit_data_pipeline.py -q
# passed

python -m py_compile core\profit_data_pipeline.py core\profit_model_pipeline.py tests\test_profit_data_pipeline.py tests\test_profit_model_pipeline.py
# passed

pytest tests/test_profit_model_pipeline.py -q
# skipped because lightgbm is missing

pytest tests/test_api_endpoints.py -q
# failed at collection because fastapi is missing
```

---

## 4. Next Required Work

### Step 1. Regenerate Profit Data Artifacts

After restoring the raw CSV:

```text
data/raw/DataCoSupplyChainDataset.csv
```

run:

```powershell
python core\profit_data_pipeline.py
```

Expected outputs:

```text
data/processed/profit_train_ready.csv
data/processed/profit_val_ready.csv
data/processed/profit_test_ready.csv
data/processed/profit_train_metadata.csv
data/processed/profit_val_metadata.csv
data/processed/profit_test_metadata.csv
data/processed/profit_feature_schema.json
data/processed/profit_split_report.json
models/profit/serving_artifacts.json
```

Check:

- ready CSVs must not contain:

```text
Days for shipping (real)
Late_delivery_risk
Delivery Status
Benefit per order
Order Id
Customer Id
```

- `profit_test_metadata.csv` must contain:

```text
order_id_hash
order_date
is_outlier
```

### Step 2. Retrain Profit Model

Run:

```powershell
python core\profit_model_pipeline.py `
  --train data\processed\profit_train_ready.csv `
  --val data\processed\profit_val_ready.csv `
  --test data\processed\profit_test_ready.csv `
  --output data\processed `
  --model-dir models
```

Expected outputs:

```text
models/profit_lightgbm_model.txt
models/profit_feature_manifest.json
data/processed/profit_model_metrics.json
data/processed/profit_predictions.csv
```

Check:

```text
profit_predictions.csv contains order_id_hash
order_id_hash is non-empty
row count equals profit_test_ready.csv row count
```

### Step 3. Verify Join With Delay Predictions

Delay predictions file:

```text
data/processed/predictions.csv
```

Expected important columns:

```text
order_id_hash
p_late
risk_bucket
expected_penalty
upgrade_cost
```

Verify an inner join:

```python
import pandas as pd

profit = pd.read_csv("data/processed/profit_predictions.csv")
delay = pd.read_csv("data/processed/predictions.csv")

joined = profit.merge(delay, on="order_id_hash", how="inner")
print(len(profit), len(delay), len(joined))
```

If joined row count is unexpectedly low, inspect whether both pipelines use the same hashing salt and source `Order Id`.

### Step 4. Add Portfolio / Decision Layer Dataset

Create a unified decision frame with at least:

```text
order_id_hash
order_state
profit_actual
profit_pred
late_actual
late_pred
expected_penalty
risk_adjusted_profit
is_outlier
order_date
```

For current historical test rows:

```text
profit_actual = actual_profit
profit_pred = predicted_profit
late_pred = p_late
expected_penalty = p_late * delay_penalty
risk_adjusted_profit = predicted_profit - expected_penalty
```

Decision rule:

```text
closed orders: use actuals for analysis/calibration
open/prospective orders: use predictions for decisioning
```

Likely implementation locations:

```text
app.py
core/optimizer.py
static/optimization.js
static/profit_prediction.js
```

### Step 5. Update Optimization To Use Profit Value

Current delay optimization already uses delay risk / penalty / upgrade cost. Next improvement is to integrate profit value.

Candidate scoring:

```text
expected_service_loss = p_late * delay_penalty
value_at_risk = max(profit_pred, 0) * p_late
optimization_value = expected_service_loss + value_at_risk - upgrade_cost
```

Be careful:

- Do not use raw `profit_pred * p_late` when profit can be negative.
- Avoid double-counting delay penalty if later using a net-profit target.

### Step 6. Robust Modeling Experiment

The original execution plan asks for experiments because extreme losses are under-predicted.

Implement at least:

```text
baseline: current LightGBM regression, raw y
signed_log: sign(y) * log1p(abs(y)), inverse after prediction
robust_objective: LightGBM regression_l1 or huber
```

Output:

```text
data/processed/profit_model_experiment_report.json
data/processed/profit_model_experiment_predictions.csv
reports/profit_model_experiment_summary.md
```

Metrics should include:

```text
all_mae
all_rmse
loss_mae
loss_rmse
extreme_loss_mae
extreme_loss_rmse
upper_outlier_mae
upper_outlier_rmse
residual_p95_abs
residual_p99_abs
bias
```

Do not select the model only by global R2/MAE.

### Step 7. Confirm `Order Item Profit Ratio`

Current decision:

```text
Order Item Profit Ratio remains a legal feature only if known at order/decision time.
```

Still needs business/data confirmation:

```text
Is Order Item Profit Ratio known at order time?
```

If yes:

```text
keep it and document as legal margin feature
```

If no:

```text
remove from profit features, regenerate data, retrain
```

If unknown:

```text
keep for demo only, but do not claim true prospective decision readiness
```

---

## 5. Suggested Test Commands

After dependencies are available:

```powershell
pytest tests/test_profit_data_pipeline.py -q
pytest tests/test_profit_model_pipeline.py -q
pytest tests/test_api_endpoints.py -q
python -m py_compile app.py core\profit_data_pipeline.py core\profit_model_pipeline.py
```

If only checking the recent data-contract work:

```powershell
pytest tests/test_profit_data_pipeline.py -q
pytest tests/test_profit_model_pipeline.py -q
```

---

## 6. Files Touched Recently

Recent implementation files:

```text
core/profit_data_pipeline.py
core/profit_model_pipeline.py
app.py
static/profit_prediction.js
tests/test_profit_data_pipeline.py
tests/test_profit_model_pipeline.py
```

Pre-existing modified/untracked files were present before the last changes and should not be assumed to be part of this handoff unless inspected:

```text
PROFIT_PREIDCT_PLAN.md
.vscode/
reports/profit_model_adjustment_execution_plan.md
```

---

## 7. Mental Model For Next Session

Keep these responsibilities separate:

```text
profit model: predicts accounting/product profit from decision-time features
delay model: predicts p_late from decision-time features
decision layer: combines profit_pred, p_late, penalty, and upgrade cost
closed-order analysis: uses actuals to calibrate and validate the models
```

Do not reintroduce known delay outcome fields into the profit model unless creating a clearly labeled historical diagnostic model.

