"""CLI for local diff, GitHub PR and evaluation suite."""
import argparse
import json
import os
from pathlib import Path
from dotenv import load_dotenv
from .diff import parse_unified_diff
from .github import get_pr_files
from .report import save_report
from .workflow import ReviewConfig, run_review
from .evaluation import evaluate_dataset


def add_review_options(p):
    p.add_argument("--output", default="reports/latest.json", help="JSON report path; Markdown saved alongside")
    p.add_argument("--model", default=None, help="Structured-output-capable OpenAI model")
    p.add_argument("--max-chars", type=int, default=7000, help="Max characters per diff chunk")
    p.add_argument("--max-chunks", type=int, default=20, help="Cost guardrail; excessive chunks yield PARTIAL report")
    p.add_argument("--min-confidence", type=float, default=0.70)


def get_config(args):
    return ReviewConfig(model=args.model or os.getenv("REVIEW_MODEL", "gpt-5-mini"),
                        max_chars=args.max_chars, max_chunks=args.max_chunks,
                        min_confidence=args.min_confidence)


def main():
    load_dotenv()
    p = argparse.ArgumentParser(description="Read-only agentic Git diff reviewer")
    sub = p.add_subparsers(dest="command", required=True)
    a = sub.add_parser("review-diff", help="Review a local `git diff` patch")
    a.add_argument("diff_file", help="Path to complete unified .patch file")
    add_review_options(a)
    b = sub.add_parser("review-pr", help="Review changed files of a GitHub PR")
    b.add_argument("--repo", required=True, help="GitHub OWNER/REPO")
    b.add_argument("--pr", required=True, type=int)
    add_review_options(b)
    c = sub.add_parser("evaluate", help="Score previously generated case reports")
    c.add_argument("--dataset", required=True)
    c.add_argument("--reports-dir", required=True)
    d = sub.add_parser("run-eval", help="Run all sample/historical cases with the model, then score")
    d.add_argument("--dataset", default="datasets/synthetic_cases.json")
    d.add_argument("--reports-dir", default="reports/eval")
    d.add_argument("--model", default=None)
    d.add_argument("--max-chars", type=int, default=7000)
    d.add_argument("--max-chunks", type=int, default=20)
    d.add_argument("--min-confidence", type=float, default=0.70)
    args = p.parse_args()
    if args.command != "evaluate" and not os.getenv("OPENAI_API_KEY"):
        p.error("OPENAI_API_KEY is not set. Copy .env.example to .env and add a valid key.")
    if args.command == "evaluate":
        print(json.dumps(evaluate_dataset(args.dataset, args.reports_dir), indent=2))
        return
    if args.command == "run-eval":
        dataset = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
        root = Path(args.dataset).resolve().parent.parent  # relative diff_file path from project root
        for case in dataset["cases"]:
            src = (root / case["diff_file"]).resolve()
            # Restrict dataset paths to this project to avoid accidental file reads.
            if not src.is_relative_to(root):
                raise ValueError("Dataset diff_file points outside project root")
            files = parse_unified_diff(src.read_text(encoding="utf-8"))
            report = run_review(files, get_config(args))
            output = str(Path(args.reports_dir) / f"{case['id']}.json")
            save_report(report, output)
            print(f"{case['id']}: {report['status']}; {len(report['findings'])} findings")
        print(json.dumps(evaluate_dataset(args.dataset, args.reports_dir), indent=2))
        return
    if args.command == "review-diff":
        files = parse_unified_diff(Path(args.diff_file).read_text(encoding="utf-8"))
    else:
        files = get_pr_files(args.repo, args.pr)
    report = run_review(files, get_config(args))
    json_file, md_file = save_report(report, args.output)
    print(f"Review status: {report['status'].upper()}")
    print(f"Findings: {len(report['findings'])}; step failures: {len(report['errors'])}")
    print(f"Coverage: {report['coverage']['successful_chunk_stage_reviews']}/{report['coverage']['expected_chunk_stage_reviews']}")
    print(f"Reports: {json_file} and {md_file}")
    if report["status"] == "partial":
        print("WARNING: Review incomplete. See report warnings/skipped/errors; do NOT treat zero findings as approval.")


if __name__ == "__main__":
    main()
