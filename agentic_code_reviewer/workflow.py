"""LangGraph workflow: prepare -> understand -> security -> error -> testing -> finalize."""
import re
from dataclasses import dataclass
from typing import TypedDict, Any
from langgraph.graph import StateGraph, START, END
from .diff import ChangedFile, make_chunks
from .llm import ask_typed, get_client
from .models import Finding, FindingsResponse, UnderstandingResponse
from .prompts import understand_prompt, stage_prompt


@dataclass
class ReviewConfig:
    model: str = "gpt-5-mini"
    max_chars: int = 7000
    max_chunks: int = 20
    max_attempts: int = 3
    min_confidence: float = 0.70


class ReviewState(TypedDict, total=False):
    files: list[ChangedFile]
    chunks: list[Any]
    warnings: list[str]
    skipped: list[str]
    errors: list[str]
    findings: list[Finding]
    summary: str
    understanding_scope: str
    stats: dict
    report: dict


def _test_path(path: str) -> bool:
    p = path.lower().replace("\\", "/")
    name = p.rsplit("/", 1)[-1]
    return (p.startswith("tests/") or "/tests/" in p or name.startswith("test_") or
            name.endswith("_test.py") or ".test." in name or ".spec." in name or name.endswith("_spec.rb"))


def _validated_findings(incoming: list[Finding], category: str, chunk, min_confidence: float):
    accepted, rejected = [], []
    for f in incoming:
        reasons = []
        if f.path != chunk.path:
            reasons.append("incorrect file path")
        if f.line not in chunk.anchors:
            reasons.append("line is not an added/new-side changed line")
        if f.category != category:
            reasons.append("incorrect review category")
        if not 0 <= f.confidence <= 1:
            reasons.append("confidence outside 0..1")
        if f.confidence < min_confidence:
            reasons.append("below confidence threshold")
        if not f.title.strip() or not f.explanation.strip() or not f.recommendation.strip():
            reasons.append("missing actionable explanation")
        if reasons:
            rejected.append(f"{chunk.chunk_id} {f.path}:{f.line} ({', '.join(reasons)})")
        else:
            accepted.append(f)
    return accepted, rejected


def _deduplicate(findings: list[Finding]):
    # One comment per (file, line, category); retain highest-confidence finding.
    # More sophisticated semantic grouping could be added in phase 2.
    by_location = {}
    for f in findings:
        key = (f.path, f.line, f.category)
        if key not in by_location or f.confidence > by_location[key].confidence:
            by_location[key] = f
    priority = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    return sorted(by_location.values(), key=lambda x: (priority[x.severity], x.path, x.line))


