# Teacher Feedback Alignment

This file maps the main feedback themes to the current EDIS / SLIDE implementation and the final presentation evidence.

| Feedback Theme | Implemented Response | Where To Show It |
|---|---|---|
| Show model quality, not only raw predictions | Dashboard metrics, confusion matrix, threshold tuning, model diagnostics | Dashboard, Model Diagnostics, `/api/metrics` |
| Turn predictions into decisions | PuLP MILP optimization recommends upgrade orders under budget | Optimization page, `/api/optimize` |
| Explain why delays happen | Feature importance, LIME-style local explanations, manager summary | Risk list, explain modal, AI assistant |
| Add visual charts | Monthly trend, regional map, KPI cards, feature importance bars | Dashboard, Regional Risk Map, Profit Prediction |
| Let users adjust assumptions | Threshold slider, budget, upgrade cost, delay penalty, scenario analysis | Dashboard and Optimization pages |
| Make it understandable for non-technical users | Manager-facing recommendations and AI decision assistant | AI Decision Assistant, optimization summary |
| Demonstrate permissions | Viewer can inspect, Manager/Engineer can execute sensitive actions | Role switcher, RBAC page, 403 endpoint behavior |
| Include financial impact | Expected penalty, net benefit, profit prediction regression | Optimization and Profit Prediction pages |

## Presentation Recommendation

Use this order in the final deck:

1. Business problem: limited logistics budget.
2. Delay model: predicts risk and explains drivers.
3. Optimization: selects feasible actions.
4. Profit model: adds financial context.
5. RBAC and system design: shows operational maturity.
6. Limitations: states assumptions honestly.

## Remaining Honesty Notes

- The profit model currently assumes `Order Item Profit Ratio` is available before the decision. If that is not true in a real business setting, this module should be framed as retrospective profit analysis or retrained without that feature.
- The app still accepts `X-Role` for classroom/demo convenience. Production security should rely only on signed bearer tokens.
- LLM output is optional. The core decision flow must remain usable with local explanations when no external API key is configured.
