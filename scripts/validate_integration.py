"""
Small integration checker for the local EDIS FastAPI server.

Run after starting the app:
    uvicorn app:app --reload --port 8000

Then:
    python scripts/validate_integration.py
"""

import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BASE_URL = "http://localhost:8000"


def request_json(path, method="GET", headers=None, body=None):
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")

    req = Request(
        f"{BASE_URL}{path}",
        data=data,
        method=method,
        headers=headers or {},
    )
    with urlopen(req, timeout=10) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def expect(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def main():
    try:
        status, metrics = request_json("/api/metrics")
        expect(status == 200, "GET /api/metrics returns 200")
        expect("roc_auc" in metrics, "metrics includes roc_auc")

        status, predictions = request_json(
            "/api/predict",
            headers={"X-Role": "Viewer"},
        )
        expect(status == 200, "GET /api/predict as Viewer returns 200")
        expect("data" in predictions, "predict response includes data")

        try:
            request_json(
                "/api/optimize",
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "X-Role": "Viewer",
                },
                body={"budget": 5000, "upgrade_cost": 80, "delay_penalty": 250, "max_candidates": 500},
            )
            raise AssertionError("Viewer optimize request should have failed")
        except HTTPError as exc:
            expect(exc.code == 403, "POST /api/optimize as Viewer returns 403")

        status, result = request_json(
            "/api/optimize",
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Role": "Logistics_Manager",
            },
            body={"budget": 5000, "upgrade_cost": 80, "delay_penalty": 250, "max_candidates": 500},
        )
        expect(status == 200, "POST /api/optimize as Logistics_Manager returns 200")
        expect("selected_orders" in result, "optimize response includes selected_orders")
        expect("solver" in result, "optimize response includes solver")
        if result["selected_orders"]:
            first_order = result["selected_orders"][0]
            expect("net_benefit" in first_order, "selected order includes net_benefit")
            expect("reason" in first_order, "selected order includes reason")

    except URLError as exc:
        print(f"ERROR: Cannot reach {BASE_URL}. Start the API server first.")
        print(exc)
        return 1
    except AssertionError as exc:
        print(f"FAIL: {exc}")
        return 1

    print("Integration check completed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