def make_workflow(config: ReviewConfig | None = None, client=None):
    """Inject a mock client for offline tests. Real client is created on first API use."""
    cfg = config or ReviewConfig()
    client_ref = [client]

    def use_client():
        if client_ref[0] is None:
            client_ref[0] = get_client()
        return client_ref[0]

    def prepare(state: ReviewState):
        chunks, warnings, skipped = make_chunks(state["files"], cfg.max_chars, cfg.max_chunks)
        return {
            "chunks": chunks, "warnings": warnings, "skipped": skipped, "errors": [], "findings": [],
            "summary": "", "understanding_scope": "none",
            "stats": {"files": len(state["files"]), "chunks": len(chunks), "successful_reviews": 0,
                      "failed_reviews": 0, "rejected_findings": 0, "api_calls": 0,
                      "input_tokens": 0, "output_tokens": 0},
        }

    def understand(state: ReviewState):
        chunks = state["chunks"]
        if not chunks:
            return {"summary": "No reviewable changes were available."}
        # Bound high-level summary input, but every admitted chunk is scanned by downstream agents.
        preview = []
        length = 0
        for ch in chunks:
            if length + len(ch.text) > cfg.max_chars * 2 and preview:
                break
            preview.append(ch)
            length += len(ch.text)
        scope = "all chunks" if len(preview) == len(chunks) else f"sampled {len(preview)}/{len(chunks)} chunks"
        stats = dict(state["stats"])
        try:
            output, usage = ask_typed(use_client(), cfg.model,
                                      understand_prompt(preview, len(chunks)),
                                      UnderstandingResponse, cfg.max_attempts)
            stats["api_calls"] += 1
            stats["input_tokens"] += usage["input_tokens"]
            stats["output_tokens"] += usage["output_tokens"]
            return {"summary": output.summary, "understanding_scope": scope, "stats": stats}
        except Exception as exc:
            return {"summary": "Change understanding failed; specialized reviews will still run.",
                    "understanding_scope": "failed", "errors": state["errors"] + [f"understand: {type(exc).__name__}: {exc}"]}

    def make_stage_node(category: str):
        def node(state: ReviewState):
            findings = list(state["findings"])
            errors = list(state["errors"])
            warnings = list(state["warnings"])
            stats = dict(state["stats"])
            tests_touched = any(_test_path(f.path) for f in state["files"])
            for chunk in state["chunks"]:
                try:
                    result, usage = ask_typed(
                        use_client(), cfg.model, stage_prompt(category, chunk, tests_touched),
                        FindingsResponse, cfg.max_attempts,
                    )
                    stats["api_calls"] += 1
                    stats["input_tokens"] += usage["input_tokens"]
                    stats["output_tokens"] += usage["output_tokens"]
                    accepted, rejected = _validated_findings(result.findings, category, chunk, cfg.min_confidence)
                    findings.extend(accepted)
                    stats["rejected_findings"] += len(rejected)
                    warnings.extend(["Rejected ungrounded/low-confidence finding: " + r for r in rejected])
                    stats["successful_reviews"] += 1
                except Exception as exc:
                    # Do not silently return "no issues" on failure.
                    errors.append(f"{category} {chunk.chunk_id} {chunk.path}: {type(exc).__name__}: {exc}")
                    stats["failed_reviews"] += 1
            return {"findings": findings, "errors": errors, "warnings": warnings, "stats": stats}
        return node

    def finalize(state: ReviewState):
        final_findings = _deduplicate(state["findings"])
        total_expected = len(state["chunks"]) * 3
        covered = state["stats"]["successful_reviews"]
        incomplete = (bool(state["skipped"]) or bool(state["errors"]) or
                      len(state["chunks"]) == 0 or covered != total_expected or
                      state.get("understanding_scope") == "failed" or
                      any("Budget limit" in w for w in state["warnings"]))
        report = {
            "status": "partial" if incomplete else "complete",
            "summary": state["summary"],
            "understanding_scope": state.get("understanding_scope", "unknown"),
            "findings": [f.model_dump() for f in final_findings],
            "coverage": {"successful_chunk_stage_reviews": covered, "expected_chunk_stage_reviews": total_expected},
            "warnings": state["warnings"],
            "skipped": state["skipped"],
            "errors": state["errors"],
            "stats": state["stats"],
            "review_policy": "Read-only AI review. Human validation required before merge. No code executed.",
        }
        return {"report": report}

    g = StateGraph(ReviewState)
    g.add_node("prepare", prepare)
    g.add_node("understand_changes", understand)
    g.add_node("security_review", make_stage_node("security"))
    g.add_node("error_handling_review", make_stage_node("error_handling"))
    g.add_node("testing_review", make_stage_node("testing"))
    g.add_node("finalize_report", finalize)
    g.add_edge(START, "prepare")
    g.add_edge("prepare", "understand_changes")
    g.add_edge("understand_changes", "security_review")
    g.add_edge("security_review", "error_handling_review")
    g.add_edge("error_handling_review", "testing_review")
    g.add_edge("testing_review", "finalize_report")
    g.add_edge("finalize_report", END)
    return g.compile()


def run_review(files: list[ChangedFile], config: ReviewConfig | None = None, client=None) -> dict:
    return make_workflow(config, client).invoke({"files": files})["report"]
