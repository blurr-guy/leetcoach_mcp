"""Shared test helpers.

Tests run against the *real* SQLite backend using an in-memory database, so the
query-builder and JSON-array handling are exercised for real rather than against
a hand-written double.
"""

from __future__ import annotations

import datetime as dt

from src.data.db import SQLiteClient


def new_db() -> SQLiteClient:
    """A fresh, empty, in-memory database."""
    return SQLiteClient(":memory:")


def seed_problem(db: SQLiteClient, problem_id: int, **overrides) -> dict:
    row = {
        "id": problem_id,
        "title": f"Problem {problem_id}",
        "slug": f"problem-{problem_id}",
        "difficulty": "Easy",
        "topics": ["Array"],
        "leetcode_url": f"https://leetcode.com/problems/problem-{problem_id}/",
        "acceptance_rate": 50.0,
        "frequency": 50.0,
    }
    row.update(overrides)
    db.table("problems").upsert(row, on_conflict="id").execute()
    return row


def seed_attempt(
    db: SQLiteClient,
    *,
    user_id: str,
    problem_id: int,
    status: str = "solved",
    time_taken_minutes: int | None = 30,
    days_ago: int = 0,
    notes: str | None = None,
) -> dict:
    timestamp = (
        dt.datetime.now(dt.UTC) - dt.timedelta(days=days_ago)
    ).isoformat()
    row = {
        "user_id": user_id,
        "problem_id": problem_id,
        "status": status,
        "time_taken_minutes": time_taken_minutes,
        "timestamp": timestamp,
        "notes": notes,
    }
    return db.table("attempts").insert(row).execute().data[0]


def seed_profile(db: SQLiteClient, user_id: str, **overrides) -> dict:
    row = {
        "user_id": user_id,
        "weak_topics": [],
        "target_companies": [],
        "streak": 0,
        "last_active": None,
    }
    row.update(overrides)
    db.table("user_profile").upsert(row, on_conflict="user_id").execute()
    return row


def find(db: SQLiteClient, table: str, **filters) -> list[dict]:
    """Read rows matching equality filters (a convenience for assertions)."""
    query = db.table(table).select("*")
    for column, value in filters.items():
        query = query.eq(column, value)
    return query.execute().data
