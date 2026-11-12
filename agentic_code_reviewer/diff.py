"""Parse Git unified diffs and create bounded, new-line-addressable chunks."""
import re
from dataclasses import dataclass
from pathlib import PurePosixPath

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
SUPPORTED = {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".java", ".rb", ".rs", ".cs", ".php", ".sql", ".sh", ".yml", ".yaml", ".tf"}


@dataclass(frozen=True)
class ChangedFile:
    path: str
    patch: str | None


@dataclass(frozen=True)
class DiffChunk:
    chunk_id: str
    path: str
    text: str
    anchors: frozenset[int]


def parse_unified_diff(raw: str) -> list[ChangedFile]:
    """Accept ordinary `git diff` output (not a bare hunk with no file path)."""
    files: list[ChangedFile] = []
    path = None
    patch_lines: list[str] = []
    in_patch = False

    def flush():
        if path is not None:
            files.append(ChangedFile(path=path, patch="\n".join(patch_lines) if patch_lines else None))

    for line in raw.splitlines():
        if line.startswith("diff --git "):
            flush()
            m = re.search(r" b/(.+)$", line)
            path = m.group(1) if m else None
            patch_lines = []
            in_patch = False
        elif line.startswith("+++ "):
            # A new file may have /dev/null on the OLD side. Keep its new path.
            candidate = line[4:].strip()
            if candidate.startswith("b/"):
                path = candidate[2:]
        elif HUNK_RE.match(line):
            if path is None:
                raise ValueError("Diff has hunks without a file header (diff --git / +++ b/path).")
            in_patch = True
            patch_lines.append(line)
        elif in_patch:
            patch_lines.append(line)
    flush()
    if not files:
        raise ValueError("No file changes found. Supply a complete unified git diff.")
    return files


def is_supported_source(path: str) -> bool:
    # Ignore binary/lock/archives and non-source assets. Generated source needs manual review.
    return PurePosixPath(path).suffix.lower() in SUPPORTED and not path.endswith((".min.js", ".lock"))


def _numbered_hunks(patch: str):
    """Yield (hunk header, [(display text, optional NEW-side changed line)])."""
    header = None
    items = []
    old_no = 0
    new_no = 0
    for raw in patch.splitlines():
        m = HUNK_RE.match(raw)
        if m:
            if header is not None:
                yield header, items
            header, items = raw, []
            old_no, new_no = int(m.group(1)), int(m.group(3))
            continue
        if header is None or raw.startswith("\\ No newline at end of file"):
            continue
        if raw.startswith("+"):
            items.append((f"NEW:{new_no} + {raw[1:]}", new_no))
            new_no += 1
        elif raw.startswith("-"):
            items.append((f"OLD:{old_no} - {raw[1:]}", None))
            old_no += 1
        elif raw.startswith(" "):
            items.append((f"NEW:{new_no}   {raw[1:]}", None))
            new_no += 1
            old_no += 1
        else:
            # Unrecognized metadata is excluded; do not create phantom line numbers.
            continue
    if header is not None:
        yield header, items


def make_chunks(files: list[ChangedFile], max_chars: int = 7000, max_chunks: int = 20):
    """Returns (chunks, warnings, skipped_files). All skipped inputs are explicit."""
    if max_chars < 600:
        raise ValueError("max_chars must be >=600")
    if max_chunks < 1:
        raise ValueError("max_chunks must be >=1")
    chunks: list[DiffChunk] = []
    warnings: list[str] = []
    skipped: list[str] = []
    for f in files:
        if not is_supported_source(f.path):
            skipped.append(f"{f.path}: unsupported or non-source file")
            continue
        if not f.patch:
            skipped.append(f"{f.path}: GitHub omitted patch (possibly binary or very large)")
            continue
        found_hunk = False
        for header, items in _numbered_hunks(f.patch):
            found_hunk = True
            prefix = f"FILE: {f.path}\n{header}\n"
            buf: list[str] = []
            anchors: set[int] = set()
            length = len(prefix)

            def commit():
                if not buf:
                    return
                # Zero changed-new-line hunks cannot be given a correct inline anchor.
                if not anchors:
                    skipped.append(f"{f.path}: chunk has no added/new-side changed lines")
                    return
                index = len(chunks) + 1
                chunks.append(DiffChunk(f"c{index:04d}", f.path, prefix + "\n".join(buf), frozenset(anchors)))

            for display, maybe_anchor in items:
                # Preserve a line only if it fits; partial/truncated analysis is reported.
                if len(display) + len(prefix) + 1 > max_chars:
                    if buf:
                        commit()
                        buf, anchors, length = [], set(), len(prefix)
                    skipped.append(f"{f.path}: one extremely long diff line exceeded chunk size")
                    continue
                if buf and length + len(display) + 1 > max_chars:
                    commit()
                    buf, anchors, length = [], set(), len(prefix)
                buf.append(display)
                length += len(display) + 1
                if maybe_anchor is not None:
                    anchors.add(maybe_anchor)
            commit()
        if not found_hunk:
            skipped.append(f"{f.path}: no parsable @@ hunks")
    if len(chunks) > max_chunks:
        warnings.append(f"Budget limit: only first {max_chunks} of {len(chunks)} chunks processed.")
        chunks = chunks[:max_chunks]
    if not chunks:
        warnings.append("No reviewable changed-source lines found.")
    return chunks, warnings, skipped
