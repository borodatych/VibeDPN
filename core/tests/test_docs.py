"""The documentation keeps its structure.

A record of the knowledge base exists only through its line in the index, and a manual only
through its line in the tree of docs/README.md: without them nobody finds it. Both lists rot
silently, and an edit that puts another document in place of the index drops every record at once,
so the lists are checked here together with the first lines that say which document a file is.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]  # tests/ -> core/ -> repository root
DOCS = REPO_ROOT / "docs"
KNOWLEDGE = DOCS / "knowledge"
KNOWLEDGE_INDEX = KNOWLEDGE / "README.md"
ROADMAP = DOCS / "roadmap.md"
DOCS_README = DOCS / "README.md"
MANUALS = DOCS / "manuals"

MARKDOWN_LINK = re.compile(r"\]\(([^)\s]+)\)")
# a record of the knowledge base: docs/knowledge/<domain>/<name>.md, as the index links it
RECORD_LINK = re.compile(r"^[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+\.md$")
TREE_MANUALS = re.compile(r"^[├└]── manuals/")
TREE_CHILD = re.compile(r"^│   [├└]── (\S+)")


def index_links() -> list[str]:
    return MARKDOWN_LINK.findall(KNOWLEDGE_INDEX.read_text(encoding="utf-8"))


def first_line(path: Path) -> str:
    return path.read_text(encoding="utf-8").partition("\n")[0]


def manuals_in_tree() -> set[str]:
    """Names listed under `manuals/` in the tree that opens docs/README.md (its first block)."""
    blocks = DOCS_README.read_text(encoding="utf-8").split("```")
    assert len(blocks) > 2, "docs/README.md does not open with the tree of the documentation"
    tree = blocks[1].splitlines()
    start = next((i for i, line in enumerate(tree) if TREE_MANUALS.match(line)), None)
    assert start is not None, "the tree in docs/README.md has no manuals/ directory"
    names: set[str] = set()
    for line in tree[start + 1 :]:
        child = TREE_CHILD.match(line)
        if child is None:
            break
        names.add(child.group(1))
    return names


def test_every_knowledge_record_is_linked_from_the_index() -> None:
    records = sorted(path.relative_to(KNOWLEDGE).as_posix() for path in KNOWLEDGE.glob("*/*.md"))
    assert records, "no records found under docs/knowledge/<domain>/"
    linked = set(index_links())
    assert [record for record in records if record not in linked] == []


def test_every_index_link_resolves() -> None:
    record_links = [link for link in index_links() if RECORD_LINK.match(link)]
    assert record_links, "the index links no record: is it still the index?"
    assert [link for link in record_links if not (KNOWLEDGE / link).is_file()] == []


def test_index_and_roadmap_are_what_they_claim_to_be() -> None:
    assert first_line(KNOWLEDGE_INDEX) == "# База знаний"
    assert first_line(ROADMAP) == "# Roadmap VibeDPN"


def test_every_manual_is_in_the_docs_tree() -> None:
    manuals = sorted(path.name for path in MANUALS.glob("*.md"))
    assert manuals, "no manuals found in docs/manuals/"
    listed = manuals_in_tree()
    assert [manual for manual in manuals if manual not in listed] == []
