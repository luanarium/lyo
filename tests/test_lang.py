"""The language pipeline: tangle, pack, load, parse -- and honest positions."""

from pathlib import Path

import pytest
from lark.exceptions import UnexpectedInput

from lyo.cartridge import png as png_mod
from lyo.cartridge.markdown import tangle
from lyo.lang.parser import parse
from lyo.lang.source import load

FIXTURES = Path(__file__).parent / "fixtures"
DECLARATIONS = (
    "game location monster item class spell track verb flow offer rules shop"
).split()


def test_every_declaration_parses():
    tree = parse((FIXTURES / "all_declarations.game").read_text())
    kinds = {c.children[0].data for c in tree.children}
    missing = [d for d in DECLARATIONS if f"{d}_decl" not in kinds]
    assert not missing, f"declarations that did not parse: {missing}"


def test_positions_propagate():
    tree = parse((FIXTURES / "all_declarations.game").read_text())
    first = tree.children[0]
    assert first.meta.line == 3, "the game declaration starts on line 3"


def test_tangle_ignores_prose_and_other_languages():
    md = (FIXTURES / "literate.md").read_text()
    tangled = tangle(md)
    assert 'print("not game source")' not in tangled.text
    assert "Prose between blocks" not in tangled.text
    assert tangled.text.count("location ") == 2
    assert "monster " in tangled.text


def test_tangle_maps_lines_back_to_the_markdown():
    md = (FIXTURES / "literate.md").read_text()
    tangled = tangle(md)
    needle = 'monster "Goblin Scout":'

    expected = md.split("\n").index(needle) + 1
    got = tangled.text.split("\n").index(needle) + 1
    assert tangled.origin_line(got) == expected


def test_markdown_source_parses():
    source = load(FIXTURES / "literate.md")
    assert len(parse(source.text).children) == 3


def test_cartridge_roundtrip_and_parse(tmp_path):
    md = (FIXTURES / "literate.md").read_text()
    cart = tmp_path / "oakhaven.png"
    cart.write_bytes(png_mod.pack(png_mod.blank(), md))

    assert png_mod.unpack(cart.read_bytes()) == md
    source = load(cart)
    assert len(parse(source.text).children) == 3


def test_cartridge_is_still_a_valid_png(tmp_path):
    cart = png_mod.pack(png_mod.blank(), "# empty\n")
    assert cart.startswith(png_mod.SIGNATURE)
    kinds = [kind for _, kind, _ in png_mod._walk(cart)]
    #  tEXt is the generated-label mark, ancillary and legal anywhere between
    #  IHDR and IEND. The payload stays immediately before IEND.
    assert kinds == [b"IHDR", b"tEXt", b"IDAT", b"gaMe", b"IEND"]
    assert kinds[0] == b"IHDR" and kinds[-1] == b"IEND"


def test_repacking_replaces_rather_than_appends():
    once = png_mod.pack(png_mod.blank(), "# one\n")
    twice = png_mod.pack(once, "# two\n")
    assert png_mod.unpack(twice) == "# two\n"
    assert [k for _, k, _ in png_mod._walk(twice)].count(b"gaMe") == 1


def test_tampering_is_detected():
    cart = bytearray(png_mod.pack(png_mod.blank(), "# one\n"))
    offset = cart.find(b"gaMe") + 4 + 40  # into the compressed payload
    cart[offset] ^= 0xFF
    with pytest.raises(png_mod.CartridgeError):
        png_mod.unpack(bytes(cart))


def test_plain_png_reports_why_it_has_no_payload():
    with pytest.raises(png_mod.CartridgeError, match="re-encoded"):
        png_mod.unpack(png_mod.blank())


def test_error_in_a_cartridge_points_at_the_markdown_line(tmp_path):
    """The convention 8 claim: PNG -> markdown -> block, to a real line."""
    md = (FIXTURES / "literate.md").read_text().split("\n")
    broken_line = md.index("  12 hp, 3 str, 7 agi, 2 int")
    md[broken_line] = "  12 hp, 3 str, @@@"
    broken_column = md[broken_line].index("@") + 1
    markdown = "\n".join(md)

    cart = tmp_path / "broken.png"
    cart.write_bytes(png_mod.pack(png_mod.blank(), markdown))
    source = load(cart)

    with pytest.raises(UnexpectedInput) as caught:
        parse(source.text)

    assert source.where(caught.value.line, caught.value.column) == (
        f"broken.png:{broken_line + 1}:{broken_column}"
    )


