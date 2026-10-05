"""Environment files, for a host that already keeps the token in one.

The usual way to hand a discord.py bot its token is a `.env` file and
python-dotenv; the Kairos bot this engine replaces kept one *above* its own
folder. So a token that already works on a machine should work here without
being retyped into configuration, which is why `lyo run` reads a `.env` beside
the project -- or one directory up -- before it asks for `adapter.<name>.token`.

Reading it is a dozen lines of stdlib, so there is no dependency here. The
supported shape is the shape those files actually have:

    # a comment
    DISCORD_TOKEN=abc.def        # and a trailing one
    export PREFIX="!"            # quoted, and `export`-prefixed

A `.env` ranks below committed configuration: the file is what a host happens
to have lying around, `lyo set` is what its operator chose. An exported
variable still outranks both, being the most immediate of the three.
"""

from __future__ import annotations

from pathlib import Path

NAME = ".env"

_QUOTES = ("'", '"')
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "'": "'"}


def parse(text: str) -> dict[str, str]:
    """The assignments in one environment file, in document order."""
    values: dict[str, str] = {}
    for line in text.lstrip("﻿").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        name, separator, value = line.partition("=")
        name = name.strip()
        #  Anything that is not a plain assignment -- shell syntax, a stray
        #  word -- is skipped rather than guessed at.
        if not separator or not name.replace("_", "").isalnum():
            continue
        values[name] = _value(value.strip())
    return values


def _value(raw: str) -> str:
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in _QUOTES:
        inner = raw[1:-1]
        #  Single quotes are literal, as in a shell; double quotes unescape.
        return _unescape(inner) if raw[0] == '"' else inner
    #  Unquoted: a `#` after whitespace starts a comment, as python-dotenv has it.
    for index in range(len(raw) - 1):
        if raw[index].isspace() and raw[index + 1] == "#":
            return raw[:index].rstrip()
    return raw


def _unescape(text: str) -> str:
    out, index = [], 0
    while index < len(text):
        character = text[index]
        if character == "\\" and index + 1 < len(text):
            following = text[index + 1]
            if following in _ESCAPES:
                out.append(_ESCAPES[following])
                index += 2
                continue
        out.append(character)
        index += 1
    return "".join(out)


def candidates(*anchors: Path) -> list[Path]:
    """Where to look for a `.env`: each anchor directory, then its parent.

    The parent is there because that is where the bot this replaces kept its
    own, and because a token shared by a few projects tends to sit one level up.
    """
    seen: dict[Path, None] = {}
    for anchor in anchors:
        directory = anchor if anchor.is_dir() else anchor.parent
        try:
            directory = directory.resolve()
        except OSError:  # pragma: no cover - an unreadable path
            continue
        for place in (directory, directory.parent):
            seen.setdefault(place / NAME, None)
    return list(seen)


def read(*anchors: Path) -> dict[str, tuple[str, Path]]:
    """Every name found, mapped to its value and the file it came from.

    Keys are matched case-insensitively -- these files are uppercase by
    convention -- and the nearest file wins, so a project's own `.env`
    overrides a shared one above it.
    """
    found: dict[str, tuple[str, Path]] = {}
    for path in candidates(*anchors):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            #  Missing, a directory, or not ours to read: not an error. The
            #  token simply is not here, and the caller says where it looked.
            continue
        for name, value in parse(text).items():
            found.setdefault(name.upper(), (value, path))
    return found
