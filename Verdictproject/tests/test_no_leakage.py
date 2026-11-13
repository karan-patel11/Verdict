"""Governance rule 4: the extractor sees rendered text only; labeler and extractor are independent."""
import ast
from pathlib import Path

import pytest
from _real_helpers import ixbrl_html

from abstention.data import gold_labels as gl
from abstention.data.render import LeakageError, assert_clean, ixbrl_to_pages, select_statement_pages
from abstention.extraction.llm_extractor import build_prompt

SRC = Path(__file__).resolve().parents[1] / "src" / "abstention"


def test_rendering_strips_all_xbrl_and_hidden_facts():
    pages = ixbrl_to_pages(ixbrl_html("987654321"))
    joined = "\n".join(pages)
    assert len(pages) >= 3
    for bad in ("ix:", "us-gaap", "contextRef", "unitRef", "xbrli", "dei:", "987654321", "Hidden"):
        assert bad.lower() not in joined.lower(), bad
    assert "<" not in joined and ">" not in joined


def test_cells_dollar_and_parentheses_are_cleaned():
    joined = "\n".join(ixbrl_to_pages(ixbrl_html()))
    assert "Total assets | 1,234" in joined
    assert "$" not in joined
    assert "(5,678)" in joined


def test_statement_page_selection_skips_cover_and_notes():
    pages = ixbrl_to_pages(ixbrl_html())
    chosen = select_statement_pages(pages)
    assert len(chosen) == 1 and "BALANCE SHEETS" in chosen[0][1]


def test_assert_clean_fails_loudly_on_markup():
    for dirty in ("<ix:nonFraction>1</ix:nonFraction>", "us-gaap:Assets 5", "contextRef=c1", "<td>1</td>"):
        with pytest.raises(LeakageError):
            assert_clean(dirty)
    assert_clean("Total assets | 1,234 | (5,678)")


def test_prompt_instructions_contain_no_gold_tags_or_values():
    pages = [(2, "Total assets | 1,234,567")]
    p = build_prompt(pages)
    outside_document = p.system + p.instructions
    all_tags = {t for s in gl.SPECS.values() for t in (*s.tags, *s.excluded_tags)}
    for tag in all_tags:
        assert tag not in p.system + p.user, tag
    for gold_value in ("1234567000", "5678000", "98765000"):   # values a labeler could hold
        assert gold_value not in outside_document
    assert "=== PAGE 2 ===" in p.document and "1,234,567" in p.document


def _imports(path: Path) -> set[str]:
    mods = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            mods |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            mods.add(("." * node.level) + (node.module or ""))
            mods |= {("." * node.level) + (node.module or "") + "." + a.name for a in node.names}
    return mods


def test_labeler_never_imports_extractor_and_extractor_never_imports_labeler():
    labeler_side = [SRC / "data" / "gold_labels.py", SRC / "data" / "sec_schema.py", SRC / "data" / "render.py"]
    for f in labeler_side:
        assert not any("extraction" in m for m in _imports(f)), f
    for f in (SRC / "extraction").glob("*.py"):
        bad = [m for m in _imports(f) if "gold_labels" in m or "edgar_corpus" in m or "real_eval" in m]
        assert not bad, (f, bad)
