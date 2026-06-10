"""
optimizer.py
EDIS — DataCo 物流延遲預測與最佳化調度系統

負責人：Danny（協助撰寫：Lisa）
功能：0/1 整數規劃最佳化引擎（預算限制下最大化預期效益）
  - 讀取 predictions.csv（model_pipeline.py 輸出）
  - 在給定預算下決定哪些訂單值得升級運送
  - 輸出 optimization_result.csv 與 JSON 格式結果

最佳化問題：
  決策變數：x_i ∈ {0, 1}（1 = 升級此訂單）
  目標：最大化 Σ (p_late_i × penalty_i - upgrade_cost_i) × x_i
  限制：Σ (upgrade_cost_i × x_i) ≤ budget
"""

import os
import json
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional

try:
    import pulp
    PULP_AVAILABLE = True
except ImportError:
    PULP_AVAILABLE = False


# ── 常數 ──────────────────────────────────────────────────────────────────────

DEFAULT_BUDGET = 5_000.0
DEFAULT_UPGRADE_COST = 80.0
DEFAULT_DELAY_PENALTY = 250.0
DEFAULT_RISK_THRESHOLD = 0.3   # 只考慮延遲機率 ≥ 此值的訂單
DEFAULT_MAX_CANDIDATES = 500   # PuLP demo 保持互動速度的候選上限


# ── 結果資料結構 ───────────────────────────────────────────────────────────────

@dataclass
class OptimizationResult:
    budget: float
    total_cost: float
    total_orders_considered: int
    selected_count: int
    expected_total_saving: float
    expected_total_penalty_avoided: float = 0.0
    solver: str = "PuLP MILP"
    selected_orders: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "budget": self.budget,
            "total_cost": round(self.total_cost, 2),
            "total_orders_considered": self.total_orders_considered,
            "selected_count": self.selected_count,
            "expected_total_saving": round(self.expected_total_saving, 2),
            "expected_total_penalty_avoided": round(self.expected_total_penalty_avoided, 2),
            "solver": self.solver,
            "selected_orders": self.selected_orders,
        }


# ── 最佳化引擎主類別 ──────────────────────────────────────────────────────────

