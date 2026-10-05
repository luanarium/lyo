"""Environment files: the token where a host already keeps it."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from lyo import env
from lyo.cli import _env_names, main

WORLD = Path(__file__).parent.parent / "world"
KAIROS = WORLD / "kairos.md"


def run(*args, **kwargs):
    return CliRunner().invoke(main, [str(a) for a in args], **kwargs)


@pytest.fixture
def elsewhere(tmp_path, monkeypatch):
    """Run from a temp directory: a real .env must not reach these tests."""
    monkeypatch.chdir(tmp_path)
    for name in ("DISCORD_TOKEN", "LYO_DISCORD_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


# ------------------------------------------------------------- the parser

def test_a_plain_assignment():
    assert env.parse("DISCORD_TOKEN=abc.def") == {"DISCORD_TOKEN": "abc.def"}


def test_comments_blank_lines_and_export_are_handled():
    assert env.parse(
        "\n# a comment\nexport DISCORD_TOKEN=abc\n\n"
    ) == {"DISCORD_TOKEN": "abc"}


def test_quotes_come_off_and_double_quotes_unescape():
    parsed = env.parse('A="one\\ntwo"\nB=\'literal\\n\'\n')
    assert parsed == {"A": "one\ntwo", "B": "literal\\n"}


def test_a_trailing_comment_is_dropped_but_a_hash_in_a_token_is_not():
    assert env.parse("A=abc # mine")["A"] == "abc"
    assert env.parse("A=abc#def")["A"] == "abc#def"


def test_lines_that_are_not_assignments_are_skipped():
    assert env.parse("just words\ncd somewhere\nA=1") == {"A": "1"}


def test_a_byte_order_mark_does_not_hide_the_first_name():
    #  A .env saved by Notepad on the brother's machine starts with one.
    assert env.parse("﻿DISCORD_TOKEN=abc") == {"DISCORD_TOKEN": "abc"}


# ------------------------------------------------------------ where it looks

def test_it_looks_beside_the_anchor_and_one_directory_up(tmp_path):
    project = tmp_path / "lyo"
    project.mkdir()
    places = env.candidates(project)
    assert places[0] == project / ".env"
    assert tmp_path / ".env" in places


def test_a_file_above_is_read_and_the_nearer_one_wins(tmp_path):
    project = tmp_path / "lyo"
    project.mkdir()
    (tmp_path / ".env").write_text("DISCORD_TOKEN=above\nOWNER=7\n")
    (project / ".env").write_text("DISCORD_TOKEN=beside\n")

    found = env.read(project)
    assert found["DISCORD_TOKEN"] == ("beside", project / ".env")
    assert found["OWNER"] == ("7", tmp_path / ".env")


def test_nothing_to_read_is_not_an_error(tmp_path):
    assert env.read(tmp_path) == {}


def test_a_name_is_matched_case_insensitively(tmp_path):
    (tmp_path / ".env").write_text("discord_token=abc\n")
    assert env.read(tmp_path)["DISCORD_TOKEN"][0] == "abc"


# ------------------------------------------------------- the settings chain

def test_a_setting_answers_to_both_name_shapes():
    #  The bare name is the one every discord.py bot already uses.
    assert _env_names("discord", "token") == ("LYO_DISCORD_TOKEN",
                                              "DISCORD_TOKEN")


def test_run_takes_the_token_from_a_dot_env(elsewhere):
    db = elsewhere / "lyo.db"
    (elsewhere / ".env").write_text("DISCORD_TOKEN=from-the-file\n")

    result = run("run", KAIROS, "--check", "--db", db)
    assert result.exit_code == 0, result.output
    assert "checks passed" in result.output
    assert "token (hidden) from DISCORD_TOKEN in" in result.output
    assert "from-the-file" not in result.output, "a secret is never printed"


def test_configuration_outranks_a_dot_env(elsewhere):
    db = elsewhere / "lyo.db"
    (elsewhere / ".env").write_text("DISCORD_TOKEN=from-the-file\n")
    run("set", "adapter.discord.token=chosen", "--db", db)
    run("commit", "--db", db)

    result = run("run", KAIROS, "--check", "--db", db)
    assert "token (hidden) from adapter.discord.token" in result.output


def test_the_environment_outranks_configuration(elsewhere, monkeypatch):
    db = elsewhere / "lyo.db"
    run("set", "adapter.discord.token=chosen", "--db", db)
    run("commit", "--db", db)
    monkeypatch.setenv("DISCORD_TOKEN", "exported")

    result = run("run", KAIROS, "--check", "--db", db)
    assert "token (hidden) from $DISCORD_TOKEN" in result.output


def test_the_prefixed_name_outranks_the_bare_one(elsewhere, monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "bare")
    monkeypatch.setenv("LYO_DISCORD_TOKEN", "prefixed")

    result = run("run", KAIROS, "--check", "--db", elsewhere / "lyo.db")
    assert "token (hidden) from $LYO_DISCORD_TOKEN" in result.output


def test_a_dash_s_still_outranks_everything(elsewhere, monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "exported")

    result = run("run", KAIROS, "--check", "-s", "discord.token=given",
                 "--db", elsewhere / "lyo.db")
    assert "token (hidden) from -s" in result.output


def test_a_missing_token_says_every_way_to_give_one(elsewhere):
    result = run("run", KAIROS, "--check", "--db", elsewhere / "lyo.db")
    assert result.exit_code != 0
    assert "lyo set adapter.discord.token=" in result.output
    assert "DISCORD_TOKEN" in result.output
    assert ".env" in result.output


# ------------------------------------------------------------- the service

def test_the_service_note_says_which_dot_env_it_will_reach(tmp_path,
                                                           monkeypatch,
                                                           capsys):
    from lyo.cli import _warn_about_env
    from lyo.service import plan as make_plan

    state, work = tmp_path / "state", tmp_path / "work"
    state.mkdir(), work.mkdir()
    (state / ".env").write_text("DISCORD_TOKEN=abc\n")
    (work / ".env").write_text("DISCORD_TOKEN=abc\n")
    monkeypatch.chdir(work)
    monkeypatch.setenv("DISCORD_TOKEN", "exported")

    _warn_about_env(make_plan("kairos", state / "lyo.db", None))
    printed = capsys.readouterr().out
    #  A shell variable is gone once the service starts; a .env beside the
    #  state file is not, because lyo reads the file itself.
    assert "DISCORD_TOKEN is set in your shell" in printed
    assert f"{state / '.env'} will be read" in printed
    assert f"{work / '.env'} will not be read" in printed
