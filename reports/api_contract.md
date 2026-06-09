# EDIS API Contract

Owner: Danny  
Purpose: Keep backend, optimizer, and dashboard aligned during integration.

## Roles

Use the `X-Role` request header.

| Role | Meaning | Optimize Access |
|---|---|---|
| `Viewer` | Can view metrics and prediction summaries | No, must return 403 |
| `Logistics_Manager` | Can view predictions and run optimization | Yes |

## GET `/api/metrics`

Returns model KPI values for the dashboard.

```json
{
  "roc_auc": 0.91,
  "f1": 0.84,
  "recall": 0.86,
  "precision": 0.82,
  "late_rate": 0.54,
  "high_risk_orders": 128
}
```

Source file:

```text
data/processed/model_metrics.json
```

## GET `/api/predict`

Request:

```text
X-Role: Viewer
```

Response:

```json
{
  "role": "Viewer",
  "count": 50,
  "data": [
    {
      "order_id_hash": "a8f3...",
      "shipping_mode": "Standard Class",
      "order_region": "Western Europe",
      "p_late": 0.82,
      "risk_bucket": "High",
      "upgrade_cost": 80.0,
      "expected_penalty": 205.0
    }
  ]
}
```

Source file:

```text
data/processed/predictions.csv
```

Required CSV columns:

```text
order_id_hash,p_late,risk_bucket,upgrade_cost,expected_penalty
```

Recommended CSV columns for dashboard display:

```text
shipping_mode,order_region
```

## POST `/api/optimize`

Request:

```text
X-Role: Logistics_Manager
Content-Type: application/json
```

```json
{
  "budget": 5000,
  "upgrade_cost": 80,
  "delay_penalty": 250,
  "max_candidates": 500
}
```

Response:

```json
{
  "role": "Logistics_Manager",
  "budget": 5000,
  "selected_count": 12,
  "total_cost": 960,
  "expected_total_saving": 2850,
  "expected_total_penalty_avoided": 3810,
  "solver": "PuLP MILP",
  "selected_orders": [
    {
      "order_id_hash": "a8f3...",
      "p_late": 0.88,
      "upgrade_cost": 80,
      "expected_penalty": 220,
      "net_benefit": 140,
      "expected_saving": 140,
      "risk_bucket": "High",
      "decision": "Upgrade",
      "reason": "High risk, p_late=0.88, net benefit NT$ 140, within budget"
    }
  ]
}
```

Viewer must receive HTTP 403 when calling this endpoint.

Notes:

- `expected_penalty` is the expected avoided delay penalty before upgrade cost.
- `net_benefit = expected_penalty - upgrade_cost`.
- `expected_saving` is kept for dashboard compatibility and should match `net_benefit`.
- `max_candidates` limits the highest net-benefit orders entering the solver so the demo remains responsive.
