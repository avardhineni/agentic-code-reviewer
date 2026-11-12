from pathlib import Path
from agentic_code_reviewer.diff import parse_unified_diff, make_chunks, ChangedFile

ROOT = Path(__file__).parent.parent


def test_sql_line_anchor():
    files = parse_unified_diff((ROOT / "samples/vulnerable.patch").read_text())
    chunks, warnings, skipped = make_chunks(files)
    assert len(files) == 1
    assert len(chunks) == 1
    assert 54 in chunks[0].anchors
    assert 55 in chunks[0].anchors
    assert "NEW:54 +" in chunks[0].text
    assert not warnings and not skipped


def test_large_diff_is_chunked_and_budget_is_visible():
    patch = "@@ -1,0 +1,40 @@\n" + "\n".join(f"+print({i})" for i in range(40))
    chunks, warnings, skipped = make_chunks([ChangedFile("demo.py", patch)], max_chars=600, max_chunks=1)
    assert len(chunks) == 1
    assert warnings and "Budget limit" in warnings[0]
    assert not skipped


def test_binary_or_missing_patch_explicitly_skipped():
    chunks, warnings, skipped = make_chunks([ChangedFile("logo.png", None), ChangedFile("hello.py", None)])
    assert not chunks
    assert len(skipped) == 2
    assert warnings
