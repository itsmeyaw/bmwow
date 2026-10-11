"""HTML → readable markdown-ish text for the web corpus (standard library only).

Keeps what spec and regulation pages carry their facts in: headings, paragraphs, list items and
tables (as `| a | b |` rows, so a value stays next to its label). Drops scripts, styles, navigation,
headers, footers, forms and other page chrome.
"""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser

_SKIP = {
    "script",
    "style",
    "noscript",
    "svg",
    "nav",
    "footer",
    "header",
    "form",
    "aside",
    "iframe",
    "button",
    "select",
    "template",
}
_BLOCK = {
    "p",
    "div",
    "section",
    "article",
    "main",
    "br",
    "li",
    "dt",
    "dd",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "tr",
    "table",
    "ul",
    "ol",
    "dl",
    "blockquote",
    "figcaption",
    "caption",
}


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0
        self.title = ""
        self._in_title = False
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        if tag == "title":
            self._in_title = True
        elif tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag in _BLOCK:
            self.out.append("\n")
            if tag in ("h1", "h2", "h3", "h4"):
                self.out.append("#" * int(tag[1]) + " ")
            elif tag == "li":
                self.out.append("- ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag == "title":
            self._in_title = False
        elif tag in ("td", "th") and self._row is not None and self._cell is not None:
            self._row.append(_clean(" ".join(self._cell)))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            cells = [c for c in self._row if c]
            if cells:
                self.out.append("\n| " + " | ".join(cells) + " |\n")
            self._row = None
        elif tag in _BLOCK:
            self.out.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        if self._in_title:
            self.title += data
        elif self._cell is not None:
            self._cell.append(data)
        else:
            self.out.append(data)


def _clean(text: str) -> str:
    return re.sub(r"[ \t\r\f\v ]+", " ", unescape(text)).strip()


def html_to_text(html: str) -> tuple[str, str]:
    """(title, text). Text keeps paragraph breaks; whitespace inside lines is collapsed."""
    parser = _Extractor()
    parser.feed(html)
    parser.close()
    lines = [_clean(line) for line in "".join(parser.out).split("\n")]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    text = re.sub(r"(?m)^(#+|-)\s*$\n?", "", text)  # empty headings / bullets
    return _clean(parser.title), re.sub(r"\n{3,}", "\n\n", text).strip()
