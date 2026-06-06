"""
Optimization module for EDIS logistics upgrade decisions.

This file is intentionally a lightweight scaffold. The detailed optimization
logic can be implemented after the model pipeline produces predictions.csv.
"""

from dataclasses import dataclass
from typing import Iterable, List


@dataclass
class OrderDecisionInput:
    """Input data needed to decide whether an order should be upgraded."""

    order_id_hash: str
    p_late: float
    expected_penalty: float
    upgrade_cost: float


@dataclass
class OrderDecisionOutput:
    """Optimization result for a selected order."""

    order_id_hash: str
    p_late: float
    upgrade_cost: float
    expected_saving: float
    decision: str


def calculate_expected_saving(order: OrderDecisionInput) -> float:
    """
    Estimate the net benefit of upgrading one order.

    Formula:
        expected_saving = p_late * expected_penalty - upgrade_cost
    """
    return order.p_late * order.expected_penalty - order.upgrade_cost


def optimize_shipments(
    orders: Iterable[OrderDecisionInput],
    budget: float,
) -> List[OrderDecisionOutput]:
    """
    Select orders to upgrade under a fixed budget.

    MVP plan:
    1. Calculate expected saving for each order.
    2. Keep only orders with positive expected saving.
    3. Select the best combination within the budget.

    The first implementation can use a greedy approach. Later, this can be
    replaced by a 0/1 integer programming solver such as PuLP.
    """
    selected_orders: List[OrderDecisionOutput] = []

    # TODO: Implement greedy or integer programming optimization.
    # For now, this scaffold returns an empty recommendation list.
    return selected_orders
