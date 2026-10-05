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


def from_bytes(name: str, data: bytes) -> Source:
    """Read game source from bytes, as an upload arrives.

    A cartridge is recognised by its signature rather than its name, since
    nothing guarantees what a browser calls the file it hands over.

    Line endings are normalised here, which reading a path gets for free.
    A document written on Windows arrives with CRLF, and a fence is matched as
    a whole line, so the carriage return left one unrecognised: the upload was
    refused for having no `game` blocks at all, in a file that lints perfectly
    well from disk.
    """
    if data.startswith(png_mod.SIGNATURE):
        return _from_markdown(name, png_mod.unpack(data))
    try:
        text = _newlines(data.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"{name} is neither a PNG cartridge nor UTF-8 text") from exc
    if name.lower().endswith(".game"):
        return Source(origin=name, text=text, raw=text)
    return _from_markdown(name, text)


def _newlines(text: str) -> str:
    """What opening a file in text mode would have done."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _from_markdown(origin: str, markdown: str) -> Source:
    #  `raw` is shown back under a caret, so it has to be the same text the
    #  line map counted: normalise once, and use it for both.
    markdown = _newlines(markdown)
    tangled = tangle(markdown)
    return Source(origin=origin, text=tangled.text,
                  line_map=tangled.line_map, raw=markdown)
