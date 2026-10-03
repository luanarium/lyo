"""A unit of game source, and where each of its lines really came from."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from gamebot.cartridge import png as png_mod
from gamebot.cartridge.markdown import tangle


@dataclass(frozen=True)
class Source:
    """Parseable text, plus enough provenance to report a position honestly."""

    origin: str
    text: str
    line_map: tuple[int, ...] | None = None

    def where(self, line: int, column: int) -> str:
        """Format a position in terms of the file the author edits."""
        if self.line_map is not None:
            if 1 <= line <= len(self.line_map):
                line = self.line_map[line - 1]
            elif self.line_map:
                line = self.line_map[-1]
        return f"{self.origin}:{line}:{column}"


def load(path: str | Path) -> Source:
    """Read game source from any of its three forms.

    `.game` is raw source, `.md` is the canonical literate form, and `.png` is
    a cartridge carrying that markdown.
    """
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix == ".game":
        return Source(origin=path.name, text=path.read_text(encoding="utf-8"))

    if suffix in (".md", ".markdown"):
        return _from_markdown(path.name, path.read_text(encoding="utf-8"))

    if suffix == ".png":
        markdown = png_mod.unpack(path.read_bytes())
        inner = _from_markdown(path.name, markdown)
        return Source(origin=inner.origin, text=inner.text, line_map=inner.line_map)

    raise ValueError(f"not a game source file: {path.name} (expected .game, .md or .png)")


def _from_markdown(origin: str, markdown: str) -> Source:
    tangled = tangle(markdown)
    return Source(origin=origin, text=tangled.text, line_map=tangled.line_map)
