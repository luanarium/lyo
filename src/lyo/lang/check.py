"""Read, parse and resolve one game source, reporting rather than raising."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lark.exceptions import UnexpectedInput

from lyo.cartridge.png import CartridgeError
from lyo.lang.model import World
from lyo.lang.parser import parse
from lyo.lang.resolve import ERROR, Diagnostic, resolve
from lyo.lang.source import Source, from_bytes, load

SUFFIXES = (".md", ".markdown", ".game", ".png")


@dataclass
class Report:
    """Everything one check produced, whether or not it got far."""

    path: Path
    source: Source | None
    world: World | None
    diagnostics: list[Diagnostic]

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == ERROR]

    @property
    def ok(self) -> bool:
        return not self.errors


def check(path: str | Path) -> Report:
    """Check one source. A failure to even read it is itself a diagnostic."""
    path = Path(path)
    try:
        source = load(path)
    except (CartridgeError, ValueError, OSError) as exc:
        return Report(path, None, None,
                      [Diagnostic(ERROR, "unreadable", str(exc), 1, 1)])
    return check_source(source, path)


def check_bytes(name: str, data: bytes) -> Report:
    """Check a gameworld that arrived as bytes rather than a path."""
    try:
        source = from_bytes(name, data)
    except (CartridgeError, ValueError) as exc:
        return Report(Path(name), None, None,
                      [Diagnostic(ERROR, "unreadable", str(exc), 1, 1)])
    return check_source(source, Path(name))


def check_source(source: Source, path: Path | None = None) -> Report:
    """Parse and resolve an already-read source."""
    path = path or Path(source.origin)
    if not source.text.strip():
        return Report(path, source, None,
                      [Diagnostic(ERROR, "empty",
                                  "no `game` code blocks found in this document", 1, 1)])


    try:
        tree = parse(source.text)
    except UnexpectedInput as exc:
        message = str(exc).split("\n")[0].strip()
        return Report(path, source, None,
                      [Diagnostic(ERROR, "syntax", message,
                                  getattr(exc, "line", 1) or 1,
                                  getattr(exc, "column", 1) or 1)])

    resolution = resolve(tree, source)
    return Report(path, source, resolution.world, resolution.diagnostics)


def sources_in(path: str | Path) -> list[Path]:
    """One file, or every game source directly inside a directory."""
    path = Path(path)
    if path.is_dir():
        return sorted(p for p in path.iterdir()
                      if p.is_file() and p.suffix.lower() in SUFFIXES)
    return [path]
