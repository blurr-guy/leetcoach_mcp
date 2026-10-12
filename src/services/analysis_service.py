"""Performance analysis: solve rate, topic accuracy, time-per-difficulty.

``analyze_performance`` joins attempts with the problem catalog, computes the
metrics below, and persists the weak-topic list (plus last_active) back to
``user_profile`` so future recommendations can be weighted toward gaps.
"""

from __future__ import annotations

import datetime as dt

from src.errors import CoachError, DataAccessError, NotFoundError
from src.models import (
    AnalyzePerformanceInput,
    AnalyzePerformanceOutput,
    Attempt,
    AttemptStatus,
    Difficulty,
    DifficultyStat,
    TimeframeSummary,
    TopicStat,
)
from src.services import progress_service

TIMEFRAME_DAYS = {"7d": 7, "30d": 30, "90d": 90, "all": None}
WEAK_ACCURACY_THRESHOLD = 0.6
MAX_WEAK_TOPICS = 5


def _run(db) -> list[dict]:
    try:
        result = db.execute()
        return result.data if result is not None else []
    except CoachError:
        raise
    except Exception as exc:
        raise DataAccessError(f"Database query failed: {exc}") from exc


def _catalog_by_id(db) -> dict[int, dict]:
    return {int(r["id"]): r for r in _run(db.table("problems").select("*"))}


def analyze_performance(
    db,
    user_id: str,
    *,
    timeframe: str = "30d",
    min_attempts_per_topic: int = 2,
    now: dt.datetime | None = None,
) -> AnalyzePerformanceOutput:
    """Compute the full performance report for a user over a timeframe.

    Raises:
        NotFoundError: if the user has no profile yet (use log_attempt first).
    """
    profile = progress_service.fetch_user_profile(db, user_id)
    if profile is None:
        raise NotFoundError(
            "No activity yet for this user. Log an attempt with log_attempt first.",
            code="no_user_activity",
        )

    now = now or dt.datetime.now(dt.timezone.utc)
    days = TIMEFRAME_DAYS.get(timeframe)
    since = now - dt.timedelta(days=days) if days else None

    attempts = progress_service.get_attempts(db, user_id, since=since)
    problems = _catalog_by_id(db)

    summary = _summarise(attempts)
    topic_stats = _topic_stats(attempts, problems, min_attempts_per_topic)
    difficulty_stats = _difficulty_stats(attempts, problems)

    weak_topics = [
        t.topic for t in topic_stats if t.is_weak
    ][:MAX_WEAK_TOPICS]

    if weak_topics:
        progress_service.persist_weak_topics(db, user_id, weak_topics)
    else:
        progress_service.persist_weak_topics(db, user_id, [])
    progress_service.update_streak(db, user_id)

    message = _build_message(summary, weak_topics, len(attempts))
    return AnalyzePerformanceOutput(
        timeframe=timeframe,
        summary=summary,
        topics=topic_stats,
        difficulties=difficulty_stats,
        weak_topics=weak_topics,
        message=message,
    )


def _summarise(attempts: list[Attempt]) -> TimeframeSummary:
    solved = sum(1 for a in attempts if a.status == AttemptStatus.SOLVED)
    attempted = sum(1 for a in attempts if a.status == AttemptStatus.ATTEMPTED)
    skipped = sum(1 for a in attempts if a.status == AttemptStatus.SKIPPED)
    solve_rate = solved / (solved + attempted) if (solved + attempted) else 0.0
    return TimeframeSummary(
        total_attempts=len(attempts),
        solved=solved,
        attempted=attempted,
        skipped=skipped,
        solve_rate=round(solve_rate, 4),
    )


def _topic_stats(
    attempts: list[Attempt], problems: dict[int, dict], min_attempts: int
) -> list[TopicStat]:
    counters: dict[str, dict[str, float]] = {}
    for attempt in attempts:
        if attempt.status == AttemptStatus.SKIPPED:
            continue
        topics = problems.get(attempt.problem_id, {}).get("topics") or []
        if not topics:
            continue
        for topic in topics:
            c = counters.setdefault(topic, {"attempted": 0.0, "solved": 0.0})
            c["attempted"] += 1
            c["solved"] += 1 if attempt.status == AttemptStatus.SOLVED else 0

    stats: list[TopicStat] = []
    for topic, c in sorted(counters.items(), key=lambda kv: kv[0].lower()):
        measured = c["attempted"] >= min_attempts
        accuracy = c["solved"] / c["attempted"] if c["attempted"] else 0.0
        stats.append(
            TopicStat(
                topic=topic,
                attempted=int(c["attempted"]),
                solved=int(c["solved"]),
                accuracy=round(accuracy, 4),
                is_weak=measured and accuracy < WEAK_ACCURACY_THRESHOLD,
            )
        )
    stats.sort(key=lambda t: (t.accuracy, t.attempted))
    return stats


def _difficulty_stats(
    attempts: list[Attempt], problems: dict[int, dict]
) -> list[DifficultyStat]:
    agg: dict[str, list[int]] = {d.value: [] for d in Difficulty}
    for attempt in attempts:
        if attempt.status != AttemptStatus.SOLVED:
            continue
        if attempt.time_taken_minutes is None or attempt.time_taken_minutes <= 0:
            continue
        difficulty = problems.get(attempt.problem_id, {}).get("difficulty")
        if difficulty in agg:
            agg[difficulty].append(attempt.time_taken_minutes)

    stats: list[DifficultyStat] = []
    for difficulty in Difficulty:
        times = agg[difficulty.value]
        if not times:
            stats.append(DifficultyStat(difficulty=difficulty, solved=0, avg_time_minutes=None))
            continue
        stats.append(
            DifficultyStat(
                difficulty=difficulty,
                solved=len(times),
                avg_time_minutes=round(sum(times) / len(times), 1),
            )
        )
    return stats


def _build_message(summary: TimeframeSummary, weak_topics: list[str], attempt_count: int) -> str:
    if attempt_count == 0:
        return "No attempts in this window. Start logging with log_attempt to get insights."
    topics = ", ".join(weak_topics) if weak_topics else "none"
    return (
        f"Solve rate {summary.solve_rate:.0%} over {summary.total_attempts} attempt(s). "
        f"Weak topics persisted: {topics}. Run recommend_problem to target them."
    )