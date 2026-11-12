"""Bug-level precision/recall using exhaustively annotated historical/synthetic cases.

Ground truth MUST be validated by a human. Unmatched findings are *candidate* FPs,
not guaranteed false bugs, if gold labels are incomplete.
"""
import json
from pathlib import Path


def match_case(report: dict, known_bugs: list[dict], line_tolerance: int = 0):
    preds = report.get("findings", [])
    taken = set()
    tp = 0
    for expected in known_bugs:
        for i, actual in enumerate(preds):
            if i in taken:
                continue
            if (actual.get("path") == expected.get("path") and
                actual.get("category") == expected.get("category") and
                abs(actual.get("line", -999999) - expected.get("line", -999999)) <= line_tolerance):
                tp += 1
                taken.add(i)
                break
    return {"tp": tp, "fp": len(preds) - tp, "fn": len(known_bugs) - tp,
            "predicted": len(preds), "known_bugs": len(known_bugs)}


def calculate_metrics(tp: int, fp: int, fn: int):
    # Undefined precision/recall when no positives exist is represented as null.
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (2 * precision * recall / (precision + recall)) if precision is not None and recall is not None and (precision + recall) else (0.0 if precision is not None and recall is not None else None)
    return {"precision": precision, "recall": recall, "f1": f1}


def evaluate_dataset(dataset_path: str, reports_dir: str):
    data = json.loads(Path(dataset_path).read_text(encoding="utf-8"))
    cases = data["cases"]
    counts = {"tp": 0, "fp": 0, "fn": 0}
    included = []
    excluded = []
    for case in cases:
        file = Path(reports_dir) / f"{case['id']}.json"
        if not file.is_file():
            excluded.append({"id": case["id"], "reason": "no report found"})
            continue
        report = json.loads(file.read_text(encoding="utf-8"))
        if report.get("status") != "complete":
            excluded.append({"id": case["id"], "reason": "partial/incomplete review"})
            continue
        out = match_case(report, case["bugs"])
        included.append({"id": case["id"], **out})
        for key in counts:
            counts[key] += out[key]
    return {"dataset": data.get("dataset_name", "unnamed"), "evaluated_cases": len(included),
            "total_cases": len(cases), "excluded_cases": excluded, **counts,
            **calculate_metrics(**counts),
            "false_alerts_per_evaluated_case": counts["fp"] / len(included) if included else None,
            "cases": included,
            "note": "Unmatched findings are candidate false positives; human labels must be exhaustive."}
