"""Inline-XBRL filing HTML -> clean text pages for the extractor.

Governance rule 4: the extractor sees rendered text only. Every XBRL element is unwrapped to
its visible text, the hidden `ix:header` block (which carries facts and contexts) is dropped,
and anything with display:none is dropped. `assert_clean` fails loudly if tag markup or
taxonomy names survive. Pure stdlib.

Finding the primary-statements pages is a separate retrieval task that this project hands
over (see DATA_CARD.md): `select_statement_pages` is a heuristic, and the pages it picks are
recorded in the manifest so the choice is auditable.
"""
from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser

_BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table"}
_CELL = {"td", "th"}
_BREAK_STYLE = re.compile(
    r"(page-break-(after|before)\s*:\s*always|break-(after|before)\s*:\s*page)", re.I
)
_HIDDEN_STYLE = re.compile(r"display\s*:\s*none", re.I)
_LEAK = re.compile(r"(ix:|xbrli|us-gaap|contextref|unitref|dei:|<\s*/?\s*[a-z][a-z0-9:]*[\s>/])", re.I)


class LeakageError(ValueError):
    """Tag markup or taxonomy names reached text that was meant for the extractor."""


def assert_clean(text: str) -> None:
    m = _LEAK.search(text)
    if m:
        raise LeakageError(f"markup or taxonomy name survived rendering: {m.group(0)!r}")


class _Renderer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.pages: list[list[str]] = [[]]
        self._stack: list[tuple[str, bool, bool]] = []  # (tag, hides_content, break_after)
        self._hidden_depth = 0
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    # -- helpers
    def _emit(self, s: str) -> None:
        if self._hidden_depth:
            return
        if self._cell is not None:
            self._cell.append(s)
        else:
            self.pages[-1].append(s)

    def _flush_row(self) -> None:
        if self._row is None:
            return
        cells = []
        for c in self._row:
            c = re.sub(r"\s+", " ", c).strip()
            if c in ("", "$", "%"):
                continue
            if c.startswith(")") and cells:
                cells[-1] += c
                continue
            cells.append(c)
        if cells:
            self.pages[-1].append(" | ".join(cells) + "\n")
        self._row = None

    # -- parser callbacks
    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        style = a.get("style", "")
        hides = tag == "ix:header" or tag in ("script", "style") or bool(_HIDDEN_STYLE.search(style))
        brk = _BREAK_STYLE.search(style)
        brk_after = bool(brk) and brk.group(0).lower().split(":")[0].endswith("after")
        brk_before = bool(brk) and not brk_after
        if brk_before and not self._hidden_depth:
            self._new_page()
        if tag in ("br", "img", "hr", "meta", "link", "input"):
            if brk_after and not self._hidden_depth:
                self._new_page()
        else:
            self._stack.append((tag, hides, brk_after))
            if hides:
                self._hidden_depth += 1
        if tag == "tr":
            self._flush_row()
            self._row = []
        elif tag in _CELL and self._row is not None:
            self._cell = []
        elif tag in _BLOCK and self._row is None:
            self._emit("\n")

    def handle_endtag(self, tag):
        page_after = False
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                page_after = self._stack[i][2] and not self._hidden_depth
                for _, hid, _b in self._stack[i:]:
                    if hid:
                        self._hidden_depth -= 1
                del self._stack[i:]
                break
        if tag in _CELL and self._cell is not None and self._row is not None:
            self._row.append("".join(self._cell))
            self._cell = None
        elif tag == "tr":
            self._flush_row()
        elif tag in _BLOCK and self._row is None:
            self._emit("\n")
        if page_after and not self._hidden_depth:
            self._new_page()

    def handle_data(self, data):
        if not self._hidden_depth and data.strip():
            self._emit(data if self._cell is not None else re.sub(r"\s+", " ", data))

    def _new_page(self) -> None:
        self._flush_row()
        if any(s.strip() for s in self.pages[-1]):
            self.pages.append([])

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)


def ixbrl_to_pages(html: str, *, fallback_lines_per_page: int = 120) -> list[str]:
    r = _Renderer()
    r.feed(html)
    r._flush_row()
    pages = ["".join(p) for p in r.pages]
    pages = [re.sub(r"\n{3,}", "\n\n", p).strip() for p in pages if p.strip()]
    if len(pages) < 2:  # no explicit page breaks: chunk by lines
        lines = "\n".join(pages).splitlines()
        pages = ["\n".join(lines[i : i + fallback_lines_per_page])
                 for i in range(0, len(lines), fallback_lines_per_page)]
    for p in pages:
        assert_clean(p)
    return pages


_STATEMENT_TITLE = re.compile(
    r"(CONSOLIDATED\s+)?(BALANCE\s+SHEETS?|STATEMENTS?\s+OF\s+(OPERATIONS|INCOME|EARNINGS|"
    r"COMPREHENSIVE\s+(INCOME|LOSS)|CASH\s+FLOWS?)|FINANCIAL\s+CONDITION)", re.I)
_NUMBER = re.compile(r"\(?\d[\d,]{2,}(\.\d+)?\)?")


def select_statement_pages(pages: list[str], *, max_pages: int = 8) -> list[tuple[int, str]]:
    """Return (1-indexed page number, text) for pages that look like primary statements:
    a statement title AND enough numbers to rule out a table of contents."""
    chosen = []
    for i, p in enumerate(pages, start=1):
        head = "\n".join(p.splitlines()[:12])
        if _STATEMENT_TITLE.search(head) and len(_NUMBER.findall(p)) >= 15:
            chosen.append((i, p))
        if len(chosen) >= max_pages:
            break
    return chosen


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
