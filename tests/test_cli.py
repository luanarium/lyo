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


# ------------------------------------------------------------ the store

def test_state_reports_when_there_is_no_file(tmp_path):
    result = run("state", "--db", tmp_path / "missing.db")
    assert result.exit_code != 0
    assert "no such file" in result.output


def test_state_saves_and_shows(tmp_path):
    db = tmp_path / "gamebot.db"
    assert run("state", "Store landed; UCI next.", "--db", db).exit_code == 0
    assert "Store landed; UCI next." in run("state", "--db", db).output


def test_state_shows_a_history(tmp_path):
    db = tmp_path / "gamebot.db"
    for note in ("one", "two", "three"):
        run("state", note, "--db", db)
    out = run("state", "--history", "2", "--db", db).output
    assert "two" in out and "three" in out and "one" not in out


def test_there_is_no_log_or_discard_command():
    """Dropped as redundant to git."""
    assert "No such command" in run("log").output
    assert "No such command" in run("discard", "x", "--why", "y").output


def test_run_check_with_a_store(tmp_path):
    db = tmp_path / "gamebot.db"
    from gamebot.engine import Engine
    from gamebot.lang.check import check as check_source
    from gamebot.store import Store

    with Store(db) as store:
        Engine(check_source(KAIROS).world, store=store).register(
            "1", "Brynn", "Warrior")

    result = run("run", KAIROS, "--check", "-s", "discord.token=fake", "--db", db)
    assert result.exit_code == 0
    assert "checks passed" in result.output


# ----------------------------------------------------------- config (UCI)

def test_set_stages_and_commit_applies(tmp_path):
    db = tmp_path / "gamebot.db"
    out = run("set", "adapter.discord.token=abc", "--db", db).output
    assert "~ adapter.discord.token='abc'" in out
    assert "1 staged" in out

    assert "adapter.discord.token" in run("changes", "--db", db).output
    assert run("commit", "--db", db).output.count("committed") == 1
    assert run("get", "adapter.discord.token", "--db", db).output.strip() == "abc"
    assert "no staged changes" in run("changes", "--db", db).output


def test_get_an_unset_option_fails(tmp_path):
    db = tmp_path / "gamebot.db"
    result = run("get", "adapter.discord.token", "--db", db)
    assert result.exit_code != 0 and "is not set" in result.output


def test_a_malformed_path_is_explained(tmp_path):
    db = tmp_path / "gamebot.db"
    result = run("get", "discord.token", "--db", db)
    assert result.exit_code != 0
    assert "package.section.option" in result.output


def test_show_output_can_be_piped_back_into_set(tmp_path):
    db, other = tmp_path / "a.db", tmp_path / "b.db"
    run("set", "adapter.discord.token=abc", "adapter.discord.prefix=?", "--db", db)
    run("commit", "--db", db)
    shown = run("show", "--db", db).output

    import click.testing
    result = click.testing.CliRunner().invoke(
        main, ["set", "-", "--db", str(other)], input=shown)
    assert result.exit_code == 0
    run("commit", "--db", other)
    assert run("get", "adapter.discord.token", "--db", other).output.strip() == "abc"


def test_revert_and_delete(tmp_path):
    db = tmp_path / "gamebot.db"
    run("set", "adapter.discord.prefix=!", "--db", db)
    run("commit", "--db", db)

    run("set", "adapter.discord.prefix=?", "--db", db)
    assert "1 reverted" in run("revert", "--db", db).output
    assert run("get", "adapter.discord.prefix", "--db", db).output.strip() == "!"

    assert "staged for removal" in run("delete", "adapter.discord.prefix",
                                       "--db", db).output
    run("commit", "--db", db)
    assert "nothing configured" in run("show", "--db", db).output


def test_run_reads_committed_configuration(tmp_path):
    db = tmp_path / "gamebot.db"
    run("set", f"game.main.source={KAIROS}", "--db", db)
    run("set", "adapter.discord.token=abc", "--db", db)

    staged = run("run", "--check", "--db", db)
    assert staged.exit_code != 0, "staged settings are not live"
    assert "gamebot commit" in staged.output

    run("commit", "--db", db)
    committed = run("run", "--check", "--db", db)
    assert committed.exit_code == 0, committed.output
    assert "Kairos" in committed.output


def test_a_flag_overrides_configuration(tmp_path):
    db = tmp_path / "gamebot.db"
    run("set", "adapter.main.name=nosuchadapter", "--db", db)
    run("commit", "--db", db)
    assert "no adapter called" in run("run", KAIROS, "--check", "--db", db).output
    assert run("run", KAIROS, "--check", "-a", "discord",
               "-s", "discord.token=x", "--db", db).exit_code == 0


def test_adapters_advertises_uci_paths():
    out = run("adapters").output
    assert "adapter.discord.token" in out
    assert "gamebot set adapter.<name>.<key>=<value>" in out
