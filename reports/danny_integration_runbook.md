# Danny Integration Runbook

Owner: Danny  
Goal: Make the full EDIS demo run from raw data to dashboard.

## Integration Flow

```text
data/raw/DataCoSupplyChainDataset.csv
  -> core/security_utils.py
  -> core/data_pipeline.py
  -> data/processed/train_ready.csv
  -> data/processed/test_ready.csv
  -> data/processed/test_metadata.csv
  -> core/model_pipeline.py
  -> data/processed/predictions.csv
  -> data/processed/model_metrics.json
  -> core/optimizer.py
  -> data/processed/optimization_result.json
  -> app.py
  -> static/index.html
```

## First-Time Setup

```bash
conda env create -f environment.yml
conda activate Fastapp
```

If the environment already exists:

```bash
conda env update -f environment.yml --prune
conda activate Fastapp
```

## Run The Pipeline

Place the DataCo CSV here:

```text
data/raw/DataCoSupplyChainDataset.csv
```

Then run:

```bash
python core/data_pipeline.py --input data/raw/DataCoSupplyChainDataset.csv --output data/processed --sample 30000
python core/model_pipeline.py --train data/processed/train_ready.csv --test data/processed/test_ready.csv --output data/processed --model-dir models
python core/optimizer.py --predictions data/processed/predictions.csv --output data/processed --budget 5000
```

## Run The App

```bash
uvicorn app:app --reload --port 8000
```

Open:

```text
http://localhost:8000/static/index.html
```

## Danny's Acceptance Checklist

- `data/processed/train_ready.csv` exists.
- `data/processed/test_ready.csv` exists.
- `data/processed/test_metadata.csv` exists.
- `data/processed/predictions.csv` includes `order_id_hash`, `shipping_mode`, `order_region`, `p_late`, `risk_bucket`, `upgrade_cost`, `expected_penalty`.
- `data/processed/model_metrics.json` includes ROC-AUC, F1, precision, recall, late rate, and high risk count.
- Viewer can open the dashboard and see metrics and risk orders.
- Viewer cannot run optimize.
- Logistics_Manager can run optimize.
- `/api/optimize` returns selected orders within budget.

## Demo Talk Track

1. The business problem is not only predicting late deliveries; the harder decision is choosing where limited upgrade budget should go.
2. EDIS first removes sensitive customer fields and hashes order IDs.
3. XGBoost estimates each order's delay probability.
4. The optimizer converts `p_late` into a budget-constrained upgrade recommendation.
5. RBAC separates visibility from action: Viewer can inspect risk, Logistics_Manager can execute optimization.