WORLD = Path(__file__).parent.parent / "world"


def test_shipped_world_parses():
    source = load(WORLD / "kairos.md")
    tree = parse(source.text)
    assert len(tree.children) == 76

    kinds = {c.children[0].data for c in tree.children}
    missing = [d for d in DECLARATIONS if f"{d}_decl" not in kinds]
    assert not missing, f"kairos.md never exercises: {missing}"


def test_shipped_world_packs_into_a_cartridge(tmp_path):
    markdown = (WORLD / "kairos.md").read_text()
    cart = tmp_path / "kairos.png"
    cart.write_bytes(png_mod.pack(png_mod.blank(), markdown))

    assert len(parse(load(cart).text).children) == 76
    assert cart.stat().st_size < 60_000, "a cartridge should stay small"


# ------------------------------------------------- generated labels

def test_a_generated_label_is_marked_as_a_placeholder():
    """`pack` without art draws a featureless square; a reader showing covers
    should be able to tell and draw something better."""
    assert png_mod.is_placeholder(png_mod.blank())
    assert not png_mod.is_placeholder(b"not a png at all")


def test_the_mark_survives_being_packed_onto(tmp_path):
    markdown = (WORLD / "kairos.md").read_text()
    assert png_mod.is_placeholder(png_mod.pack(png_mod.blank(), markdown))


def test_chosen_art_is_never_a_placeholder():
    #  a PNG of our own making, but without the mark
    import struct
    import zlib

    width = height = 8
    raw = b"".join(b"\x00" + bytes((200, 40, 90)) * width for _ in range(height))
    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
    art = (png_mod.SIGNATURE
           + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))

    assert not png_mod.is_placeholder(art)
    markdown = (WORLD / "kairos.md").read_text()
    assert not png_mod.is_placeholder(png_mod.pack(art, markdown))
    assert png_mod.unpack(png_mod.pack(art, markdown)) == markdown


def test_the_mark_does_not_masquerade_as_a_payload():
    """A text chunk is only a payload candidate if it carries the magic, so a
    marked label with no game still reports the useful error."""
    with pytest.raises(png_mod.CartridgeError, match="re-encoded"):
        png_mod.unpack(png_mod.blank())


def test_unrelated_text_metadata_is_ignored(tmp_path):
    import struct
    import zlib

    #  the sort of comment a camera or an editor leaves behind
    noise = png_mod._text(b"Comment", b"exported by something else")
    blank = png_mod.blank()
    at = blank.index(b"IDAT") - 4
    carrying = blank[:at] + noise + blank[at:]

    with pytest.raises(png_mod.CartridgeError, match="re-encoded"):
        png_mod.unpack(carrying)

    markdown = (WORLD / "kairos.md").read_text()
    assert png_mod.unpack(png_mod.pack(carrying, markdown)) == markdown


def test_the_cover_convention_is_the_default_label_size():
    """630x500 is itch.io's cover size, not one invented here."""
    assert png_mod.COVER == (630, 500)
    assert png_mod.dimensions(png_mod.blank()) == png_mod.COVER

    markdown = (WORLD / "kairos.md").read_text()
    packed = png_mod.pack(png_mod.blank(), markdown)
    assert png_mod.dimensions(packed) == png_mod.COVER, "packing keeps the label"


def test_dimensions_needs_no_decoding_and_tolerates_rubbish():
    assert png_mod.dimensions(png_mod.blank(123, 45)) == (123, 45)
    assert png_mod.dimensions(b"not a png") is None
    assert png_mod.dimensions(b"") is None


def test_art_of_any_shape_is_kept_byte_for_byte():
    """Resizing would need an imaging library and lose the original."""
    import struct
    import zlib

    width, height = 240, 240
    raw = b"".join(b"\x00" + bytes((200, 40, 90)) * width for _ in range(height))

    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    art = (png_mod.SIGNATURE
           + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))

    markdown = (WORLD / "kairos.md").read_text()
    packed = png_mod.pack(art, markdown)
    assert png_mod.dimensions(packed) == (240, 240), "not resized to the cover"
    #  the image data is the same bytes, so the picture is untouched
    original = [d for _, k, d in png_mod._walk(art) if k == b"IDAT"]
    carried = [d for _, k, d in png_mod._walk(packed) if k == b"IDAT"]
    assert original == carried
    assert png_mod.unpack(packed) == markdown

