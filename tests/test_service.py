"""Running lyo as a service, on systemd and on Task Scheduler."""

import subprocess
import sys
from pathlib import Path

import pytest

from lyo.service import Plan, SchTasks, ServiceError, Systemd, plan, supervisor


class Recorder:
    """Stands in for subprocess.run, so no real service is touched."""

    def __init__(self, returncode=0, stdout="", stderr=""):
        self.calls: list[list[str]] = []
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr

    def __call__(self, argv):
        self.calls.append(list(argv))
        return subprocess.CompletedProcess(list(argv), self.returncode,
                                           self.stdout, self.stderr)


@pytest.fixture
def a_plan(tmp_path):
    return Plan(name="lyo", executable=Path("/opt/lyo/bin/lyo"),
                working_dir=tmp_path, db=tmp_path / "lyo.db",
                source=tmp_path / "world" / "kairos.md")


# -------------------------------------------------------------------- plan

def test_an_instance_name_is_prefixed_once():
    base = dict(executable=Path("/x/lyo"), working_dir=Path("/w"), db=Path("/w/a.db"))
    assert Plan(name="lyo", **base).unit_name == "lyo"
    assert Plan(name="kairos", **base).unit_name == "lyo-kairos"


def test_the_command_carries_absolute_paths(a_plan):
    argv = a_plan.argv()
    assert argv[0] == "/opt/lyo/bin/lyo" and argv[1] == "run"
    assert "--db" in argv
    assert all(Path(p).is_absolute() for p in argv if p.startswith("/"))


def test_a_plan_without_a_source_omits_it(tmp_path):
    made = plan("lyo", tmp_path / "lyo.db", None, working_dir=tmp_path)
    assert "run" in made.argv() and made.source is None


# ----------------------------------------------------------------- systemd

def test_the_unit_is_a_user_unit_wanting_the_default_target(a_plan, tmp_path):
    text = Systemd(root=tmp_path / "units").definition(a_plan)
    assert "WantedBy=default.target" in text
    assert "[Service]" in text and "Type=simple" in text


def test_the_unit_stops_with_sigterm_and_reloads_with_sighup(a_plan, tmp_path):
    """Both signals are handled by the control channel."""
    text = Systemd(root=tmp_path / "units").definition(a_plan)
    assert "KillSignal=SIGTERM" in text
    assert "ExecReload=/bin/kill -HUP $MAINPID" in text


def test_the_unit_restarts_on_failure_rather_than_ordering_on_the_network(
        a_plan, tmp_path):
    text = Systemd(root=tmp_path / "units").definition(a_plan)
    assert "Restart=on-failure" in text
    assert "network-online" not in text, "a user manager cannot order on it"


def test_the_unit_carries_no_secrets(a_plan, tmp_path):
    text = Systemd(root=tmp_path / "units").definition(a_plan)
    assert "token" not in text.lower()
    assert "Environment" not in text


def test_install_writes_the_unit_and_enables_it(a_plan, tmp_path):
    runner = Recorder()
    boss = Systemd(root=tmp_path / "units", runner=runner)

    result = boss.install(a_plan)
    assert result.ok
    assert boss.unit_path(a_plan).read_text().startswith("[Unit]")
    assert ["systemctl", "--user", "daemon-reload"] in runner.calls
    assert ["systemctl", "--user", "enable", "lyo.service"] in runner.calls


def test_uninstall_disables_and_removes(a_plan, tmp_path):
    runner = Recorder()
    boss = Systemd(root=tmp_path / "units", runner=runner)
    boss.install(a_plan)

    assert boss.uninstall(a_plan).ok
    assert not boss.unit_path(a_plan).exists()
    assert ["systemctl", "--user", "disable", "--now", "lyo.service"] in runner.calls


def test_uninstalling_what_was_never_installed_is_not_an_error(a_plan, tmp_path):
    boss = Systemd(root=tmp_path / "units", runner=Recorder())
    result = boss.uninstall(a_plan)
    assert result.ok and "no unit" in result.message


@pytest.mark.parametrize("verb", ["start", "stop", "restart"])
def test_lifecycle_verbs_reach_systemctl(a_plan, tmp_path, verb):
    runner = Recorder()
    boss = Systemd(root=tmp_path / "units", runner=runner)
    assert getattr(boss, verb)(a_plan).ok
    assert runner.calls == [["systemctl", "--user", verb, "lyo.service"]]


def test_status_reads_is_active(a_plan, tmp_path):
    boss = Systemd(root=tmp_path / "units", runner=Recorder(stdout="active\n"))
    assert boss.status(a_plan).ok and boss.status(a_plan).message == "active"

    idle = Systemd(root=tmp_path / "units",
                   runner=Recorder(returncode=3, stdout="inactive\n"))
    assert idle.status(a_plan).ok is False


def test_the_installed_command_is_read_back_from_the_unit(a_plan, tmp_path):
    """Status must report what is installed, not what it would install."""
    boss = Systemd(root=tmp_path / "units", runner=Recorder())
    assert boss.current_command(a_plan) is None

    boss.install(a_plan)
    assert boss.current_command(a_plan) == a_plan.command()

    moved = Plan(name="lyo", executable=Path("/elsewhere/lyo"),
                 working_dir=a_plan.working_dir, db=a_plan.db)
    assert boss.current_command(moved) == a_plan.command(), "the old one, honestly"


# ----------------------------------------------------------- task scheduler

def test_a_task_is_registered_to_run_at_logon(a_plan):
    runner = Recorder()
    assert SchTasks(runner=runner).install(a_plan).ok
    (argv,) = runner.calls
    assert argv[:2] == ["schtasks", "/create"]
    assert "/sc" in argv and argv[argv.index("/sc") + 1] == "onlogon"
    assert a_plan.command() in argv


def test_a_task_is_removed_forcibly(a_plan):
    runner = Recorder()
    assert SchTasks(runner=runner).uninstall(a_plan).ok
    assert runner.calls == [["schtasks", "/delete", "/tn", "lyo", "/f"]]


def test_task_status_parses_the_list_output(a_plan):
    running = SchTasks(runner=Recorder(stdout="TaskName: \\lyo\nStatus:  Running\n"))
    assert running.status(a_plan).ok

    absent = SchTasks(runner=Recorder(returncode=1))
    assert absent.status(a_plan).message == "not installed"


def test_restarting_a_task_ends_then_runs(a_plan):
    runner = Recorder()
    SchTasks(runner=runner).restart(a_plan)
    assert [c[1] for c in runner.calls] == ["/end", "/run"]


# --------------------------------------------------------------- selection

def test_the_supervisor_matches_the_host():
    import shutil

    if sys.platform == "win32":
        assert isinstance(supervisor(), SchTasks)
    elif shutil.which("systemctl") and Path("/run/systemd/system").exists():
        assert isinstance(supervisor(), Systemd)
    else:
        with pytest.raises(ServiceError, match="no supported service manager"):
            supervisor()
