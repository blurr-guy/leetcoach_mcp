"""Problem catalog access and recommendation scoring.

``recommend_problems`` weights candidates toward (a) the user's weak topics,
(b) a difficulty sweet spot, and (c) higher frequency-of-appearance, then
returns deterministic top-N picks with human-readable rationale.
"""

from __future__ import annotations

from src.errors import CoachError, DataAccessError, NotFoundError
from src.models import (
    Difficulty,
    Problem,
    ProblemCandidate,
    RecommendProblemOutput,
)
from src.services import progress_service

# score weightings (all in [0, ~1])
WEAK_TOPIC_BOOST = 0.35
FREQUENCY_WEIGHT = 0.30
ACCEPTANCE_WEIGHT = 0.10
DIFFICULTY_MATCH_BONUS = 0.20
DIFFICULTY_DEFAULT = {Difficulty.EASY: 0.08, Difficulty.MEDIUM: 0.04, Difficulty.HARD: 0.0}


def _run(db) -> list[dict]:
    try:
        result = db.execute()
        return result.data if result is not None else []
    except CoachError:
        raise
    except Exception as exc:
        raise DataAccessError(f"Database query failed: {exc}") from exc


def get_problem(db, problem_id: int) -> Problem:
    rows = _run(db.table("problems").select("*").eq("id", problem_id))
    if not rows:
        raise NotFoundError(f"Problem {problem_id} is not in the catalog.", code="problem_not_found")
    return Problem.model_validate(rows[0])


def get_problem_by_slug(db, slug: str) -> Problem:
    rows = _run(db.table("problems").select("*").eq("slug", slug))
    if not rows:
        raise NotFoundError(f"No problem with slug '{slug}'.", code="problem_not_found")
    return Problem.model_validate(rows[0])


def upsert_problems(db, rows: list[dict]) -> int:
    """Bulk upsert catalog rows keyed on the problem ``id``. Returns row count."""
    if not rows:
        return 0
    result = db.table("problems").upsert(rows, on_conflict="id").execute()
    return len(result.data)


def _catalog_rows(db) -> list[Problem]:
    return [Problem.model_validate(r) for r in _run(db.table("problems").select("*"))]


def _score(problem: Problem, weak: list[str], difficulty: Difficulty | None) -> float:
    score = 0.0
    if any(_normalise_topic(t) in weak for t in problem.topics):
        score += WEAK_TOPIC_BOOST
    score += (problem.frequency / 100.0) * FREQUENCY_WEIGHT
    score += (1.0 - abs(problem.acceptance_rate - 50.0) / 100.0) * ACCEPTANCE_WEIGHT
    if difficulty and problem.difficulty == difficulty:
        score += DIFFICULTY_MATCH_BONUS
    elif not difficulty:
        score += DIFFICULTY_DEFAULT.get(problem.difficulty, 0.0)
    return score


def _rationale(problem: Problem, weak: list[str], difficulty: Difficulty | None, score: float) -> str:
    reasons: list[str] = []
    if any(_normalise_topic(t) in weak for t in problem.topics):
        reasons.append("matches a weak topic")
    else:
        reasons.append("good general practice")
    if difficulty and problem.difficulty == difficulty:
        reasons.append(f"exact {difficulty.value} difficulty")
    elif not difficulty:
        reasons.append("appropriate difficulty")
    return f"Score {score:.2f}; " + ", ".join(reasons) + "."


def recommend_problems(
    db,
    *,
    topic: str | None = None,
    difficulty: Difficulty | None = None,
    exclude_solved: bool = True,
    limit: int = 3,
    user_id: str,
    solved_ids: set[int] | None = None,
    weak_topics: list[str] | None = None,
) -> RecommendProblemOutput:
    """Pick the best next problems for a user from the seeded catalog."""
    if difficulty is not None and not isinstance(difficulty, Difficulty):
        difficulty = Difficulty(difficulty)

    catalog = _catalog_rows(db)
    if not catalog:
        raise DataAccessError(
            "The problems catalog is empty. Run scripts/seed_catalog.py first.",
            code="empty_catalog",
        )

    profile = progress_service.fetch_user_profile(db, user_id)
    weak = weak_topics if weak_topics is not None else (profile.weak_topics if profile else [])
    weak = [_normalise_topic(w) for w in weak if isinstance(w, str)]
    solved = (
        solved_ids
        if solved_ids is not None
        else progress_service.get_solved_problem_ids(db, user_id)
    )

    pool = []
    for problem in catalog:
        if problem.id in solved:
            continue
        if topic and not any(_normalise_topic(t) == _normalise_topic(topic) for t in problem.topics):
            continue
        if difficulty and problem.difficulty != difficulty:
            continue
        pool.append(problem)

    if not pool:
        return RecommendProblemOutput(
            candidates=[],
            message=(
                f"No unsolved problems match topic={topic!r}, difficulty={difficulty!r}. "
                "Adjust the filters, or disable exclude_solved."
            ),
        )

    scored = sorted(
        ((_score(p, weak, difficulty), p) for p in pool),
        key=lambda t: (-t[0], t[1].id),
    )

    candidates = [
        ProblemCandidate(
            problem_id=p.id,
            title=p.title,
            slug=p.slug,
            difficulty=p.difficulty,
            leetcode_url=p.leetcode_url,
            topics=p.topics,
            acceptance_rate=p.acceptance_rate,
            frequency=p.frequency,
            score=round(score, 4),
            rationale=_rationale(p, weak, difficulty, score),
        )
        for score, p in scored[:limit]
    ]

    filters = "unsolved" if exclude_solved else "no filter"
    message = (
        f"Recommended {len(candidates)} problem(s) (filter: {filters}). "
        "Run analyze_performance for topic-level accuracy, or log_attempt after each try."
    )
    return RecommendProblemOutput(candidates=candidates, message=message)


def missed_problems(db, user_id: str) -> list[tuple[Problem, dict]]:
    """Problems the user attempted/skipped, with their latest (missed) attempt.

    Returns ``[(problem, latest_missed_attempt_row)]`` ordered by recency.
    """
    rows = _run(
        db.table("attempts")
        .select("*")
        .eq("user_id", user_id)
        .in_("status", ["attempted", "skipped"])
        .order("timestamp", desc=True)
    )
    seen: dict[int, dict] = {}
    for row in rows:
        pid = int(row["problem_id"])
        if pid not in seen:
            seen[pid] = row
    out = []
    for pid, row in seen.items():
        try:
            problem = get_problem(db, pid)
        except NotFoundError:
            continue
        out.append((problem, row))
    return out


def _normalise_topic(topic: str) -> str:
    return topic.strip().lower()