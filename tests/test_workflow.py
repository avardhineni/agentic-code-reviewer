from pathlib import Path
from unittest.mock import patch
from agentic_code_reviewer.diff import parse_unified_diff
from agentic_code_reviewer.models import Finding, FindingsResponse, UnderstandingResponse
from agentic_code_reviewer.workflow import run_review, ReviewConfig

ROOT = Path(__file__).parent.parent


def test_workflow_lines_and_structured_report_without_real_api():
    files = parse_unified_diff((ROOT / "samples/vulnerable.patch").read_text())
    def fake_ask(_client, _model, prompt, schema, _attempts):
        if schema is UnderstandingResponse:
            return UnderstandingResponse(summary="SQL lookup changed", change_types=["database"], areas_to_watch=["injection"]), {"input_tokens": 15, "output_tokens": 5}
        findings = []
        if "REVIEW CATEGORY: security" in prompt:
            findings = [Finding(path="app/auth.py", line=54, category="security", severity="high", title="SQL injection", explanation="Raw user input in SQL", recommendation="Parameterize", confidence=0.96),
                        Finding(path="app/auth.py", line=999, category="security", severity="high", title="Invented", explanation="Not real", recommendation="None", confidence=0.9)]
        return FindingsResponse(findings=findings), {"input_tokens": 10, "output_tokens": 5}
    with patch("agentic_code_reviewer.workflow.ask_typed", fake_ask):
        report = run_review(files, ReviewConfig(), client=object())
    assert report["status"] == "complete"
    assert report["coverage"]["successful_chunk_stage_reviews"] == 3
    assert len(report["findings"]) == 1
    assert report["findings"][0]["line"] == 54
    assert report["stats"]["rejected_findings"] == 1


def test_failed_stage_reports_partial_not_false_success():
    files = parse_unified_diff((ROOT / "samples/vulnerable.patch").read_text())
    def fail(_client, _model, prompt, schema, _attempts):
        if schema is UnderstandingResponse:
            return UnderstandingResponse(summary="Changes", change_types=[], areas_to_watch=[]), {"input_tokens": 0, "output_tokens": 0}
        if "REVIEW CATEGORY: security" in prompt:
            raise RuntimeError("service unavailable")
        return FindingsResponse(findings=[]), {"input_tokens": 0, "output_tokens": 0}
    with patch("agentic_code_reviewer.workflow.ask_typed", fail):
        report = run_review(files, ReviewConfig(), client=object())
    assert report["status"] == "partial"
    assert report["errors"]
    assert report["coverage"]["successful_chunk_stage_reviews"] == 2
