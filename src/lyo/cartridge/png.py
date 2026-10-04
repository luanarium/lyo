"""PNG cartridges: a game's markdown source carried inside a PNG.

The payload lives in a private ancillary chunk (`gaMe`), which the PNG spec
reserves for exactly this and which every decoder ignores, so the file stays a
perfectly ordinary image whose visible pixels are the cartridge label.

stdlib only: no imaging library is needed to read or write a chunk.
"""

from __future__ import annotations

import hashlib
import struct
import zlib

SIGNATURE = b"\x89PNG\r\n\x1a\n"
CHUNK = b"gaMe"
MAGIC = b"GBC1"

#  A label this module drew itself, rather than art someone chose. Marked so a
#  reader can tell the difference and draw something better than a blank
#  square; the mark is copied into any cartridge packed onto it.
LABEL = b"lyo-label"
PLACEHOLDER = b"placeholder"

#  The cover convention, borrowed from itch.io rather than invented: 630x500,
#  which is the shape people already draw game covers in. Nothing enforces it
#  -- `pack` keeps whatever art it is given, byte for byte -- but a cover that
#  matches it is shown without letterboxing.
COVER = (630, 500)
#  Read these too: other tools write text into the standard chunks.
TEXT_CHUNKS = (b"tEXt", b"zTXt", b"iTXt")


class CartridgeError(Exception):
    """A PNG carried no readable cartridge payload."""


def _text(keyword: bytes, value: bytes) -> bytes:
    """A tEXt chunk: a Latin-1 keyword, a null, then the value."""
    return _chunk(b"tEXt", keyword + b"\x00" + value)


def _chunk(kind: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)


def _walk(png: bytes):
    if not png.startswith(SIGNATURE):
        raise CartridgeError("not a PNG file")
    offset = len(SIGNATURE)
    while offset + 12 <= len(png):
        (length,) = struct.unpack(">I", png[offset : offset + 4])
        kind = png[offset + 4 : offset + 8]
        yield offset, kind, png[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if kind == b"IEND":
            return


def pack(png: bytes, source: str) -> bytes:
    """Return `png` with `source` embedded, replacing any existing payload."""
    payload = source.encode("utf-8")
    body = MAGIC + hashlib.sha256(payload).digest() + zlib.compress(payload, 9)

    rebuilt, inserted = bytearray(SIGNATURE), False
    for _, kind, data in _walk(png):
        if kind == CHUNK:
            continue  # drop the old payload
        if kind == b"IEND" and not inserted:
            rebuilt += _chunk(CHUNK, body)
            inserted = True
        rebuilt += _chunk(kind, data)
    if not inserted:
        raise CartridgeError("PNG has no IEND chunk")
    return bytes(rebuilt)


def unpack(png: bytes) -> str:
    """Extract the markdown source from a cartridge."""
    found = None
    for _, kind, data in _walk(png):
        if kind == CHUNK:
            found = data
            break
        #  A payload may have been written into a text chunk by an older
        #  version or another tool. Require the magic, so unrelated metadata --
        #  a camera's comment, this module's own label mark -- is not mistaken
        #  for a payload and reported as a corrupt one.
        if kind in TEXT_CHUNKS and found is None:
            at = data.find(MAGIC)
            if at >= 0:
                found = data[at:]

    if found is None:
        raise CartridgeError(
            "no cartridge payload in this PNG -- it may have been re-encoded, "
            "which strips the chunk. Distribute cartridges as files, not as "
            "images posted through services that recompress them."
        )
    if not found.startswith(MAGIC):
        raise CartridgeError("cartridge payload is not in a format this version reads")

    digest, compressed = found[4:36], found[36:]
    try:
        payload = zlib.decompress(compressed)
    except zlib.error as exc:
        raise CartridgeError(f"cartridge payload is corrupt: {exc}") from exc
    if hashlib.sha256(payload).digest() != digest:
        raise CartridgeError("cartridge checksum mismatch: the payload was altered")
    return payload.decode("utf-8")


def dimensions(png: bytes) -> tuple[int, int] | None:
    """A PNG's pixel size, read from IHDR without decoding the image."""
    try:
        for _, kind, data in _walk(png):
            if kind == b"IHDR" and len(data) >= 8:
                return struct.unpack(">II", data[:8])
    except CartridgeError:
        return None
    return None


def blank(width: int = COVER[0], height: int = COVER[1],
          rgb: tuple[int, int, int] = (26, 22, 37)) -> bytes:
    """A plain PNG, so `pack` has something to write into when no art is given.

    Marked as a placeholder, so anything showing cartridge covers can draw its
    own thing rather than a featureless square.
    """
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))
    return (
        SIGNATURE
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _text(LABEL, PLACEHOLDER)
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )


def is_placeholder(png: bytes) -> bool:
    """Whether this PNG's picture is one `blank` drew, not art someone chose."""
    try:
        for _, kind, data in _walk(png):
            if kind == b"tEXt" and data.split(b"\x00", 1)[0] == LABEL:
                return data.split(b"\x00", 1)[1:] == [PLACEHOLDER]
    except CartridgeError:
        return False
    return False
