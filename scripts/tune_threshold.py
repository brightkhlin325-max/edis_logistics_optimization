"""
Tune the late-risk decision threshold from an existing predictions.csv file.

This script does not retrain the model. It scans candidate thresholds and
compares precision, recall, F1, confusion matrix counts, and business cost.
"""

import argparse
import json
import os
from typing import Dict, List

import pandas as pd


DEFAULT_INPUT = "data/processed/predictions.csv"
DEFAULT_OUTPUT_DIR = "data/processed"


def safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def evaluate_threshold(
    y_true: pd.Series,
    y_prob: pd.Series,
    threshold: float,
    upgrade_cost: float,
    delay_penalty: float,
) -> Dict[str, float]:
    y_pred = y_prob >= threshold

    tp = int(((y_true == 1) & y_pred).sum())
    tn = int(((y_true == 0) & (~y_pred)).sum())
    fp = int(((y_true == 0) & y_pred).sum())
    fn = int(((y_true == 1) & (~y_pred)).sum())

    precision = safe_div(tp, tp + fp)
    recall = safe_div(tp, tp + fn)
    f1 = safe_div(2 * precision * recall, precision + recall)
    selected_count = int(y_pred.sum())

    upgrade_spend = selected_count * upgrade_cost
    missed_delay_cost = fn * delay_penalty
    false_alarm_cost = fp * upgrade_cost
    expected_cost = missed_delay_cost + false_alarm_cost

    return {
        "threshold": round(threshold, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "selected_count": selected_count,
        "upgrade_spend": round(upgrade_spend, 2),
        "missed_delay_cost": round(missed_delay_cost, 2),
        "false_alarm_cost": round(false_alarm_cost, 2),
        "expected_cost": round(expected_cost, 2),
    }


def build_thresholds(start: float, stop: float, step: float) -> List[float]:
    values = []
    current = start
    while current <= stop + 1e-9:
        values.append(round(current, 10))
        current += step
    return values


def tune_thresholds(
    input_path: str,
    output_dir: str,
    start: float,
    stop: float,
    step: float,
    upgrade_cost: float,
    delay_penalty: float,
) -> Dict[str, object]:
    df = pd.read_csv(input_path)
    required = {"true_label", "p_late"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns in {input_path}: {sorted(missing)}")

    y_true = df["true_label"].astype(int)
    y_prob = df["p_late"].astype(float)

    rows = [
        evaluate_threshold(y_true, y_prob, threshold, upgrade_cost, delay_penalty)
        for threshold in build_thresholds(start, stop, step)
    ]
    result_df = pd.DataFrame(rows)

    best_f1 = result_df.sort_values(
        ["f1", "recall", "precision"],
        ascending=[False, False, False],
    ).iloc[0].to_dict()
    best_cost = result_df.sort_values(
        ["expected_cost", "fn", "fp"],
        ascending=[True, True, True],
    ).iloc[0].to_dict()

    os.makedirs(output_dir, exist_ok=True)
    csv_path = os.path.join(output_dir, "threshold_tuning.csv")
    json_path = os.path.join(output_dir, "threshold_tuning_summary.json")

    result_df.to_csv(csv_path, index=False)
    summary = {
        "input_path": input_path,
        "row_count": int(len(df)),
        "upgrade_cost": upgrade_cost,
        "delay_penalty": delay_penalty,
        "best_f1": best_f1,
        "best_expected_cost": best_cost,
        "outputs": {
            "csv": csv_path,
            "json": json_path,
        },
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Tune prediction threshold for EDIS late-risk model.")
    parser.add_argument("--input", default=DEFAULT_INPUT, help="Path to predictions.csv.")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Directory for tuning outputs.")
    parser.add_argument("--start", type=float, default=0.1, help="First threshold to evaluate.")
    parser.add_argument("--stop", type=float, default=0.9, help="Last threshold to evaluate.")
    parser.add_argument("--step", type=float, default=0.05, help="Threshold interval.")
    parser.add_argument("--upgrade-cost", type=float, default=80.0, help="Cost of upgrading one order.")
    parser.add_argument("--delay-penalty", type=float, default=250.0, help="Cost of missing one delayed order.")
    args = parser.parse_args()

    summary = tune_thresholds(
        input_path=args.input,
        output_dir=args.output_dir,
        start=args.start,
        stop=args.stop,
        step=args.step,
        upgrade_cost=args.upgrade_cost,
        delay_penalty=args.delay_penalty,
    )

    print("Threshold tuning completed.")
    print(f"Rows analyzed: {summary['row_count']}")
    print(f"Best F1 threshold: {summary['best_f1']['threshold']} (F1={summary['best_f1']['f1']})")
    print(
        "Best cost threshold: "
        f"{summary['best_expected_cost']['threshold']} "
        f"(expected_cost={summary['best_expected_cost']['expected_cost']})"
    )
    print(f"CSV: {summary['outputs']['csv']}")
    print(f"JSON: {summary['outputs']['json']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
