# EDIS / SLIDE Final Demo Script

This script keeps the presentation focused on one story: prediction becomes logistics action.

## 0. Setup Check

Start the app:

```bash
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000/static/index.html
```

Recommended quick health checks:

```bash
curl 'http://127.0.0.1:8000/api/metrics?threshold=0.5'
curl 'http://127.0.0.1:8000/api/profit/metrics'
```

## 1. Opening

Talk track:

> Logistics teams cannot upgrade every shipment. EDIS predicts which orders are likely to be late, estimates business impact, and recommends where limited logistics budget should be used first.

Show:

- Dashboard KPI cards.
- Current threshold value.
- High-risk order count and expected penalty exposure.

## 2. Delay Risk

Show:

- Risk order table.
- Threshold slider.
- Feature importance or risk explanation.

Talk track:

> The model output is not only a probability. We convert the probability into risk tiers and expected penalty so a manager can act on it.

## 3. Manager Optimization

Steps:

1. Switch role to Manager.
2. Login with the demo credentials.
3. Open optimization.
4. Enter a budget.
5. Run optimization.

Talk track:

> The optimizer does not simply sort by risk. It chooses the best set of orders under budget constraints, so the recommendation is operationally feasible.

Show:

- Selected order count.
- Total spend.
- Expected net benefit.
- Sample selected orders and reasons.

## 4. AI Decision Assistant

Show:

- AI assistant or manager brief.
- Explain that the LLM payload is de-identified and aggregate-safe.

Talk track:

> The AI assistant is used after the deterministic model and optimizer. It explains the decision in manager-friendly language; it does not replace the optimization logic.

## 5. Profit Prediction

Show:

- Profit Prediction page.
- RMSE / MAE / R2.
- Feature importance.
- Highest residual examples.

Talk track:

> Profit prediction is a separate regression module. It helps evaluate financial impact, but we state its assumption clearly: margin must be known at decision time for this to be a valid pre-shipment predictor.

## 6. Engineer View

Steps:

1. Switch to Engineer if credentials are available.
2. Show model diagnostics and retraining.
3. Show regional map and RBAC page.

Talk track:

> The Engineer view is for maintenance: model monitoring, retraining, map diagnostics, and permission review.

## 7. Teacher Feedback Closing

Show `reports/teacher_feedback_alignment.md` or a slide derived from it.

Close with:

> The final system responds to the original feedback by showing model quality, business decisions, adjustable parameters, explanations, role permissions, and financial analysis in one workflow.

## Backup Plan

If LLM key setup fails, use the local fallback summary and say:

> The external LLM is optional. The project still runs because the core model, optimizer, and local explanation pipeline are independent from the API key.
