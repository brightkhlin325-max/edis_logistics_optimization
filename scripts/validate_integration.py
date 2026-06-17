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


def login(username, password):
    status, payload = request_json(
        "/api/login",
        method="POST",
        headers={"Content-Type": "application/json"},
        body={"username": username, "password": password},
    )
    expect(status == 200, f"POST /api/login as {username} returns 200")
    expect(payload.get("token"), f"login as {username} returns token")
    expect(payload.get("session_id"), f"login as {username} returns session_id")
    return payload


def auth_headers(token, session_id=None, content_type=False):
    headers = {"Authorization": f"Bearer {token}"}
    if session_id:
        headers["X-Session-ID"] = session_id
    if content_type:
        headers["Content-Type"] = "application/json"
    return headers


def main():
    try:
        viewer_login = login("viewer", "view1234")
        manager_login = login("admin", "edis1234")
        viewer_headers = auth_headers(
            viewer_login["token"],
            viewer_login.get("session_id"),
        )
        manager_headers = auth_headers(
            manager_login["token"],
            manager_login.get("session_id"),
        )

        status, metrics = request_json("/api/metrics")
        expect(status == 200, "GET /api/metrics returns 200")
        expect("roc_auc" in metrics, "metrics includes roc_auc")

        status, predictions = request_json(
            "/api/predict",
            headers=viewer_headers,
        )
        expect(status == 200, "GET /api/predict with Viewer token returns 200")
        expect(predictions.get("role") == "Viewer", "Viewer token resolves Viewer role")
        expect("data" in predictions, "predict response includes data")
        first_prediction = (predictions.get("data") or [{}])[0]

        try:
            request_json(
                "/api/optimize",
                method="POST",
                headers=auth_headers(
                    viewer_login["token"],
                    viewer_login.get("session_id"),
                    content_type=True,
                ),
                body={"budget": 5000, "upgrade_cost": 80, "delay_penalty": 250, "max_candidates": 500},
            )
            raise AssertionError("Viewer optimize request should have failed")
        except HTTPError as exc:
            expect(exc.code == 403, "POST /api/optimize with Viewer token returns 403")

        status, result = request_json(
            "/api/optimize",
            method="POST",
            headers=auth_headers(
                manager_login["token"],
                manager_login.get("session_id"),
                content_type=True,
            ),
            body={"budget": 5000, "upgrade_cost": 80, "delay_penalty": 250, "max_candidates": 500},
        )
        expect(status == 200, "POST /api/optimize with Manager token returns 200")
        expect(result.get("role") == "Logistics_Manager", "Manager token resolves Logistics_Manager role")
        expect("selected_orders" in result, "optimize response includes selected_orders")
        expect("solver" in result, "optimize response includes solver")
        expect("manager_analysis" in result, "optimize response includes manager_analysis")
        expect(
            "sample_order_explanations" in result["manager_analysis"],
            "manager_analysis includes sample_order_explanations",
        )
        if result["selected_orders"]:
            first_order = result["selected_orders"][0]
            expect("net_benefit" in first_order, "selected order includes net_benefit")
            expect("reason" in first_order, "selected order includes reason")

        try:
            request_json(
                "/api/llm/manager-brief",
                method="POST",
                headers=auth_headers(
                    viewer_login["token"],
                    viewer_login.get("session_id"),
                    content_type=True,
                ),
                body={"budget": 5000, "upgrade_cost": 80, "delay_penalty": 250},
            )
            raise AssertionError("Viewer LLM brief request should have failed")
        except HTTPError as exc:
            expect(exc.code == 403, "POST /api/llm/manager-brief with Viewer token returns 403")

        status, brief = request_json(
            "/api/llm/manager-brief",
            method="POST",
            headers=auth_headers(
                manager_login["token"],
                manager_login.get("session_id"),
                content_type=True,
            ),
            body={"budget": 5000, "upgrade_cost": 80, "delay_penalty": 250},
        )
        expect(status == 200, "POST /api/llm/manager-brief with Manager token returns 200")
        expect("brief_text" in brief, "LLM brief response includes brief_text")
        expect(brief["data_boundary"]["de_identified_only"] is True, "LLM brief uses de-identified boundary")
        expect("safe_payload" in brief, "LLM brief response includes safe_payload")

        if first_prediction.get("order_id_hash"):
            status, explanation = request_json(
                f"/api/explain/{first_prediction['order_id_hash']}",
                headers=viewer_headers,
            )
            expect(status == 200, "GET /api/explain/{order_id_hash} returns 200")
            expect("top_x_factors" in explanation, "explanation includes top_x_factors")
            expect("manager_summary" in explanation, "explanation includes manager_summary")

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
