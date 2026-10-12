"""Local SQLite data access.

Exposes the same chainable query-builder surface the services already speak::

    db.table("problems").select("*").eq("id", 1).execute().data

Because the interface matches what the services were written against, the
business logic in ``src/services/`` is storage-agnostic and needed no changes
for the move from Postgres to SQLite.

Everything is local: a single file on disk, no server, no network, no accounts.
The schema is applied automatically on first connect.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Load a repo-root .env if present. Real environment variables always win, and
# the file is entirely optional: the defaults below work with no .env at all.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

DEFAULT_DB_PATH = "data/leetcode.db"
DEFAULT_USER_ID = "00000000-0000-4000-a000-000000000001"

ENV_DB_PATH = "LEETCOACH_DB_PATH"
ENV_DEFAULT_USER = "LEETCOACH_DEFAULT_USER_ID"

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

# Columns held as JSON-encoded arrays (SQLite has no array type).
_JSON_COLUMNS: dict[str, tuple[str, ...]] = {
    "problems": ("topics",),
    "user_profile": ("weak_topics", "target_companies"),
}

_TABLES = ("problems", "attempts", "user_profile")
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _check_ident(name: str) -> str:
    if not _IDENT.match(name):
        raise ValueError(f"Invalid SQL identifier: {name!r}")
    return name


class _Result:
    """Mimics the ``.data`` attribute of a PostgREST response."""

    def __init__(self, data: list[dict[str, Any]]):
        self.data = data


class _Query:
    """A lazy, chainable SQL builder. Nothing runs until :meth:`execute`."""

    def __init__(self, client: SQLiteClient, table: str):
        self._client = client
        self._table = table
        self._op = "select"
        self._cols = "*"
        self._where: list[str] = []
        self._params: list[Any] = []
        self._order: tuple[str, bool] | None = None
        self._limit: int | None = None
        self._payload: Any = None
        self._on_conflict: str | None = None

    # ---- chainable verbs -------------------------------------------------
    def select(self, cols: str = "*") -> _Query:
        self._cols = cols
        return self

    def insert(self, payload: Any) -> _Query:
        self._op = "insert"
        self._payload = payload
        return self

    def upsert(self, payload: Any, on_conflict: str | None = None) -> _Query:
        self._op = "upsert"
        self._payload = payload
        self._on_conflict = on_conflict
        return self

    def update(self, payload: dict) -> _Query:
        self._op = "update"
        self._payload = payload
        return self

    def delete(self) -> _Query:
        self._op = "delete"
        return self

    def eq(self, col: str, value: Any) -> _Query:
        self._where.append(f'"{_check_ident(col)}" = ?')
        self._params.append(value)
        return self

    def gte(self, col: str, value: Any) -> _Query:
        self._where.append(f'"{_check_ident(col)}" >= ?')
        self._params.append(value)
        return self

    def in_(self, col: str, values: list[Any]) -> _Query:
        col = _check_ident(col)
        if not values:
            self._where.append("0 = 1")
            return self
        placeholders = ", ".join("?" * len(values))
        self._where.append(f'"{col}" IN ({placeholders})')
        self._params.extend(values)
        return self

    def order(self, col: str, desc: bool = False) -> _Query:
        self._order = (_check_ident(col), desc)
        return self

    def limit(self, n: int) -> _Query:
        self._limit = n
        return self

    # ---- terminal verb ---------------------------------------------------
    def execute(self) -> _Result:
        with self._client.lock:
            return self._execute_locked()

    def _execute_locked(self) -> _Result:
        conn = self._client.conn
        where = f" WHERE {' AND '.join(self._where)}" if self._where else ""

        if self._op == "select":
            sql = f'SELECT {self._select_list()} FROM "{self._table}"{where}'
            if self._order:
                col, desc = self._order
                sql += f' ORDER BY "{col}" {"DESC" if desc else "ASC"}'
            if self._limit is not None:
                sql += f" LIMIT {int(self._limit)}"
            rows = conn.execute(sql, self._params).fetchall()
            return _Result([self._decode(r) for r in rows])

        if self._op == "delete":
            rows = conn.execute(
                f'DELETE FROM "{self._table}"{where} RETURNING *', self._params
            ).fetchall()
            conn.commit()
            return _Result([self._decode(r) for r in rows])

        if self._op == "update":
            payload = self._encode(self._payload)
            assignments = ", ".join(f'"{_check_ident(c)}" = ?' for c in payload)
            conn.execute(
                f'UPDATE "{self._table}" SET {assignments}{where}',
                list(payload.values()) + self._params,
            )
            rows = conn.execute(
                f'SELECT * FROM "{self._table}"{where}', self._params
            ).fetchall()
            conn.commit()
            return _Result([self._decode(r) for r in rows])

        if self._op in ("insert", "upsert"):
            return self._write_rows(conn)

        raise AssertionError(f"Unsupported op: {self._op}")  # pragma: no cover

    # ---- helpers ---------------------------------------------------------
    def _select_list(self) -> str:
        if self._cols == "*":
            return "*"
        return ", ".join(f'"{_check_ident(c.strip())}"' for c in self._cols.split(","))

    def _write_rows(self, conn: sqlite3.Connection) -> _Result:
        payloads = self._payload if isinstance(self._payload, list) else [self._payload]
        if not payloads:
            return _Result([])

        columns = list(payloads[0].keys())
        col_sql = ", ".join(f'"{_check_ident(c)}"' for c in columns)
        placeholders = ", ".join("?" * len(columns))

        sql = f'INSERT INTO "{self._table}" ({col_sql}) VALUES ({placeholders})'
        if self._op == "upsert":
            conflict = self._on_conflict or "id"
            updates = [
                f'"{_check_ident(c)}" = excluded."{_check_ident(c)}"'
                for c in columns
                if c != conflict
            ]
            if updates:
                sql += (
                    f' ON CONFLICT("{_check_ident(conflict)}")'
                    f" DO UPDATE SET {', '.join(updates)}"
                )
            else:  # nothing but the conflict key; ignore duplicates
                sql += f' ON CONFLICT("{_check_ident(conflict)}") DO NOTHING'
        sql += " RETURNING *"

        written: list[dict[str, Any]] = []
        for payload in payloads:
            encoded = self._encode(payload)
            row = conn.execute(sql, [encoded.get(c) for c in columns]).fetchone()
            if row is not None:
                written.append(self._decode(row))
        conn.commit()
        return _Result(written)

    def _encode(self, payload: dict) -> dict:
        out = dict(payload)
        for col in _JSON_COLUMNS.get(self._table, ()):
            if col in out and not isinstance(out[col], str):
                out[col] = json.dumps(out[col])
        return out

    def _decode(self, row: sqlite3.Row) -> dict:
        out = dict(row)
        for col in _JSON_COLUMNS.get(self._table, ()):
            if col in out:
                val = out[col]
                if isinstance(val, str):
                    try:
                        out[col] = json.loads(val)
                    except json.JSONDecodeError:
                        out[col] = []
                elif val is None:
                    out[col] = []
        return out


class SQLiteClient:
    """A tiny SQLite-backed database client."""

    def __init__(self, path: str | None = None):
        self.path = path or default_db_path()
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")  # OFF by default in SQLite
        if self.path != ":memory:":
            self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.executescript(SCHEMA_PATH.read_text())
        self.conn.commit()

    def table(self, name: str) -> _Query:
        if name not in _TABLES:
            raise ValueError(f"Unknown table: {name!r}")
        return _Query(self, name)

    def close(self) -> None:
        self.conn.close()


_client: SQLiteClient | None = None
_client_lock = threading.Lock()


def default_db_path() -> str:
    return os.getenv(ENV_DB_PATH, "").strip() or DEFAULT_DB_PATH


def get_client() -> SQLiteClient:
    """Return the process-wide SQLite client, creating it on first use."""
    global _client
    with _client_lock:
        if _client is None:
            _client = SQLiteClient(default_db_path())
        return _client


def get_default_user_id() -> str:
    """The user id attached to rows when a tool call omits ``user_id``.

    Defaults to a stable built-in uuid so a fresh clone works with zero
    configuration. Override with ``LEETCOACH_DEFAULT_USER_ID``.
    """
    return os.getenv(ENV_DEFAULT_USER, "").strip() or DEFAULT_USER_ID


def resolve_user_id(user_id: str | None) -> str:
    """Use the explicit user id, or fall back to the configured default."""
    if user_id and user_id.strip():
        return user_id.strip()
    return get_default_user_id()
