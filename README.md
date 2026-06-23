# EDIS / SLIDE — Enterprise Decision Intelligence System

> DataCo supply-chain delay prediction, profit prediction, and logistics optimization dashboard.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.136-green)
![XGBoost](https://img.shields.io/badge/XGBoost-delay%20risk-orange)
![LightGBM](https://img.shields.io/badge/LightGBM-profit%20prediction-brightgreen)
![License](https://img.shields.io/badge/License-Academic-lightgrey)

---

## Project Summary

EDIS, presented in the UI as **SLIDE 供應鏈物流智慧調度引擎**, turns DataCo supply-chain data into a decision-support workflow:

1. Predict order delay risk with an XGBoost classifier.
2. Explain likely delay drivers through feature importance and local order context.
3. Optimize shipping upgrade decisions under budget constraints with PuLP MILP.
4. Predict order profit with a separate LightGBM regression module.
5. Protect operational actions with role-based access control.
6. Provide a dashboard that non-technical users can operate during a live demo.

The core message for the final presentation:

> The system does not stop at model accuracy. It converts model output into operational logistics decisions.

---

## Current Capabilities

- **Delay Risk Model**: XGBoost classifier with dashboard KPI, confusion matrix, feature importance, and threshold tuning.
- **Optimization Engine**: PuLP 0/1 integer programming selects orders worth upgrading within a budget.
- **Profit Prediction**: LightGBM regressor predicts `Order Profit Per Order` and shows RMSE, MAE, R2, feature importance, and high-error samples.
- **AI Decision Assistant**: Manager/Engineer users can configure LLM providers and generate executive summaries from safe, de-identified payloads.
- **RBAC Demo Flow**: Viewer, Logistics_Manager, and Engineer roles expose different dashboard pages and backend permissions.
- **Model Operations**: Engineer views include model diagnostics, retraining workflow, regional risk map, and RBAC documentation.

---

## Team Scope

| Member | Primary Contribution Area |
|---|---|
| Bright | FastAPI backend, RBAC, API design |
| Lisa | Data processing, de-identification, feature engineering |
| Danny | PuLP optimization, LIME-style explanation, project integration |
| 子堯 | XGBoost modeling, model evaluation |
| 紹光 | Dashboard UI/UX, frontend integration, presentation |
| 祖航 | Profit prediction / LightGBM extension and supporting analysis |

Use the final presentation to report what each member actually implemented or reviewed, not only the planned ownership above.

---

## Key Metrics

### Delay Risk Model

The live API reports model metrics through:

```text
GET /api/metrics?threshold=0.5
```

Recent demo values include:

| Metric | Value |
|---|---:|
| ROC-AUC | 0.7967 |
| F1 | 0.7024 |
| Precision | 0.8600 |
| Recall | 0.5936 |
| Total evaluated orders | 27,078 |

### Profit Prediction Model

The live API reports profit metrics through:

```text
GET /api/profit/metrics
```

Recent demo values include:

| Metric | Value |
|---|---:|
| RMSE | 61.6712 |
| MAE | 7.3617 |
| R2 | 0.8069 |
| Rows | 27,078 |
| Features | 37 |

Important modeling note: the profit model assumes `Order Item Profit Ratio` is a known pricing-margin feature at decision time. If a real deployment only knows margin after fulfillment, that feature must be removed and the profit model should be treated as retrospective analysis rather than pre-shipment prediction. See `reports/profit_model_design.md`.

---

## API Overview

| Method | Path | Access | Purpose |
|---|---|---|---|
| GET | `/api/metrics` | Public | Delay model KPI metrics |
| GET | `/api/predict` | Viewer / Manager / Engineer | De-identified delay risk list |
| POST | `/api/optimize` | Manager / Engineer | Budget-constrained shipping optimization |
| POST | `/api/login` | Public | Login and signed token issuance |
| GET | `/api/chart/monthly` | Public | Monthly delay trend data |
| GET | `/api/geojson/countries` | Public | Regional map data |
| GET | `/api/profit/metrics` | Public demo endpoint | Profit model metrics |
| GET | `/api/profit/feature-importance` | Public demo endpoint | Profit model feature importance |
| GET | `/api/profit/predictions` | Public demo endpoint | Profit prediction rows and residuals |
| GET / PUT | `/api/llm/settings` | Manager / Engineer | LLM provider/model/API key settings |

Security note: the current project keeps `X-Role` support for classroom/demo convenience, but production usage should rely on signed `Authorization: Bearer <token>` only.

---

## Demo Flow

Recommended final demo sequence:

1. Open `Dashboard 總覽` and explain business risk, model KPI, and threshold.
2. Show high-risk orders and explain that `p_late` is converted into decision input.
3. Switch to `Manager`, login, and run optimization with a budget.
4. Show selected upgrade orders, net benefit, and manager-facing rationale.
5. Open `AI 決策助理` to generate an executive explanation.
6. Open `收益預測` and show LightGBM profit metrics plus high-error samples.
7. Switch to `Engineer` and show diagnostics, retraining, regional map, and RBAC.
8. Close with how teacher feedback maps to implemented features.

Detailed script: `reports/demo_script.md`

Teacher feedback mapping: `reports/teacher_feedback_alignment.md`

---

## Quick Start

### Requirements

- Python 3.10+
- Conda, Miniconda, or venv

### Clone

```bash
git clone https://github.com/brightkhlin325-max/edis_logistics_optimization.git
cd edis_logistics_optimization
```

### Install

```bash
python -m venv .venv
source .venv/bin/activate       # macOS / Linux
# or .venv\Scripts\activate     # Windows PowerShell
pip install -r requirements.txt
```

### Prepare Data And Models

Place the DataCo CSV under:

```text
data/raw/DataCoSupplyChainDataset.csv
```

Then run the required pipelines as needed:

```bash
python core/auth.py
python core/data_pipeline.py
python core/model_pipeline.py
python core/profit_model_pipeline.py
```

The repository also includes demo-ready processed/model artifacts so the dashboard can run for presentation.

### Start Dashboard

```bash
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000/static/index.html
```

---

## Login

| Role | Username | Password |
|---|---|---|
| Manager | `admin` | `edis1234` |

Viewer mode does not require login. Engineer access is supported by the RBAC code path; use the seeded project credentials if available in the local auth database.

---

## Validation

Run tests with:

```bash
python -m pytest
```

If pytest is missing in an older local environment:

```bash
pip install -r requirements.txt
```

macOS note: XGBoost requires the OpenMP runtime. The provided `environment.yml`
includes `libomp` for Conda users. If you build a plain venv and see
`Library not loaded: @rpath/libomp.dylib`, install OpenMP through your system
package manager or use the Conda environment.

Recommended health checks:

```bash
curl 'http://127.0.0.1:8000/api/metrics?threshold=0.5'
curl 'http://127.0.0.1:8000/api/profit/metrics'
curl 'http://127.0.0.1:8000/static/index.html'
```

---

## Project Structure

```text
edis_logistics_optimization/
  app.py
  core/
    auth.py
    data_pipeline.py
    model_pipeline.py
    optimizer.py
    explainer.py
    profit_model_pipeline.py
    security_utils.py
  data/
    processed/
    raw/
  models/
  reports/
  scripts/
  static/
    components/
    app.js
    profit_prediction.js
    styles.css
  tests/
  requirements.txt
  environment.yml
```

---

## Final Presentation Positioning

The strongest version of the project is:

> A secure, explainable, role-aware decision dashboard that connects delay prediction, profit analysis, and logistics optimization into one management workflow.

Be explicit about assumptions, especially for profit prediction and role-header demo convenience. That honesty makes the project look more mature, not weaker.
