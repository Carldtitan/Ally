"""Seam 1: every database call goes through here.

No sqlite3 import anywhere else. Moving to Postgres should be a connection
string and a driver, not a search-and-replace across the codebase.

Two things make that swap small:

  * **Named parameters only.** Queries are written `:name`, which SQLite takes
    natively and psycopg takes after one translation in `_translate`. Positional
    `?` would have to be rewritten by hand in every query.
  * **Rows come back as dicts.** Nothing downstream indexes a tuple, so a
    driver that returns rows in a different shape changes nothing above this
    file.

Connections are per-thread and created lazily. That is the shape that ports:
a pool created inside a request handler multiplies per serverless instance and
exhausts the server's connection cap (Dos-and-donts 8.5).
"""

from __future__ import annotations

import re
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Iterator, Mapping, Sequence

from . import config

_local = threading.local()

# :name, but not ::cast and not inside a literal
_NAMED = re.compile(r"(?<!:):([a-zA-Z_][a-zA-Z0-9_]*)")


def _translate(sql: str) -> str:
    """SQLite takes :name as-is. Postgres wants %(name)s."""
    if config.is_sqlite():
        return sql
    return _NAMED.sub(r"%(\1)s", sql)


def _connect() -> sqlite3.Connection:
    url = config.database_url()
    if not url.startswith("sqlite:"):
        # The Postgres branch lives here and nowhere else.
        raise NotImplementedError(
            f"Only SQLite is wired up. Add the psycopg branch here for {url!r}."
        )
    path = url.removeprefix("sqlite:///")
    config.root().mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None, timeout=30)
    conn.row_factory = sqlite3.Row
    # WAL lets the dashboard read while the worker writes.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def connection() -> sqlite3.Connection:
    """This thread's connection, created on first use."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = _local.conn = _connect()
    return conn


def close() -> None:
    """Drop this thread's connection. Call on worker shutdown, not per request."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None


def query_all(sql: str, params: Mapping[str, Any] | None = None) -> list[dict]:
    cur = connection().execute(_translate(sql), dict(params or {}))
    try:
        return [dict(r) for r in cur.fetchall()]
    finally:
        cur.close()


def query_one(sql: str, params: Mapping[str, Any] | None = None) -> dict | None:
    cur = connection().execute(_translate(sql), dict(params or {}))
    try:
        row = cur.fetchone()
        return dict(row) if row is not None else None
    finally:
        cur.close()


def execute(sql: str, params: Mapping[str, Any] | None = None) -> int:
    """Run a statement. Returns lastrowid for INSERT, rowcount otherwise."""
    cur = connection().execute(_translate(sql), dict(params or {}))
    try:
        return cur.lastrowid if cur.lastrowid else cur.rowcount
    finally:
        cur.close()


def execute_many(sql: str, rows: Sequence[Mapping[str, Any]]) -> int:
    if not rows:
        return 0
    cur = connection().executemany(_translate(sql), [dict(r) for r in rows])
    try:
        return cur.rowcount
    finally:
        cur.close()


def script(ddl: str) -> None:
    """Run DDL. Schema lives with the caller; this seam only executes it."""
    connection().executescript(ddl)


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """All-or-nothing. Commits on clean exit, rolls back on any exception."""
    conn = connection()
    conn.execute("BEGIN")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
