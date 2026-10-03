"""Tangle a literate markdown game: extract its fenced `game` blocks.

The line map is the point of this module. A game's canonical form is markdown,
so every position the parser reports has to be translated back to the line the
author actually sees in their editor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_FENCE = re.compile(r"^(?P<indent>[ \t]*)(?P<fence>`{3,}|~{3,})[ \t]*(?P<info>[^\s`~]*)[ \t]*$")


@dataclass(frozen=True)
class Tangled:
    """Extracted source, plus the original line number of each of its lines."""

    text: str
    line_map: tuple[int, ...]

    def origin_line(self, tangled_line: int) -> int:
        """Translate a 1-based tangled line to its 1-based markdown line."""
        if 1 <= tangled_line <= len(self.line_map):
            return self.line_map[tangled_line - 1]
        return self.line_map[-1] if self.line_map else 1


def tangle(markdown: str, lang: str = "game") -> Tangled:
    """Concatenate every ```lang block, in document order."""
    out: list[str] = []
    lines: list[int] = []
    fence: tuple[str, int] | None = None  # (fence chars, indent width)

    for number, line in enumerate(markdown.split("\n"), start=1):
        match = _FENCE.match(line)
        if fence is None:
            if match and match["info"] == lang:
                fence = (match["fence"], len(match["indent"].expandtabs(4)))
            continue
        # Inside a block: a bare fence of the same kind and at least as long closes it.
        if (
            match
            and not match["info"]
            and match["fence"][0] == fence[0][0]
            and len(match["fence"]) >= len(fence[0])
        ):
            fence = None
            continue
        out.append(_dedent(line, fence[1]))
        lines.append(number)

    return Tangled("\n".join(out) + "\n" if out else "", tuple(lines))


def _dedent(line: str, width: int) -> str:
    """Drop up to `width` columns of leading whitespace, for fences inside lists."""
    if width <= 0:
        return line
    expanded = line.expandtabs(4)
    stripped = expanded[:width].lstrip()
    return stripped + expanded[width:] if not stripped else expanded
