"""
tests/test_explainer.py
ManagerExplainer（LIME-style 歸因）單元測試。

涵蓋本次修正：
  - issue 1：敘述改用「可能導致延遲的主要因子」
  - issue 2A：order_specific 誠實標記
      有本訂單實際值（運送模式、目的地區域）→ True
      模型整體性因子（承諾天數、交易型態）→ False
"""

import pandas as pd

from explainer import ManagerExplainer


def _explainer():
    df = pd.DataFrame({
        "p_late": [0.75, 0.4],
        "order_region": ["South Asia", "Western Europe"],
        "shipping_mode": ["Second Class", "First Class"],
    })
    importances = {
        "Shipping Mode_Second Class": 0.30,
        "Days for shipment (scheduled)": 0.20,
        "Type_TRANSFER": 0.10,
    }
    return ManagerExplainer(df, {"feature_importance": importances})


def _factor(factors, label):
    return next((f for f in factors if f["label"] == label), None)


def test_narrative_uses_new_wording():
    r = _explainer().explain_order({
        "p_late": 0.75, "shipping_mode": "Second Class",
        "order_region": "South Asia", "expected_penalty": 187, "upgrade_cost": 80,
    })
    assert "可能導致延遲的主要因子" in r["manager_summary"]
    assert "主要 X 因子" not in r["manager_summary"]
    assert "此訂單延遲風險為 HIGH（p_late=75.0%）" in r["manager_summary"]
    assert "若升級運送，原罰款 USD $187" in r["manager_summary"]
    assert "扣除升級成本 USD $80 後，可省下 USD $107的懲罰成本(淨效益)" in r["manager_summary"]
    assert "預期可避免罰款" not in r["manager_summary"]


def test_order_specific_flags_are_honest():
    r = _explainer().explain_order({
        "p_late": 0.75, "shipping_mode": "Second Class",
        "order_region": "South Asia", "expected_penalty": 187, "upgrade_cost": 80,
    })
    factors = r["top_x_factors"]
    # 每個因子都必須帶 order_specific 欄位
    assert all("order_specific" in f for f in factors)

    mode = _factor(factors, "運送模式")
    region = _factor(factors, "目的地區域")
    assert mode is not None and mode["order_specific"] is True
    assert region is not None and region["order_specific"] is True
    # 區域因子應帶本訂單實際區域名稱
    assert "South Asia" in region["evidence"]

    days = _factor(factors, "承諾運送天數")
    if days is not None:
        assert days["order_specific"] is False
        assert "模型整體性因子" in days["evidence"]

    txn = _factor(factors, "訂單交易型態")
    if txn is not None:
        assert txn["order_specific"] is False


def test_explainer_uses_shared_risk_boundaries():
    explainer = _explainer()
    assert explainer._risk_bucket(0.2999) == "Low"
    assert explainer._risk_bucket(0.30) == "Medium"
    assert explainer._risk_bucket(0.6999) == "Medium"
    assert explainer._risk_bucket(0.70) == "High"
