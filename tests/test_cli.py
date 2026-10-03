"""The CLI surface: lint, tangle, pack, unpack."""

from pathlib import Path

from click.testing import CliRunner

from gamebot.cli import main

WORLD = Path(__file__).parent.parent / "world"
KAIROS = WORLD / "kairos.md"


def run(*args):
    return CliRunner().invoke(main, [str(a) for a in args])


def test_lint_defaults_to_the_world_directory():
    result = run("lint", "--stats")
    assert result.exit_code == 0, result.output
    assert "Kairos" in result.output
    assert "0 errors" in result.output


def test_lint_can_hide_warnings():
    result = run("lint", KAIROS, "--no-warnings")
    assert result.exit_code == 0
    assert "warning" not in result.output


def test_lint_fails_and_suggests_on_a_bad_name(tmp_path):
    broken = tmp_path / "broken.md"
    broken.write_text(
        KAIROS.read_text().replace('spawns "Goblin Scout"', 'spawns "Goblin Scowt"')
    )
    result = run("lint", broken)
    assert result.exit_code == 1
    assert 'did you mean "Goblin Scout"' in result.output
    assert "^" in result.output, "a caret should point at the column"


def test_lint_reads_a_cartridge(tmp_path):
    cart = tmp_path / "kairos.png"
    assert run("pack", KAIROS, "-o", cart).exit_code == 0
    result = run("lint", cart, "--stats")
    assert result.exit_code == 0
    assert "6 locations" in result.output


def test_pack_refuses_a_source_that_does_not_resolve(tmp_path):
    broken = tmp_path / "broken.md"
    broken.write_text(
        KAIROS.read_text().replace('spawns "Goblin Scout"', 'spawns "Goblin Scowt"')
    )
    result = run("pack", broken, "-o", tmp_path / "out.png")
    assert result.exit_code != 0
    assert "refusing to pack" in result.output
    assert not (tmp_path / "out.png").exists()


def test_pack_and_unpack_round_trip(tmp_path):
    cart, back = tmp_path / "k.png", tmp_path / "k.md"
    assert run("pack", KAIROS, "-o", cart).exit_code == 0
    assert run("unpack", cart, "-o", back).exit_code == 0
    assert back.read_text() == KAIROS.read_text()


def test_unpack_explains_a_plain_png(tmp_path):
    from gamebot.cartridge.png import blank

    plain = tmp_path / "plain.png"
    plain.write_bytes(blank())
    result = run("unpack", plain)
    assert result.exit_code != 0
    assert "re-encoded" in result.output


def test_tangle_writes_only_source(tmp_path):
    out = tmp_path / "k.game"
    assert run("tangle", KAIROS, "-o", out).exit_code == 0
    text = out.read_text()
    assert text.startswith('game "Kairos":')
    assert "<details>" not in text
    assert run("lint", out, "--no-warnings").exit_code == 0


def test_tangle_rejects_a_document_with_no_blocks(tmp_path):
    empty = tmp_path / "prose.md"
    empty.write_text("# Just prose\n\nNothing fenced here.\n")
    result = run("tangle", empty)
    assert result.exit_code != 0
    assert "no `game` code blocks" in result.output
