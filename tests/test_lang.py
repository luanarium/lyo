"""The language pipeline: tangle, pack, load, parse -- and honest positions."""

from pathlib import Path

import pytest
from lark.exceptions import UnexpectedInput

from gamebot.cartridge import png as png_mod
from gamebot.cartridge.markdown import tangle
from gamebot.lang.parser import parse
from gamebot.lang.source import load

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
    assert kinds == [b"IHDR", b"IDAT", b"gaMe", b"IEND"]


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
    assert len(tree.children) == 74

    kinds = {c.children[0].data for c in tree.children}
    missing = [d for d in DECLARATIONS if f"{d}_decl" not in kinds]
    assert not missing, f"kairos.md never exercises: {missing}"


def test_shipped_world_packs_into_a_cartridge(tmp_path):
    markdown = (WORLD / "kairos.md").read_text()
    cart = tmp_path / "kairos.png"
    cart.write_bytes(png_mod.pack(png_mod.blank(), markdown))

    assert len(parse(load(cart).text).children) == 74
    assert cart.stat().st_size < 60_000, "a cartridge should stay small"
