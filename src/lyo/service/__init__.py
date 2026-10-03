"""Running lyo as a service, on whatever the host already supplies.

systemd user units on Linux, Task Scheduler on Windows -- both chosen because
they need no administrator rights and no extra dependency. The generated
definition is plain text, so `lyo service install --dry-run` can show you
exactly what it would write.

Secrets stay out of it: the bot token lives in the project's sqlite3 file, so
the unit carries no credentials.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence


class ServiceError(Exception):
    """The host cannot manage services the way we were asked to."""


@dataclass(frozen=True)
class Plan:
    """What the service should run."""

    name: str
    executable: Path
    working_dir: Path
    db: Path
    source: Path | None = None
    description: str = "lyo Engine"

    @property
    def unit_name(self) -> str:
        return self.name if self.name.startswith("lyo") else f"lyo-{self.name}"

    def argv(self) -> list[str]:
        parts = [str(self.executable), "run"]
        if self.source is not None:
            parts.append(str(self.source))
        parts += ["--db", str(self.db)]
        return parts

    def command(self) -> str:
        return " ".join(self.argv())


@dataclass
class Result:
    ok: bool
    message: str
    detail: str = ""


Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]


def _run(argv: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(list(argv), capture_output=True, text=True, check=False)


# ------------------------------------------------------------------ systemd


@dataclass
class Systemd:
    """A systemd user unit. No root, and it survives with enable-linger."""

    root: Path = field(
        default_factory=lambda: Path.home() / ".config" / "systemd" / "user")
    runner: Runner = _run

    kind = "systemd user unit"

    def unit_path(self, plan: Plan) -> Path:
        return self.root / f"{plan.unit_name}.service"

    def definition(self, plan: Plan) -> str:
        #  No After=network-online.target: a user manager cannot order against
        #  system targets reliably, so Restart handles a late network instead.
        return f"""[Unit]
Description={plan.description} -- {plan.unit_name}

[Service]
Type=simple
WorkingDirectory={plan.working_dir}
ExecStart={plan.command()}
ExecReload=/bin/kill -HUP $MAINPID
Restart=on-failure
RestartSec=5
KillSignal=SIGTERM
TimeoutStopSec=20

