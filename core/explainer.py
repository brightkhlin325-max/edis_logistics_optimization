# -*- coding: utf-8 -*-
"""
Explanation layer for EDIS manager-facing logistics recommendations.

This module is LLM-ready: the current implementation builds deterministic
Chinese executive summaries locally. Later, `build_manager_narrative` can be
replaced with an external LLM call without changing the API contract.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterable

import pandas as pd

from risk_policy import risk_bucket_for_probability


DEFAULT_TOP_FACTORS = [
    "Shipping Mode_Standard Class",
    "Shipping Mode_Same Day",
    "Shipping Mode_First Class",
    "Days for shipment (scheduled)",
    "Type_TRANSFER",
]


@dataclass
class FactorImpact:
    feature: str
    label: str
    impact: str
    evidence: str
    weight: float
    # True：此因子帶有「本訂單實際值」（如運送模式、目的地區域）
    # False：此因子為「模型整體性因子」，資料中無本訂單的逐筆數值（如承諾天數、交易型態）
    order_specific: bool = False

    def to_dict(self) -> dict:
        return {
            "feature": self.feature,
            "label": self.label,
            "impact": self.impact,
            "evidence": self.evidence,
            "weight": round(float(self.weight), 4),
            "order_specific": bool(self.order_specific),
        }


class ManagerExplainer:
    """
    Produces LIME-style top-X factors and manager-facing explanations.

    The project currently ships static predictions and global feature
    importance, but not the original per-order feature matrix required by true
    LIME perturbation. This class uses the same explanation contract and a
    LIME-style attribution fallback based on model feature importance plus
    visible order fields.
    """

    def __init__(self, predictions: pd.DataFrame, metrics: dict | None = None):
        self.predictions = predictions.copy()
        self.metrics = metrics or {}
        self.feature_importance = self.metrics.get("feature_importance", {}) or {}
        
        # 效能優化：預先計算全球與各區域平均延遲率，避免對每筆訂單重複執行 O(N) 字串掃描
        self.global_mean = float(self.predictions["p_late"].mean()) if "p_late" in self.predictions.columns else 0.0
        self.region_means = {}
        if "order_region" in self.predictions.columns and "p_late" in self.predictions.columns:
            try:
                self.region_means = self.predictions.groupby(
                    self.predictions["order_region"].astype(str).str.strip()
                )["p_late"].mean().to_dict()
            except Exception:
                pass

    def explain_order(self, order: dict) -> dict:
        p_late = float(order.get("p_late", 0.0))
        expected_penalty = float(order.get("expected_penalty", p_late * 250.0))
        shipping_base_costs = {
            "Standard Class": 50.0,
            "Second Class": 80.0,
            "First Class": 120.0,
            "Same Day": 180.0,
        }
        region_multipliers = {
            "Western Europe": 1.1,
            "Central America": 0.9,
            "South America": 0.95,
            "Northern Europe": 1.25,
            "Eastern Europe": 1.05,
            "North America": 1.15,
            "East Asia": 1.2,
            "Oceania": 1.3,
        }
        mode_val = order.get("shipping_mode", "Standard Class")
        region_val = order.get("order_region", "Unknown")
        base = shipping_base_costs.get(mode_val, 80.0)
        mult = region_multipliers.get(region_val, 1.0)
        default_dynamic_cost = round(base * mult, 2)
        
        upgrade_cost = float(order.get("upgrade_cost", default_dynamic_cost))
        net_benefit = float(order.get("net_benefit", expected_penalty - upgrade_cost))
        risk_bucket = str(order.get("risk_bucket", self._risk_bucket(p_late)))
        shipping_mode = str(order.get("shipping_mode", "Unknown"))
        order_region = str(order.get("order_region", "Unknown")).strip()

        factors = self._build_factor_impacts(
            shipping_mode=shipping_mode,
            order_region=order_region,
            p_late=p_late,
        )
        action = self._recommended_action(risk_bucket, net_benefit)
        narrative = self._build_manager_narrative(
            risk_bucket=risk_bucket,
            p_late=p_late,
            shipping_mode=shipping_mode,
            order_region=order_region,
            expected_penalty=expected_penalty,
            upgrade_cost=upgrade_cost,
            net_benefit=net_benefit,
            action=action,
            factors=factors,
        )

        return {
            "order_id_hash": order.get("order_id_hash"),
            "risk_bucket": risk_bucket,
            "p_late": round(p_late, 4),
            "recommended_action": action,
            "expected_penalty": round(expected_penalty, 2),
            "upgrade_cost": round(upgrade_cost, 2),
            "net_benefit": round(net_benefit, 2),
            "top_x_factors": [f.to_dict() for f in factors],
            "manager_summary": narrative,
            "explanation_method": "LIME-style local attribution using feature importance; ready to swap with true LIME when test feature matrix is available.",
        }

    def summarize_optimization(self, optimization_result: dict) -> dict:
        selected_orders = optimization_result.get("selected_orders", [])
        selected_count = int(optimization_result.get("selected_count", len(selected_orders)))
        budget = float(optimization_result.get("budget", 0.0))
        total_cost = float(optimization_result.get("total_cost", 0.0))
        expected_total_saving = float(optimization_result.get("expected_total_saving", 0.0))
        explained_orders = [
            self.explain_order(self._hydrate_order(order))
            for order in selected_orders[:5]
        ]
        top_action = self._top_action_from_orders(explained_orders)
        budget_usage = (total_cost / budget * 100.0) if budget else 0.0

        summary = (
            f"建議主管核准本批調度：在預算 USD ${budget:,.0f} 下，"
            f"系統挑選出 {selected_count} 筆建議升級訂單，"
            f"預估淨效益 USD ${expected_total_saving:,.0f}，預算使用率 {budget_usage:.0f}%。"
            f"主要調整方向是：{top_action}"
        )

        return {
            "headline": summary,
            "recommended_policy": top_action,
            "budget_usage_pct": round(budget_usage, 2),
            "sample_order_explanations": explained_orders,
            "llm_ready_prompt": self._build_llm_prompt(optimization_result, explained_orders),
        }

    def _hydrate_order(self, order: dict) -> dict:
        order_id = order.get("order_id_hash")
        hydrated = dict(order)
        if order_id and "order_id_hash" in self.predictions.columns:
            rows = self.predictions[self.predictions["order_id_hash"].astype(str) == str(order_id)]
            if not rows.empty:
                hydrated = {**rows.iloc[0].to_dict(), **hydrated}
        return hydrated

    def _build_factor_impacts(self, shipping_mode: str, order_region: str, p_late: float) -> list[FactorImpact]:
        importances = self.feature_importance or {name: 0.01 for name in DEFAULT_TOP_FACTORS}
        region_avg = self._region_average(order_region)
        factors: list[FactorImpact] = []

        for feature, weight in sorted(importances.items(), key=lambda item: item[1], reverse=True):
            impact = self._feature_impact(feature, shipping_mode, order_region, region_avg, p_late)
            if impact:
                factors.append(FactorImpact(feature=feature, weight=weight, **impact))
            if len(factors) >= 3:
                break

        if not any(f.label == "運送模式" for f in factors) and shipping_mode != "Unknown":
            feature = f"Shipping Mode_{shipping_mode}"
            factors.append(FactorImpact(
                feature=feature,
                label="運送模式",
                impact="raises risk" if shipping_mode == "Standard Class" else "context",
                evidence=f"此訂單實際使用 {shipping_mode}，需搭配延遲機率與淨效益判斷是否升級",
                weight=float(importances.get(feature, 0.0)),
                order_specific=True,
            ))
        if not any("region" in f.feature.lower() or "Order Region" in f.feature for f in factors):
            factors.append(FactorImpact(
                feature="order_region",
                label="目的地區域",
                impact="raises risk" if region_avg >= 0.55 else "neutral",
                evidence=f"{order_region or 'Unknown'} 平均延遲機率約 {region_avg:.0%}",
                weight=0.0,
                order_specific=True,
            ))
        return factors[:4]

    def _feature_impact(
        self,
        feature: str,
        shipping_mode: str,
        order_region: str,
        region_avg: float,
        p_late: float,
    ) -> dict | None:
        if feature.startswith("Shipping Mode_"):
            mode = feature.split("_", 1)[1]
            if mode != shipping_mode:
                return None
            impact = "raises risk" if mode == "Standard Class" else "context"
            evidence = f"此訂單實際使用 {shipping_mode}，為可能導致延遲的主要因子之一"
            return {"label": "運送模式", "impact": impact, "evidence": evidence,
                    "order_specific": True}

        if feature == "Days for shipment (scheduled)":
            return {
                "label": "承諾運送天數",
                "impact": "raises risk" if p_late >= 0.7 else "context",
                # 預測資料未提供每筆訂單的實際承諾天數，故此處為模型整體性因子，不偽裝成本訂單數值
                "evidence": "承諾時效越緊越容易延遲（模型整體性因子，預測資料未含本訂單實際天數）",
                "order_specific": False,
            }

        if feature.startswith("Type_"):
            return {
                "label": "訂單交易型態",
                "impact": "context",
                "evidence": f"{feature.replace('_', ' ')} 對延遲風險有次要影響（模型整體性因子）",
                "order_specific": False,
            }

        if "Region" in feature or "Country" in feature:
            return {
                "label": "目的地區域",
                "impact": "raises risk" if region_avg >= 0.55 else "neutral",
                "evidence": f"{order_region} 平均延遲機率約 {region_avg:.0%}",
                "order_specific": True,
            }

        return {
            "label": feature.replace("_", " "),
            "impact": "context",
            "evidence": "此特徵在模型整體重要性中排名靠前（模型整體性因子）",
            "order_specific": False,
        }

    def _region_average(self, order_region: str) -> float:
        if not order_region:
            return self.global_mean
        return self.region_means.get(order_region.strip(), self.global_mean)

    def _recommended_action(self, risk_bucket: str, net_benefit: float) -> str:
        if risk_bucket == "High" and net_benefit > 0:
            return "升級運送並列入優先調度"
        if risk_bucket == "Medium" and net_benefit > 0:
            return "保留升級候選，視當日預算與倉配容量決定"
        return "維持原運送方式並持續監控"

    def _build_manager_narrative(
        self,
        risk_bucket: str,
        p_late: float,
        shipping_mode: str,
        order_region: str,
        expected_penalty: float,
        upgrade_cost: float,
        net_benefit: float,
        action: str,
        factors: Iterable[FactorImpact],
    ) -> str:
        factor_text = "、".join(f"{f.label}（{f.evidence}）" for f in factors)
        return (
            f"此訂單延遲風險為 {risk_bucket.upper()}（p_late={p_late:.1%}），"
            f"目前運送模式為 {shipping_mode}，目的地為 {order_region or 'Unknown'}。"
            f"若升級運送，原罰款 USD ${expected_penalty:,.0f}，"
            f"扣除升級成本 USD ${upgrade_cost:,.0f} 後，可省下 USD ${net_benefit:,.0f}的懲罰成本(淨效益)。"
            f"可能導致延遲的主要因子為：{factor_text}。建議：{action}。"
        )

    def _top_action_from_orders(self, explanations: list[dict]) -> str:
        if not explanations:
            return "目前沒有需要升級的訂單，維持監控即可。"
        high_count = sum(1 for e in explanations if e.get("risk_bucket") == "High")
        common_modes = [
            factor["evidence"]
            for e in explanations
            for factor in e.get("top_x_factors", [])
            if factor.get("label") == "運送模式"
        ]
        mode_hint = common_modes[0] if common_modes else "優先處理高風險與正淨效益訂單"
        return f"優先升級高風險且淨效益為正的訂單；樣本中 {high_count} 筆為 High risk，{mode_hint}。"

    def _build_llm_prompt(self, optimization_result: dict, explanations: list[dict]) -> str:
        compact = {
            "optimization": {
                "budget": optimization_result.get("budget"),
                "selected_count": optimization_result.get("selected_count"),
                "total_cost": optimization_result.get("total_cost"),
                "expected_total_saving": optimization_result.get("expected_total_saving"),
            },
            "sample_explanations": explanations[:3],
        }
        return (
            "請用物流主管能理解的語氣，根據以下最佳化調度結果與訂單風險因子，"
            "產出三句決策建議、風險原因與預算說明："
            f"{json.dumps(compact, ensure_ascii=False, default=self._json_default)}"
        )

    def _risk_bucket(self, p_late: float) -> str:
        return risk_bucket_for_probability(p_late)

    def _json_default(self, value):
        if hasattr(value, "item"):
            return value.item()
        return str(value)
