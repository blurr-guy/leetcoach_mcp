"""Progress tracking: attempts, streaks, and user profiles.

All functions take the ``db`` client (the SQLite client, or a test double) as the
first argument and speak only to the chainable PostgREST query builder.
"""

from __future__ import annotations

import datetime as dt

from src.errors import BadRequestError, CoachError, DataAccessError, NotFoundError
from src.models import Attempt, AttemptStatus, LogAttemptInput, UserProfile


def _run(db) -> list[dict]:
    """Execute a PostgREST chain and return ``result.data`` raising on errors."""
    try:
        result = db.execute()
        return result.data if result is not None else []
    except CoachError:
        raise
    except Exception as exc:
        raise DataAccessError(f"Database query failed: {exc}") from exc


def fetch_user_profile(db, user_id: str) -> UserProfile | None:
    """Return the user's profile row, or ``None`` if it has never been created."""
    rows = _run(db.table("user_profile").select("*").eq("user_id", user_id))
    if not rows:
        return None
    return UserProfile.model_validate(rows[0])


def ensure_user_profile(db, user_id: str) -> UserProfile:
    """Return the profile, creating an empty one if missing."""
    profile = fetch_user_profile(db, user_id)
    if profile is not None:
        return profile
    _run(db.table("user_profile").insert({"user_id": user_id}).select("*"))
    profile = fetch_user_profile(db, user_id)
    if profile is None:
        raise DataAccessError("Failed to create user_profile row.")
    return profile


def get_attempts(
    db, user_id: str, *, since: dt.datetime | None = None, limit: int | None = None
) -> list[Attempt]:
    """Return the user's attempts, newest first.

    ``since`` and ``limit`` are pushed down into the PostgREST query so the
    database does the filtering and truncation instead of shipping every
    historical row to the process just to discard it in Python.
    """
    query = db.table("attempts").select("*").eq("user_id", user_id)
    if since is not None:
        query = query.gte("timestamp", since.isoformat())
    query = query.order("timestamp", desc=True)
    if limit is not None:
        query = query.limit(limit)
    return [Attempt.model_validate(r) for r in _run(query)]


def get_solved_problem_ids(db, user_id: str) -> set[int]:
    """Return the set of problem ids the user has ever marked solved."""
    rows = _run(
        db.table("attempts")
        .select("problem_id")
        .eq("user_id", user_id)
        .eq("status", AttemptStatus.SOLVED.value)
    )
    return {int(r["problem_id"]) for r in rows}


def compute_streak(solved_dates: set[dt.date], *, today: dt.date | None = None) -> int:
    """Number of consecutive days (ending today or yesterday) with a solve."""
    today = today or dt.date.today()
    anchor = today
    if anchor not in solved_dates:
        anchor -= dt.timedelta(days=1)
    streak = 0
    day = anchor
    while day in solved_dates:
        streak += 1
        day -= dt.timedelta(days=1)
    return streak


def update_streak(db, user_id: str, *, today: dt.date | None = None) -> int:
    """Recompute and persist the user's current day streak on their profile."""
    today = today or dt.date.today()
    solved_dates = {
        a.timestamp.date()
        for a in get_attempts(db, user_id)
        if a.status == AttemptStatus.SOLVED
    }
    streak = compute_streak(solved_dates, today=today)
    _run(
        db.table("user_profile")
        .update({"streak": streak, "last_active": today.isoformat()})
        .eq("user_id", user_id)
    )
    return streak


def persist_weak_topics(db, user_id: str, weak_topics: list[str]) -> None:
    """Write the recomputed weak-topic list to the user's profile."""
    _run(
        db.table("user_profile")
        .update({"weak_topics": weak_topics})
        .eq("user_id", user_id)
    )


def log_attempt(db, input_data: LogAttemptInput, *, now: dt.datetime | None = None) -> tuple[Attempt, int]:
    """Record one attempt and return ``(attempt, updated_streak)``.

    Raises:
        NotFoundError: if the problem id is not in the catalog.
        BadRequestError: if ``time_taken_minutes`` is set for a skipped attempt.
    """
    problem = db.table("problems").select("*").eq("id", input_data.problem_id)
    problem_rows = _run(problem)
    if not problem_rows:
        raise NotFoundError(
            f"Problem {input_data.problem_id} is not in the catalog. "
            "Run scripts/seed_catalog.py first.",
            code="problem_not_found",
        )

    if input_data.status == AttemptStatus.SKIPPED and input_data.time_taken_minutes is not None:
        raise BadRequestError(
            "A 'skipped' attempt cannot carry time_taken_minutes.",
            code="invalid_attempt_time",
        )

    timestamp = now or dt.datetime.now(dt.timezone.utc)
    row = {
        "user_id": input_data.user_id,
        "problem_id": input_data.problem_id,
        "status": input_data.status.value,
        "time_taken_minutes": input_data.time_taken_minutes,
        "timestamp": timestamp.isoformat(),
        "notes": input_data.notes,
    }
    inserted = _run(db.table("attempts").insert(row).select("*"))
    if not inserted:
        raise DataAccessError("Attempt insert returned no rows.")
    attempt = Attempt.model_validate(inserted[0])

    try:
        ensure_user_profile(db, input_data.user_id)
    except DataAccessError:
        pass
    streak = update_streak(db, input_data.user_id)
    return attempt, streak