[Install]
WantedBy=default.target
"""

    def installed(self, plan: Plan) -> bool:
        return self.unit_path(plan).exists()

    def current_command(self, plan: Plan) -> str | None:
        """What the installed unit actually runs, which may predate this plan."""
        path = self.unit_path(plan)
        if not path.exists():
            return None
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("ExecStart="):
                return line.split("=", 1)[1].strip()
        return None

    def install(self, plan: Plan) -> Result:
        path = self.unit_path(plan)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.definition(plan), encoding="utf-8")
        self.runner(["systemctl", "--user", "daemon-reload"])
        enabled = self.runner(["systemctl", "--user", "enable", f"{plan.unit_name}.service"])
        return Result(enabled.returncode == 0, f"installed {path}",
                      (enabled.stderr or "").strip())

    def uninstall(self, plan: Plan) -> Result:
        name = f"{plan.unit_name}.service"
        self.runner(["systemctl", "--user", "disable", "--now", name])
        path = self.unit_path(plan)
        existed = path.exists()
        path.unlink(missing_ok=True)
        self.runner(["systemctl", "--user", "daemon-reload"])
        return Result(True, f"removed {path}" if existed else f"no unit at {path}")

    def _control(self, verb: str, plan: Plan) -> Result:
        done = self.runner(["systemctl", "--user", verb, f"{plan.unit_name}.service"])
        return Result(done.returncode == 0, f"{verb} {plan.unit_name}",
                      (done.stderr or done.stdout or "").strip())

    def start(self, plan: Plan) -> Result:
        return self._control("start", plan)

    def stop(self, plan: Plan) -> Result:
        return self._control("stop", plan)

    def restart(self, plan: Plan) -> Result:
        return self._control("restart", plan)

    def status(self, plan: Plan) -> Result:
        done = self.runner(["systemctl", "--user", "is-active",
                            f"{plan.unit_name}.service"])
        state = (done.stdout or "").strip() or "unknown"
        return Result(state == "active", state)

    def hint(self, plan: Plan) -> str:
        return (f"start it with `lyo service start`. To keep it running after "
                f"you log out: loginctl enable-linger {os.environ.get('USER', '$USER')}")


# ------------------------------------------------------------ task scheduler


@dataclass
class SchTasks:
    """Windows Task Scheduler, on logon. No admin rights, no service wrapper."""

    runner: Runner = _run

    kind = "Windows scheduled task"

    def unit_path(self, plan: Plan) -> Path:
        return Path(f"\\{plan.unit_name}")

    def definition(self, plan: Plan) -> str:
        return (f'schtasks /create /tn "{plan.unit_name}" /sc onlogon /f \\\n'
                f'  /tr "{plan.command()}"\n'
                f'# working directory: {plan.working_dir}\n')

    def installed(self, plan: Plan) -> bool:
        return self.runner(["schtasks", "/query", "/tn", plan.unit_name]).returncode == 0

    def current_command(self, plan: Plan) -> str | None:
        done = self.runner(["schtasks", "/query", "/tn", plan.unit_name,
                            "/fo", "list", "/v"])
        if done.returncode != 0:
            return None
        for line in (done.stdout or "").splitlines():
            if line.lower().startswith("task to run"):
                return line.split(":", 1)[-1].strip()
        return None

    def install(self, plan: Plan) -> Result:
        done = self.runner(["schtasks", "/create", "/tn", plan.unit_name,
                            "/sc", "onlogon", "/f", "/tr", plan.command()])
        return Result(done.returncode == 0, f"registered task {plan.unit_name}",
                      (done.stderr or done.stdout or "").strip())

    def uninstall(self, plan: Plan) -> Result:
        done = self.runner(["schtasks", "/delete", "/tn", plan.unit_name, "/f"])
        return Result(done.returncode == 0, f"removed task {plan.unit_name}",
                      (done.stderr or done.stdout or "").strip())

    def start(self, plan: Plan) -> Result:
        done = self.runner(["schtasks", "/run", "/tn", plan.unit_name])
        return Result(done.returncode == 0, f"started {plan.unit_name}",
                      (done.stderr or done.stdout or "").strip())

    def stop(self, plan: Plan) -> Result:
        done = self.runner(["schtasks", "/end", "/tn", plan.unit_name])
        return Result(done.returncode == 0, f"stopped {plan.unit_name}",
                      (done.stderr or done.stdout or "").strip())

    def restart(self, plan: Plan) -> Result:
        self.stop(plan)
        return self.start(plan)

    def status(self, plan: Plan) -> Result:
        done = self.runner(["schtasks", "/query", "/tn", plan.unit_name, "/fo", "list"])
        if done.returncode != 0:
            return Result(False, "not installed")
        state = "unknown"
        for line in (done.stdout or "").splitlines():
            if line.lower().startswith("status"):
                state = line.split(":", 1)[-1].strip().lower()
        return Result(state == "running", state)

    def hint(self, plan: Plan) -> str:
        return ("the task runs at logon. `lyo service start` runs it now "
                "without waiting.")


# ---------------------------------------------------------------- selection


def supervisor(runner: Runner | None = None) -> Systemd | SchTasks:
    """Whatever this host already provides."""
    if sys.platform == "win32":
        return SchTasks(runner=runner or _run)
    if shutil.which("systemctl") and Path("/run/systemd/system").exists():
        return Systemd(runner=runner or _run)
    raise ServiceError(
        "no supported service manager found. Supported: systemd user units on "
        "Linux, Task Scheduler on Windows. `lyo service install --dry-run` "
        "still prints the definition so you can install it by hand.")


def plan(name: str, db: Path, source: Path | None,
         working_dir: Path | None = None) -> Plan:
    executable = shutil.which("lyo") or str(Path(sys.executable).parent / "lyo")
    return Plan(name=name, executable=Path(executable).resolve(),
                working_dir=(working_dir or Path.cwd()).resolve(),
                db=db.resolve(), source=source.resolve() if source else None)
