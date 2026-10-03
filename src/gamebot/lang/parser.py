"""Parse game source into a positioned tree.

Every node carries (line, column) because convention 8 requires an error to
resolve back through PNG -> markdown -> code block to a real location in the
file the author actually edited.
"""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files

from lark import Lark, Tree
from lark.indenter import Indenter


class GameIndenter(Indenter):
    """Turn leading whitespace into _INDENT / _DEDENT tokens."""

    NL_type = "_NL"
    OPEN_PAREN_types = ["LPAR"]
    CLOSE_PAREN_types = ["RPAR"]
    INDENT_type = "_INDENT"
    DEDENT_type = "_DEDENT"
    tab_len = 8


def grammar_text() -> str:
    return (files("gamebot.lang.grammar") / "game.lark").read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def parser() -> Lark:
    """Build the LALR(1) parser once and reuse it."""
    return Lark(
        grammar_text(),
        parser="lalr",
        postlex=GameIndenter(),
        propagate_positions=True,
        maybe_placeholders=True,
    )


def parse(source: str) -> Tree:
    """Parse game source. A trailing newline is required by the indenter."""
    if not source.endswith("\n"):
        source += "\n"
    return parser().parse(source)
