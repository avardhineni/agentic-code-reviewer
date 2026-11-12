"""Render JSON review to readable Markdown with explicit completeness information."""
import json
from pathlib import Path


def markdown_report(report: dict) -> str:
    lines = ["# Agentic Code Review", "", f"**Status:** {report['status'].upper()}", "",
             "## Change summary", "", report.get("summary") or "(no summary)", "",
             "## Findings", ""]
    if not report.get("findings"):
        lines += ["No actionable findings were returned. This is not proof that the code is bug-free.", ""]
    for f in report.get("findings", []):
        lines += [f"### {f['severity'].upper()}: {f['title']}", "",
                  f"- **Location:** `{f['path']}:{f['line']}`",
                  f"- **Category:** {f['category']}", f"- **Confidence (model estimate):** {f['confidence']:.2f}",
                  f"- **Why it matters:** {f['explanation']}",
                  f"- **Recommended fix:** {f['recommendation']}", ""]
    cov = report["coverage"]
    lines += ["## Coverage and limitations", "",
              f"- Chunk/stage reviews completed: {cov['successful_chunk_stage_reviews']}/{cov['expected_chunk_stage_reviews']}",
              f"- Understanding scope: {report.get('understanding_scope')}",
              f"- Input tokens: {report['stats']['input_tokens']}; output tokens: {report['stats']['output_tokens']}",
              "- AI recommendations require human verification before merge.", ""]
    for label, key in (("Warnings", "warnings"), ("Skipped input", "skipped"), ("Step failures", "errors")):
        if report.get(key):
            lines += [f"## {label}", ""]
            lines.extend(f"- {x}" for x in report[key])
            lines.append("")
    return "\n".join(lines) + "\n"


def save_report(report: dict, output_path: str):
    base = Path(output_path)
    if base.suffix.lower() == ".json":
        base = base.with_suffix("")
    base.parent.mkdir(parents=True, exist_ok=True)
    json_file = base.with_suffix(".json")
    md_file = base.with_suffix(".md")
    json_file.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_file.write_text(markdown_report(report), encoding="utf-8")
    return json_file, md_file