class ShippingOptimizer:
    """
    在預算限制下，選出最值得升級運送的訂單組合。

    使用範例：
        optimizer = ShippingOptimizer(budget=5000)
        result = optimizer.run(
            predictions_path="data/processed/predictions.csv",
            output_dir="data/processed",
        )
        print(result.to_dict())
    """

    def __init__(
        self,
        budget: float = DEFAULT_BUDGET,
        upgrade_cost: float = DEFAULT_UPGRADE_COST,
        delay_penalty: float = DEFAULT_DELAY_PENALTY,
        risk_threshold: float = DEFAULT_RISK_THRESHOLD,
        max_candidates: int = DEFAULT_MAX_CANDIDATES,
    ):
        """
        Parameters
        ----------
        budget : float
            物流預算上限（元）
        upgrade_cost : float
            每筆訂單升級費用（元）
        delay_penalty : float
            每筆訂單延遲罰款估計（元）
        risk_threshold : float
            只對延遲機率高於此值的訂單進行最佳化決策
        max_candidates : int
            進入 PuLP MILP 求解器的候選訂單上限，避免 demo API 長時間卡住
        """
        self.budget = budget
        self.upgrade_cost = upgrade_cost
        self.delay_penalty = delay_penalty
        self.risk_threshold = risk_threshold
        self.max_candidates = max_candidates

    # ── 公開方法 ───────────────────────────────────────────────────────────

    def run(
        self,
        predictions_path: str,
        output_dir: str = "data/processed",
    ) -> OptimizationResult:
        """
        完整最佳化流程：載入預測 → 求解 → 輸出

        Parameters
        ----------
        predictions_path : str
            model_pipeline.py 輸出的 predictions.csv 路徑
        output_dir : str
            結果輸出目錄

        Returns
        -------
        OptimizationResult
        """
        os.makedirs(output_dir, exist_ok=True)

        print("=" * 60)
        print("EDIS ShippingOptimizer — 開始執行")
        print(f"  預算：NT$ {self.budget:,.0f}")
        print("=" * 60)

        # 載入預測資料
        df = self._load_predictions(predictions_path)

        # 篩選候選訂單
        candidates = self._filter_candidates(df)

        # 求解
        result = self.optimize(candidates)

        # 儲存結果
        self._save_results(result, output_dir)

        print(f"\n✓ 最佳化完成：選出 {result.selected_count} 筆訂單升級")
        print(f"  總升級成本：NT$ {result.total_cost:,.0f}（預算：{self.budget:,.0f}）")
        print(f"  預期淨效益：NT$ {result.expected_total_saving:,.0f}")
        print("=" * 60)

        return result

    def optimize(self, candidates: pd.DataFrame) -> OptimizationResult:
        """
        核心最佳化求解器。

        求解策略：
        使用 PuLP 求解 0/1 MILP。PuLP 未安裝時直接報錯。

        Parameters
        ----------
        candidates : pd.DataFrame
            候選訂單，必須包含 p_late、upgrade_cost、expected_penalty

        Returns
        -------
        OptimizationResult
        """
        if len(candidates) == 0:
            print("  警告：無候選訂單。")
            return OptimizationResult(
                budget=self.budget,
                total_cost=0.0,
                total_orders_considered=0,
                selected_count=0,
                expected_total_saving=0.0,
                expected_total_penalty_avoided=0.0,
                solver="none",
            )

        if not PULP_AVAILABLE:
            raise RuntimeError("PuLP 未安裝，無法執行 MILP。請先執行：pip install pulp")

        print("  求解器：PuLP MILP（0/1 整數規劃）")
        selected_indices = self._solve_with_pulp(candidates)
        solver = "PuLP MILP"

        return self._build_result(candidates, selected_indices, solver)

    # ── 私有方法 ───────────────────────────────────────────────────────────

    def _load_predictions(self, path: str) -> pd.DataFrame:
        """載入 predictions.csv 並補上缺失欄位的預設值。"""
        print(f"\n[Step 1] 載入預測結果：{path}")
        df = pd.read_csv(path)
        print(f"  共 {len(df):,} 筆預測")

        # 補全必要欄位
        if "upgrade_cost" not in df.columns:
            df["upgrade_cost"] = self.upgrade_cost
        if "expected_penalty" not in df.columns:
            df["expected_penalty"] = df["p_late"] * self.delay_penalty
        if "order_id_hash" in df.columns:
            before = len(df)
            df = (
                df.sort_values("p_late", ascending=False)
                .drop_duplicates(subset=["order_id_hash"], keep="first")
                .reset_index(drop=True)
            )
            removed = before - len(df)
            if removed:
                print(f"  已移除重複訂單：{removed:,} 筆")

        return df

    def _filter_candidates(self, df: pd.DataFrame) -> pd.DataFrame:
        """只保留延遲機率超過門檻的訂單作為候選。"""
        candidates = df[df["p_late"] >= self.risk_threshold].copy()
        print(f"\n[Step 2] 篩選候選訂單（p_late >= {self.risk_threshold}）：{len(candidates):,} 筆")

        candidates["net_benefit"] = candidates["expected_penalty"] - candidates["upgrade_cost"]
        candidates["roi"] = candidates["net_benefit"] / candidates["upgrade_cost"]

        # 只保留 ROI > 0 的訂單（升級才划算）
        candidates = candidates[candidates["net_benefit"] > 0].reset_index(drop=True)
        print(f"  ROI > 0 的候選訂單：{len(candidates):,} 筆")

        if self.max_candidates and len(candidates) > self.max_candidates:
            candidates = (
                candidates
                .sort_values("net_benefit", ascending=False)
                .head(self.max_candidates)
                .reset_index(drop=True)
            )
            print(f"  進入求解器候選上限：{self.max_candidates:,} 筆（依 net_benefit 排序）")
        return candidates

    def _solve_with_pulp(self, candidates: pd.DataFrame) -> list:
        """使用 PuLP 求解 0/1 整數規劃。"""
        n = len(candidates)
        prob = pulp.LpProblem("shipping_upgrade", pulp.LpMaximize)

        # 決策變數
        x = [pulp.LpVariable(f"x_{i}", cat="Binary") for i in range(n)]

        # 目標函數：最大化預期淨效益
        obj = pulp.lpSum(
            (candidates.iloc[i]["expected_penalty"] - candidates.iloc[i]["upgrade_cost"]) * x[i]
            for i in range(n)
        )
        prob += obj

        # 預算限制
        prob += pulp.lpSum(
            candidates.iloc[i]["upgrade_cost"] * x[i] for i in range(n)
        ) <= self.budget

        prob.solve(pulp.PULP_CBC_CMD(msg=0))

        selected = [i for i in range(n) if pulp.value(x[i]) == 1]
        print(f"  PuLP 求解狀態：{pulp.LpStatus[prob.status]}")
        return selected

    def _build_result(
        self,
        candidates: pd.DataFrame,
        selected_indices: list,
        solver: str,
    ) -> OptimizationResult:
        """將求解結果轉換為 OptimizationResult。"""
        selected_df = candidates.iloc[selected_indices] if selected_indices else pd.DataFrame()

        total_cost = selected_df["upgrade_cost"].sum() if len(selected_df) > 0 else 0.0
        total_penalty_avoided = selected_df["expected_penalty"].sum() if len(selected_df) > 0 else 0.0
        total_saving = selected_df["net_benefit"].sum() if len(selected_df) > 0 else 0.0

        # 建立訂單清單
        orders = []
        for _, row in selected_df.iterrows():
            risk_bucket = str(row["risk_bucket"]) if "risk_bucket" in row else "Unknown"
            order = {
                "p_late": round(float(row["p_late"]), 4),
                "upgrade_cost": round(float(row["upgrade_cost"]), 2),
                "expected_penalty": round(float(row["expected_penalty"]), 2),
                "net_benefit": round(float(row["net_benefit"]), 2),
                "expected_saving": round(float(row["net_benefit"]), 2),
                "decision": "Upgrade",
                "reason": self._build_reason(row, risk_bucket),
            }
            if "order_id_hash" in row:
                order["order_id_hash"] = str(row["order_id_hash"])
            if "risk_bucket" in row:
                order["risk_bucket"] = risk_bucket
            orders.append(order)

        return OptimizationResult(
            budget=self.budget,
            total_cost=total_cost,
            total_orders_considered=len(candidates),
            selected_count=len(selected_df),
            expected_total_saving=total_saving,
            expected_total_penalty_avoided=total_penalty_avoided,
            solver=solver,
            selected_orders=orders,
        )

    def _build_reason(self, row: pd.Series, risk_bucket: str) -> str:
        """產生可供 demo 說明的推薦原因。"""
        return (
            f"{risk_bucket} risk, "
            f"p_late={float(row['p_late']):.2f}, "
            f"net benefit NT$ {float(row['net_benefit']):.0f}, "
            "within budget"
        )

    def _save_results(self, result: OptimizationResult, output_dir: str) -> None:
        """儲存最佳化結果（CSV + JSON）。"""
        result_dict = result.to_dict()

        # JSON
        json_path = os.path.join(output_dir, "optimization_result.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result_dict, f, ensure_ascii=False, indent=2)
        print(f"\n  結果 JSON：{json_path}")

        # CSV
        if result.selected_orders:
            csv_path = os.path.join(output_dir, "optimization_result.csv")
            pd.DataFrame(result.selected_orders).to_csv(csv_path, index=False)
            print(f"  結果 CSV：{csv_path}")


# ── 直接執行入口 ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="EDIS ShippingOptimizer")
    parser.add_argument("--predictions", default="data/processed/predictions.csv")
    parser.add_argument("--output", default="data/processed")
    parser.add_argument("--budget", type=float, default=DEFAULT_BUDGET)
    parser.add_argument("--upgrade-cost", type=float, default=DEFAULT_UPGRADE_COST)
    parser.add_argument("--penalty", type=float, default=DEFAULT_DELAY_PENALTY)
    parser.add_argument("--max-candidates", type=int, default=DEFAULT_MAX_CANDIDATES)
    args = parser.parse_args()

    optimizer = ShippingOptimizer(
        budget=args.budget,
        upgrade_cost=args.upgrade_cost,
        delay_penalty=args.penalty,
        max_candidates=args.max_candidates,
    )
    result = optimizer.run(
        predictions_path=args.predictions,
        output_dir=args.output,
    )
    print("\n最佳化摘要：")
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
