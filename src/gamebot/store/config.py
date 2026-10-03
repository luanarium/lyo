"""Configuration in the shape of OpenWrt's UCI.

`package.section.option`, with get/set/show/commit. A `set` stages a change;
nothing takes effect until `commit`, and `revert` throws staged changes away.
That staging is the whole point of the convention: a half-finished edit to a
running service should not be live.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

SET = "set"
DELETE = "delete"


class BadPath(ValueError):
    """A path that is not package[.section[.option]]."""


@dataclass(frozen=True)
class Option:
    package: str
    section: str
    option: str
    value: str | None = None
    staged: str | None = None
    staged_op: str | None = None

    @property
    def path(self) -> str:
        return f"{self.package}.{self.section}.{self.option}"

    @property
    def effective(self) -> str | None:
        """What a reader sees: the staged value if one is pending."""
        if self.staged_op == DELETE:
            return None
        if self.staged_op == SET:
            return self.staged
        return self.value

    @property
    def committed(self) -> str | None:
        """What a running service sees. Staging is invisible until commit."""
        return self.value

    @property
    def pending(self) -> bool:
        return self.staged_op is not None

    def show(self) -> str:
        mark = {SET: "~", DELETE: "-"}.get(self.staged_op or "", " ")
        return f"{mark} {self.path}={_quote(self.effective)}"


def _quote(value: str | None) -> str:
    if value is None:
        return "''"
    return "'" + value.replace("'", "'\\''") + "'"


def parse(path: str, *, exact: bool = True) -> tuple[str, ...]:
    """Split a UCI path. With exact, all three parts are required."""
    parts = tuple(p for p in path.strip().split("."))
    if not path.strip() or any(not p for p in parts) or len(parts) > 3:
        raise BadPath(f"{path!r} is not package.section.option")
    if exact and len(parts) != 3:
        raise BadPath(f"{path!r} needs all three of package.section.option")
    return parts


def split_assignment(text: str) -> tuple[str, str]:
    """`package.section.option=value` into its two halves."""
    path, separator, value = text.partition("=")
    if not separator:
        raise BadPath(f"{text!r} is not package.section.option=value")
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        value = value[1:-1]
    return path.strip(), value


class Config:
    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    # ------------------------------------------------------------- reading

    def get(self, path: str) -> str | None:
        package, section, option = parse(path)
        row = self.db.execute(
            "SELECT * FROM config WHERE package = ? AND section = ? "
            "AND option = ?", (package, section, option)).fetchone()
        return self._option(row).effective if row else None

    def show(self, prefix: str | None = None) -> list[Option]:
        clauses, values = [], []
        if prefix:
            parts = parse(prefix, exact=False)
            for column, part in zip(("package", "section", "option"), parts):
                clauses.append(f"{column} = ?")
                values.append(part)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.db.execute(
            f"SELECT * FROM config {where} ORDER BY package, section, option",
            values).fetchall()
        #  A staged removal still shows, marked, until it is committed.
        return [self._option(row) for row in rows]

    def changes(self, package: str | None = None) -> list[Option]:
        return [o for o in self.show(package) if o.pending]

    def committed(self, path: str) -> str | None:
        """One option as a running service sees it: committed values only."""
        package, section, option = parse(path)
        row = self.db.execute(
            "SELECT value FROM config WHERE package = ? AND section = ? "
            "AND option = ?", (package, section, option)).fetchone()
        return row["value"] if row else None

    def live(self, package: str, section: str) -> dict[str, str]:
        """Every committed option in one section, for the runtime to read.

        Deliberately not the staged view: `uci get` shows an author their
        pending edit, but the running service must not see it until commit.
        """
        return {o.option: o.committed
                for o in self.show(f"{package}.{section}")
                if o.committed is not None}

    @staticmethod
    def _option(row: sqlite3.Row) -> Option:
        return Option(row["package"], row["section"], row["option"],
                      row["value"], row["staged"], row["staged_op"])

    # ------------------------------------------------------------- writing

    def set(self, path: str, value: str) -> Option:
        package, section, option = parse(path)
        self.db.execute(
            "INSERT INTO config (package, section, option, value, staged, "
            "staged_op) VALUES (?, ?, ?, NULL, ?, ?) "
            "ON CONFLICT (package, section, option) DO UPDATE SET "
            "  staged = excluded.staged, staged_op = excluded.staged_op",
            (package, section, option, value, SET))
        return Option(package, section, option, staged=value, staged_op=SET)

    def delete(self, path: str) -> bool:
        """Stage a removal. Returns False if there was nothing to remove."""
        package, section, option = parse(path)
        row = self.db.execute(
            "SELECT * FROM config WHERE package = ? AND section = ? "
            "AND option = ?", (package, section, option)).fetchone()
        if row is None:
            return False
        if row["value"] is None:
            #  Never committed, so there is nothing to stage a removal of.
            self.db.execute(
                "DELETE FROM config WHERE package = ? AND section = ? "
                "AND option = ?", (package, section, option))
            return True
        self.db.execute(
            "UPDATE config SET staged = NULL, staged_op = ? "
            "WHERE package = ? AND section = ? AND option = ?",
            (DELETE, package, section, option))
        return True

    # ------------------------------------------------------------ staging

    def commit(self, package: str | None = None) -> list[Option]:
        pending = self.changes(package)
        for option in pending:
            where = (option.package, option.section, option.option)
            if option.staged_op == DELETE:
                self.db.execute(
                    "DELETE FROM config WHERE package = ? AND section = ? "
                    "AND option = ?", where)
            else:
                self.db.execute(
                    "UPDATE config SET value = staged, staged = NULL, "
                    "staged_op = NULL WHERE package = ? AND section = ? "
                    "AND option = ?", where)
        return pending

    def revert(self, package: str | None = None) -> list[Option]:
        pending = self.changes(package)
        for option in pending:
            where = (option.package, option.section, option.option)
            if option.value is None:
                self.db.execute(
                    "DELETE FROM config WHERE package = ? AND section = ? "
                    "AND option = ?", where)
            else:
                self.db.execute(
                    "UPDATE config SET staged = NULL, staged_op = NULL "
                    "WHERE package = ? AND section = ? AND option = ?", where)
        return pending
