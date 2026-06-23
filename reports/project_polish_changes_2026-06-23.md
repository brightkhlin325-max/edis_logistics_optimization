# Project Polish Changes — 2026-06-23

Branch: `codex/project-polish-docs`

## Goal

Improve the final-project readiness of EDIS / SLIDE based on six identified gaps:

1. README and presentation story were behind the current feature set.
2. Demo flow needed one clear narrative.
3. Profit prediction needed an explicit modeling assumption.
4. Test dependencies needed to support `python -m pytest`.
5. RBAC documentation needed a production-security caveat.
6. Teacher feedback needed a direct implementation mapping.

## Files Changed

| File | Change |
|---|---|
| `README.md` | Rewritten to describe the current SLIDE/EDIS system, including XGBoost delay prediction, PuLP optimization, LightGBM profit prediction, LLM settings, RBAC roles, demo flow, and validation commands. |
| `reports/demo_script.md` | Added a step-by-step final demo script from dashboard KPI to optimization, AI assistant, profit prediction, engineer diagnostics, and teacher feedback close. |
| `reports/teacher_feedback_alignment.md` | Added a table mapping teacher feedback themes to implemented features and where to show them. |
| `reports/profit_model_design.md` | Clarified that `Order Item Profit Ratio` is only valid if known at decision time and added current demo metrics. |
| `PROFIT_PREIDCT_PLAN.md` | Updated the leakage discussion so margin is treated as a conditional assumption instead of always discarded. |
| `reports/api_contract.md` | Added Engineer role, bearer-token preference, production hardening guidance, and profit prediction endpoint documentation. |
| `requirements.txt` | Added `pytest>=8.0` so test commands are reproducible. |
| `environment.yml` | Added `pytest>=8.0` and Conda `libomp` so macOS XGBoost/LightGBM tests have an OpenMP runtime. |

## Windows Team Update

The team primarily uses Windows, so this branch now documents Windows first:

- `setup_and_run.bat` is the recommended team launcher.
- README includes PowerShell/Conda commands and venv fallback commands.
- README documents the PowerShell execution policy fix for venv activation.
- README recommends Conda when compiled ML packages such as XGBoost/LightGBM fail in plain venv.
- `environment.yml` keeps `libomp` as part of the shared Conda environment; it is harmless for Windows users and fixes OpenMP runtime availability for teammates on macOS.

## Validation Performed

- Confirmed latest branch was based on current `main`.
- Confirmed app health before changes with:
  - `/static/index.html` returning 200
  - `/api/metrics?threshold=0.5` returning 200
  - `/api/profit/metrics` returning 200
- Installed pytest into the local `.venv` and ran `python -m pytest`.
- Result: 27 passed, 1 skipped, 1 failed.
- The remaining failure is environmental: XGBoost cannot load `libxgboost.dylib` because macOS OpenMP runtime `libomp.dylib` is missing from this machine. This branch adds `libomp` to `environment.yml` and documents the fix in `README.md`.

## Notes For Reviewers

- This branch intentionally changes documentation and environment metadata only.
- It does not modify runtime business logic.
- It does not stage unrelated local files such as `UI 頁面修改.docx`, `EDIS_UI_PAGE_SPEC_INTEGRATED.md`, local DB backups, or implementation plan drafts.
