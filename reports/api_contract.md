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
  "manager_analysis": {
    "headline": "建議主管核准本批調度...",
    "recommended_policy": "優先升級高風險且淨效益為正的訂單...",
    "budget_usage_pct": 19.2,
    "sample_order_explanations": [
      {
        "order_id_hash": "a8f3...",
        "risk_bucket": "High",
        "p_late": 0.88,
        "recommended_action": "升級運送並列入優先調度",
        "top_x_factors": [
          {
            "feature": "Shipping Mode_Standard Class",
            "label": "運送模式",
            "impact": "raises risk",
            "evidence": "此訂單使用 Standard Class，模型將運送模式列為主要 X 因子",
            "weight": 0.34
          }
        ],
        "manager_summary": "此訂單延遲風險為 High..."
      }
    ],
    "llm_ready_prompt": "請用物流主管能理解的語氣..."
  },
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

## GET `/api/explain/{order_id_hash}`

Returns the top X factors and manager-facing explanation for a single de-identified order.

Current implementation uses LIME-style local attribution from `model_metrics.json`
feature importance plus the visible order fields in `predictions.csv`. When the
project exports the original test feature matrix, this endpoint can swap in true
LIME without changing the response shape.

Request:

```text
X-Role: Viewer | Logistics_Manager
```

Response:

```json
{
  "role": "Viewer",
  "order_id_hash": "a8f3...",
  "risk_bucket": "High",
  "p_late": 0.88,
  "recommended_action": "升級運送並列入優先調度",
  "expected_penalty": 220,
  "upgrade_cost": 80,
  "net_benefit": 140,
  "top_x_factors": [
    {
      "feature": "Shipping Mode_Standard Class",
      "label": "運送模式",
      "impact": "raises risk",
      "evidence": "此訂單使用 Standard Class，模型將運送模式列為主要 X 因子",
      "weight": 0.34
    }
  ],
  "manager_summary": "此訂單延遲風險為 High...",
  "explanation_method": "LIME-style local attribution using feature importance..."
}
```

Viewer must receive HTTP 403 when calling `POST /api/optimize`.

Notes:

- `expected_penalty` is the expected avoided delay penalty before upgrade cost.
- `net_benefit = expected_penalty - upgrade_cost`.
- `expected_saving` is kept for dashboard compatibility and should match `net_benefit`.
- `max_candidates` limits the highest net-benefit orders entering the solver so the demo remains responsive.
