"""Interview-prep plan generation with spaced-repetition review scheduling.

Combines live performance analysis (weak topics) with a role-based curriculum,
then lays out a day-by-day schedule of new problems plus review days for
previously missed problems (SRS intervals of 1 / 3 / 7 / 14 days).
"""

from __future__ import annotations

import datetime as dt

from src.models import PlanProblem, PrepPlanDay, PrepPlanOutput, ReviewTask
from src.services import analysis_service, problem_service, progress_service

MINUTES_PER_PROBLEM = 40
MAX_PROBLEMS_PER_DAY = 3
SRS_INTERVALS = (1, 3, 7, 14)

ROLE_TOPICS: dict[str, list[str]] = {
    "general_swe": [
        "Array", "Hash Table", "Two Pointers", "String", "Binary Search",
        "Tree", "Graph", "Dynamic Programming", "Greedy", "Math",
    ],
    "backend": [
        "Array", "Hash Table", "Two Pointers", "Stack", "Heap", "Graph",
        "Dynamic Programming", "Greedy", "String", "Database",
    ],
    "frontend": [
        "Array", "String", "Tree", "Two Pointers", "Binary Search", "Stack",
        "Hash Table", "Heap", "Design", "Dynamic Programming",
    ],
    "data_ml": [
        "Array", "Math", "Hash Table", "Matrix", "Dynamic Programming",
        "Binary Search", "Sorting", "Greedy",
    ],
    "mobile": [
        "Array", "String", "Hash Table", "Stack", "Tree", "Two Pointers",
        "Dynamic Programming", "Heap",
    ],
    "devops": [
        "Array", "String", "Hash Table", "Stack", "Binary Search", "Graph",
        "Dynamic Programming",
    ],
}


def generate_prep_plan(
    db,
    user_id: str,
    *,
    target_role: str = "general_swe",
    weeks: int = 4,
    daily_time_minutes: int = 60,
    today: dt.date | None = None,
    now: dt.datetime | None = None,
) -> PrepPlanOutput:
    """Build a day-by-day prep plan for the user. Raises NotFoundError if idle."""
    today = today or dt.date.today()
    now = now or dt.datetime.combine(today, dt.time.min, tzinfo=dt.timezone.utc)

    analysis = analysis_service.analyze_performance(
        db, user_id, timeframe="all", min_attempts_per_topic=2, now=now
    )
    weak_topics = analysis.weak_topics

    role_topics = ROLE_TOPICS.get(target_role, ROLE_TOPICS["general_swe"])
    focus_cycle = weak_topics + [t for t in role_topics if t not in weak_topics]
    if not focus_cycle:
        focus_cycle = role_topics

    solved_ids = progress_service.get_solved_problem_ids(db, user_id)
    total_days = weeks * 7
    problems_per_day = max(
        1, min(MAX_PROBLEMS_PER_DAY, daily_time_minutes // MINUTES_PER_PROBLEM)
    )

    days: list[PrepPlanDay] = []
    used_ids: set[int] = set()

    for day_index in range(1, total_days + 1):
        focus = focus_cycle[(day_index - 1) % len(focus_cycle)]
        date = today + dt.timedelta(days=day_index - 1)

        reco = problem_service.recommend_problems(
            db,
            topic=focus,
            difficulty=None,
            exclude_solved=True,
            limit=problems_per_day,
            user_id=user_id,
            solved_ids=solved_ids | used_ids,
            weak_topics=weak_topics,
        )
        plan_problems: list[PlanProblem] = []
        rank = 0
        for candidate in reco.candidates:
            rank += 1
            plan_problems.append(
                PlanProblem(
                    problem_id=candidate.problem_id,
                    title=candidate.title,
                    slug=candidate.slug,
                    difficulty=candidate.difficulty,
                    leetcode_url=candidate.leetcode_url,
                    topic=focus,
                    rationale=candidate.rationale,
                )
            )
            used_ids.add(candidate.problem_id)

        reviews = _schedule_reviews(db, user_id, day_index, today, solved_ids)

        days.append(
            PrepPlanDay(
                day=day_index,
                date=date.isoformat(),
                focus=focus,
                problems=plan_problems,
                reviews=reviews,
                suggested_minutes=len(plan_problems) * MINUTES_PER_PROBLEM,
            )
        )

    total_new = sum(len(d.problems) for d in days)
    total_reviews = sum(len(d.reviews) for d in days)
    message = (
        f"{weeks}-week {target_role} plan for {user_id}: {total_new} new problem slot(s), "
        f"{total_reviews} spaced-repetition review task(s) across {total_days} days."
    )
    return PrepPlanOutput(
        target_role=target_role,
        weeks=weeks,
        daily_time_minutes=daily_time_minutes,
        days=days,
        message=message,
    )


def _schedule_reviews(
    db, user_id: str, day_index: int, today: dt.date, solved_ids: set[int]
) -> list[ReviewTask]:
    """Compute review tasks landing exactly on ``day_index``."""
    reviews: list[ReviewTask] = []
    for problem, row in problem_service.missed_problems(db, user_id):
        try:
            last_date = dt.date.fromisoformat(str(row["timestamp"])[:10])
        except (TypeError, ValueError):
            continue
        for interval in SRS_INTERVALS:
            review_date = last_date + dt.timedelta(days=interval)
            review_day = (review_date - today).days + 1
            if review_day == day_index and problem.id not in solved_ids:
                reviews.append(
                    ReviewTask(
                        problem_id=problem.id,
                        title=problem.title,
                        slug=problem.slug,
                        leetcode_url=problem.leetcode_url,
                        days_since_last_attempt=(today - last_date).days,
                    )
                )
                break
    return reviews