"""A unit of game source, and where each of its lines really came from."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lyo.cartridge import png as png_mod
from lyo.cartridge.markdown import tangle


@dataclass(frozen=True)
class Source:
    """Parseable text, plus enough provenance to report a position honestly."""

    origin: str
    text: str
    line_map: tuple[int, ...] | None = None
    raw: str | None = None
    """The document as the author wrote it, for showing a line back to them."""

    def line_of(self, origin_line: int) -> str:
        """The author's own line, for a caret under a diagnostic."""
        document = self.raw if self.raw is not None else self.text
        lines = document.split("\n")
        return lines[origin_line - 1] if 1 <= origin_line <= len(lines) else ""

    def origin_line(self, line: int) -> int:
        if self.line_map is None:
            return line
        if 1 <= line <= len(self.line_map):
            return self.line_map[line - 1]
        return self.line_map[-1] if self.line_map else line

    def where(self, line: int, column: int) -> str:
        """Format a position in terms of the file the author edits."""
        return f"{self.origin}:{self.origin_line(line)}:{column}"


def load(path: str | Path) -> Source:
    """Read game source from any of its three forms.

    `.game` is raw source, `.md` is the canonical literate form, and `.png` is
    a cartridge carrying that markdown.
    """
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix == ".game":
        text = path.read_text(encoding="utf-8")
        return Source(origin=path.name, text=text, raw=text)

    if suffix in (".md", ".markdown"):
        return _from_markdown(path.name, path.read_text(encoding="utf-8"))

    if suffix == ".png":
        markdown = png_mod.unpack(path.read_bytes())
        return _from_markdown(path.name, markdown)

    raise ValueError(f"not a game source file: {path.name} (expected .game, .md or .png)")


def _from_markdown(origin: str, markdown: str) -> Source:
    tangled = tangle(markdown)
    return Source(origin=origin, text=tangled.text,
                  line_map=tangled.line_map, raw=markdown)
