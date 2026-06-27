"""
tests/test_optimizer.py
ShippingOptimizer（0/1 整數規劃最佳化引擎）單元測試。

涵蓋：
  - 空候選 → 安全回傳
  - 預算限制下的「已知最佳解」驗證（核心商業邏輯）
  - 預算充足時選入所有正 ROI 訂單
  - run() 全流程：候選篩選（門檻 + ROI > 0）
  - OptimizationResult.to_dict() 結構與四捨五入
"""

import pandas as pd
import pytest

from optimizer import ShippingOptimizer, OptimizationResult


def _candidates(rows):
    """建立 optimize() 所需的候選 DataFrame（含 net_benefit 欄位）。"""
    df = pd.DataFrame(rows)
    df["net_benefit"] = df["expected_penalty"] - df["upgrade_cost"]
    return df


def test_empty_candidates_returns_safe_result():
    opt = ShippingOptimizer(budget=5000)
    result = opt.optimize(pd.DataFrame())
    assert isinstance(result, OptimizationResult)
    assert result.selected_count == 0
    assert result.total_cost == 0.0
    assert result.expected_total_saving == 0.0
    assert result.solver == "none"


def test_budget_constraint_picks_optimal_subset():
    """預算只夠 2 筆時，須挑出淨效益最大的組合（A+B），且不超預算。"""
    cands = _candidates([
        {"p_late": 0.9, "upgrade_cost": 100.0, "expected_penalty": 300.0},  # A net 200
        {"p_late": 0.8, "upgrade_cost": 100.0, "expected_penalty": 250.0},  # B net 150
        {"p_late": 0.5, "upgrade_cost": 100.0, "expected_penalty": 120.0},  # C net 20
    ])
    opt = ShippingOptimizer(budget=250)  # 容得下 2 筆（200），容不下 3 筆（300）
    result = opt.optimize(cands)

    assert result.selected_count == 2
    assert result.total_cost == 200.0
    assert result.total_cost <= opt.budget
    # 最佳組合 A+B 的淨效益 = 200 + 150 = 350（勝過含 C 的任何組合）
    assert result.expected_total_saving == pytest.approx(350.0)
    assert result.expected_total_penalty_avoided == pytest.approx(550.0)
    assert result.solver == "PuLP MILP"


def test_ample_budget_selects_all_positive_roi():
    cands = _candidates([
        {"p_late": 0.9, "upgrade_cost": 100.0, "expected_penalty": 300.0},
        {"p_late": 0.8, "upgrade_cost": 100.0, "expected_penalty": 250.0},
    ])
    opt = ShippingOptimizer(budget=10_000)
    result = opt.optimize(cands)
    assert result.selected_count == 2
    assert result.total_cost == 200.0


def test_run_filters_below_threshold_and_negative_roi():
    """run() 應只保留 p_late >= 門檻 且 net_benefit > 0 的訂單。"""
    raw = pd.DataFrame({
        "p_late": [0.05, 0.9, 0.8],           # 第一筆低於門檻會被濾掉
        "upgrade_cost": [80.0, 80.0, 500.0],  # 第三筆成本過高 → ROI 為負，被濾掉
    })
    # 用 delay_penalty 讓 expected_penalty = p_late * 250
    opt = ShippingOptimizer(budget=10_000, risk_threshold=0.3,
                            delay_penalty=250.0, upgrade_cost=80.0)
    result = opt.run(raw, save_results=False)
    # 只有第二筆（p_late 0.9：penalty 225 > cost 80）會通過並被選入
    assert result.selected_count == 1
    assert result.total_orders_considered == 1


def test_complete_fields_relabels_legacy_risk_bucket_by_probability():
    raw = pd.DataFrame({
        "p_late": [0.2999, 0.30, 0.6999, 0.70],
        "risk_bucket": ["High", "High", "Low", "Low"],
    })
    completed = ShippingOptimizer()._complete_fields(raw)
    assert completed["risk_bucket"].tolist() == ["Low", "Medium", "Medium", "High"]


def test_candidate_cap_keeps_highest_individual_net_benefits():
    raw = pd.DataFrame({
        "p_late": [0.9, 0.9, 0.9],
        "expected_penalty": [300.0, 250.0, 200.0],
        "upgrade_cost": [100.0, 100.0, 100.0],
    })
    candidates = ShippingOptimizer(
        risk_threshold=0.3,
        max_candidates=2,
    )._filter_candidates(raw)
    assert candidates["net_benefit"].tolist() == [200.0, 150.0]


def test_selected_orders_are_reported_by_highest_net_benefit():
    cands = _candidates([
        {"order_id_hash": "low", "p_late": 0.95, "upgrade_cost": 100.0, "expected_penalty": 130.0},
        {"order_id_hash": "high", "p_late": 0.80, "upgrade_cost": 100.0, "expected_penalty": 300.0},
        {"order_id_hash": "mid", "p_late": 0.90, "upgrade_cost": 100.0, "expected_penalty": 250.0},
    ])
    result = ShippingOptimizer(budget=10_000).optimize(cands)

    assert [order["order_id_hash"] for order in result.selected_orders] == ["high", "mid", "low"]
    assert [order["net_benefit"] for order in result.selected_orders] == [200.0, 150.0, 30.0]


def test_to_dict_structure_and_rounding():
    cands = _candidates([
        {"p_late": 0.91234, "upgrade_cost": 100.005, "expected_penalty": 300.567},
    ])
    opt = ShippingOptimizer(budget=10_000)
    d = opt.optimize(cands).to_dict()
    for key in ("budget", "total_cost", "selected_count",
                "expected_total_saving", "solver", "selected_orders"):
        assert key in d
    # to_dict 對金額做 2 位四捨五入
    assert d["total_cost"] == round(d["total_cost"], 2)
    assert isinstance(d["selected_orders"], list)
