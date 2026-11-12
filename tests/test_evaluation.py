from agentic_code_reviewer.evaluation import match_case, calculate_metrics


def test_tp_fp_fn():
    report = {"findings": [
        {"path": "app/auth.py", "line": 54, "category": "security"},
        {"path": "app/auth.py", "line": 55, "category": "testing"},
    ]}
    gold = [{"path": "app/auth.py", "line": 54, "category": "security"},
            {"path": "app/other.py", "line": 10, "category": "error_handling"}]
    assert match_case(report, gold) == {"tp": 1, "fp": 1, "fn": 1, "predicted": 2, "known_bugs": 2}
    assert calculate_metrics(1, 1, 1) == {"precision": 0.5, "recall": 0.5, "f1": 0.5}


def test_no_detections_does_not_fake_perfect_precision():
    metrics = calculate_metrics(0, 0, 0)
    assert metrics["precision"] is None
    assert metrics["recall"] is None
