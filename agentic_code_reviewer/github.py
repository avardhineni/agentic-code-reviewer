"""Read-only pull request file retrieval using the GitHub REST API."""
import os
import re
import httpx
from .diff import ChangedFile

SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")


def get_pr_files(repo: str, pr: int) -> list[ChangedFile]:
    parts = repo.split("/")
    if len(parts) != 2 or any(not SAFE_NAME.fullmatch(x) for x in parts):
        raise ValueError("Expected --repo OWNER/REPOSITORY")
    if pr <= 0:
        raise ValueError("--pr must be positive")
    token = os.getenv("GITHUB_TOKEN", "").strip()
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2026-03-10", "User-Agent": "Agentic-Code-Reviewer/0.1"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    found: list[ChangedFile] = []
    with httpx.Client(timeout=30.0, follow_redirects=False) as client:
        for page in range(1, 31):  # GitHub caps at 3,000 files (30 x 100)
            response = client.get(
                f"https://api.github.com/repos/{parts[0]}/{parts[1]}/pulls/{pr}/files",
                params={"per_page": 100, "page": page}, headers=headers,
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, list):
                raise ValueError("Unexpected GitHub response shape")
            for item in data:
                found.append(ChangedFile(path=item["filename"], patch=item.get("patch")))
            if len(data) < 100:
                break
    if len(found) >= 3000:
        # Never pretend to have inspected files omitted by the API limit.
        raise ValueError("PR has >=3000 files. GitHub's files endpoint is capped; split the PR or fetch a complete diff locally.")
    if not found:
        raise ValueError("This pull request has no changed files or is not accessible.")
    return found
