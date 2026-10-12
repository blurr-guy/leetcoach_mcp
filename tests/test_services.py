"""Unit tests for the service layer (no MCP transport, no network).

All services are exercised against a real in-memory SQLite database via
:mod:`tests.db_helpers`.
"""

from __future__ import annotations

import datetime as dt

import pytest

from src.errors import BadRequestError, DataAccessError, NotFoundError
from src.models import AttemptStatus, LogAttemptInput
from src.services import analysis_service, planning_service, problem_service, progress_service
from tests.db_helpers import find, new_db, seed_attempt, seed_problem, seed_profile

USER = "user-1"


# ---------------------------------------------------------------------------
# progress_service
# ---------------------------------------------------------------------------


class TestComputeStreak:
    def test_today_solves(self):
        today = dt.date(2026, 1, 10)
        dates = {today, today - dt.timedelta(days=1), today - dt.timedelta(days=2)}
        assert progress_service.compute_streak(dates, today=today) == 3

    def test_gap_resets(self):
        today = dt.date(2026, 1, 10)
        dates = {today, today - dt.timedelta(days=3)}
        assert progress_service.compute_streak(dates, today=today) == 1

    def test_anchors_to_yesterday_if_no_solve_today(self):
        today = dt.date(2026, 1, 10)
        dates = {today - dt.timedelta(days=1), today - dt.timedelta(days=2)}
        assert progress_service.compute_streak(dates, today=today) == 2


class TestGetAttempts:
    def _spy(self, db):
        """Capture every Query the service builds, so we can assert pushdown."""
        captured: list = []
        original = db.table

        def spy(name):
            query = original(name)
            captured.append(query)
            return query

        db.table = spy
        return captured

    @staticmethod
    def _has_gte(query) -> bool:
        return any(">=" in clause for clause in query._where)

    def test_since_is_pushed_into_the_query(self):
        db = new_db()
        seed_problem(db, 1)
        seed_attempt(db, user_id=USER, problem_id=1, days_ago=0)
        seed_attempt(db, user_id=USER, problem_id=1, days_ago=45)

        captured = self._spy(db)
        since = dt.datetime.now(dt.UTC) - dt.timedelta(days=30)
        attempts = progress_service.get_attempts(db, USER, since=since)

        assert len(attempts) == 1
        assert self._has_gte(captured[-1]), "since must filter server-side"

    def test_limit_is_pushed_into_the_query(self):
        db = new_db()
        for i in range(5):
            seed_problem(db, i)
            seed_attempt(db, user_id=USER, problem_id=i, days_ago=i)

        captured = self._spy(db)
        attempts = progress_service.get_attempts(db, USER, limit=2)

        assert len(attempts) == 2
        assert captured[-1]._limit == 2, "limit must truncate server-side"

    def test_returns_newest_first_and_excludes_other_users(self):
        db = new_db()
        seed_problem(db, 1)
        seed_attempt(db, user_id=USER, problem_id=1, days_ago=5)
        seed_attempt(db, user_id=USER, problem_id=1, days_ago=0)
        seed_attempt(db, user_id="someone-else", problem_id=1, days_ago=0)

        attempts = progress_service.get_attempts(db, USER)

        assert [a.user_id for a in attempts] == [USER, USER]
        assert attempts[0].timestamp >= attempts[1].timestamp


class TestLogAttempt:
    def test_creates_attempt_and_updates_streak(self):
        db = new_db()
        seed_problem(db, 1)
        attempt, streak = progress_service.log_attempt(
            db,
            LogAttemptInput(
                problem_id=1,
                status=AttemptStatus.SOLVED,
                time_taken_minutes=25,
                user_id=USER,
            ),
        )
        assert attempt.problem_id == 1
        assert attempt.status == AttemptStatus.SOLVED
        assert streak >= 1
        assert find(db, "attempts", user_id=USER, problem_id=1)
        assert find(db, "user_profile", user_id=USER)  # profile auto-created

    def test_unknown_problem_raises_not_found(self):
        db = new_db()
        with pytest.raises(NotFoundError):
            progress_service.log_attempt(
                db,
                LogAttemptInput(
                    problem_id=9999,
                    status=AttemptStatus.SOLVED,
                    user_id=USER,
                ),
            )

    def test_skipped_with_time_raises(self):
        db = new_db()
        seed_problem(db, 1)
        with pytest.raises(BadRequestError):
            progress_service.log_attempt(
                db,
                LogAttemptInput(
                    problem_id=1,
                    status=AttemptStatus.SKIPPED,
                    time_taken_minutes=10,
                    user_id=USER,
                ),
            )

    def test_skipped_without_time_is_allowed(self):
        db = new_db()
        seed_problem(db, 1)
        attempt, _ = progress_service.log_attempt(
            db,
            LogAttemptInput(
                problem_id=1,
                status=AttemptStatus.SKIPPED,
                user_id=USER,
            ),
        )
        assert attempt.status == AttemptStatus.SKIPPED


# ---------------------------------------------------------------------------
# problem_service
# ---------------------------------------------------------------------------


class TestUpsertProblems:
    def test_inserts_then_updates_existing(self):
        db = new_db()
        rows = [
            {"id": 1, "title": "Two Sum", "slug": "two-sum", "difficulty": "Easy",
             "topics": ["Array"], "leetcode_url": "https://leetcode.com/problems/two-sum/",
             "acceptance_rate": 49.0, "frequency": 90.0},
        ]
        assert problem_service.upsert_problems(db, rows) == 1
        rows[0]["title"] = "Two Sum II"
        assert problem_service.upsert_problems(db, rows) == 1
        assert find(db, "problems", id=1)[0]["title"] == "Two Sum II"


class TestRecommendProblems:
    def test_filters_by_difficulty_and_topic(self):
        db = new_db()
        seed_problem(db, 1, difficulty="Easy", topics=["Array"])
        seed_problem(db, 2, difficulty="Hard", topics=["Array"])
        seed_problem(db, 3, difficulty="Easy", topics=["Graph"])

        out = problem_service.recommend_problems(
            db, difficulty="Easy", topic="Array", limit=5, user_id=USER
        )
        ids = [c.problem_id for c in out.candidates]
        assert ids == [1]

    def test_excludes_solved(self):
        db = new_db()
        seed_problem(db, 1)
        seed_problem(db, 2, topics=["Array", "Graph"])
        seed_attempt(db, user_id=USER, problem_id=1, status="solved")

        out = problem_service.recommend_problems(db, limit=5, user_id=USER)
        ids = [c.problem_id for c in out.candidates]
        assert 1 not in ids
        assert 2 in ids

    def test_weak_topic_is_prioritised(self):
        db = new_db()
        seed_profile(db, USER, weak_topics=["Graph"])
        seed_problem(db, 1, topics=["Graph"], frequency=10.0)
        seed_problem(db, 2, topics=["Array"], frequency=100.0)

        out = problem_service.recommend_problems(db, limit=1, user_id=USER)
        assert out.candidates[0].problem_id == 1
        assert "weak" in out.candidates[0].rationale

    def test_empty_catalog_raises(self):
        db = new_db()
        with pytest.raises(DataAccessError, match="empty"):
            problem_service.recommend_problems(db, limit=3, user_id=USER)

    def test_no_match_returns_empty_with_message(self):
        db = new_db()
        seed_problem(db, 1, difficulty="Easy")
        out = problem_service.recommend_problems(
            db, difficulty="Hard", topic="GraphQL", limit=3, user_id=USER
        )
        assert out.candidates == []


# ---------------------------------------------------------------------------
# analysis_service
# ---------------------------------------------------------------------------


class TestAnalyzePerformance:
    def test_full_report_and_weak_topic_persistence(self):
        db = new_db()
        seed_profile(db, USER)
        seed_problem(db, 1, topics=["Array"], difficulty="Easy")
        seed_problem(db, 2, topics=["Graph"], difficulty="Medium")
        seed_problem(db, 3, topics=["Array", "Graph"], difficulty="Medium")
        seed_problem(db, 4, topics=["Array"], difficulty="Hard")

        seed_attempt(db, user_id=USER, problem_id=1, status="solved", time_taken_minutes=30, days_ago=0)
        seed_attempt(db, user_id=USER, problem_id=2, status="attempted", time_taken_minutes=60, days_ago=1)
        seed_attempt(db, user_id=USER, problem_id=3, status="solved", time_taken_minutes=90, days_ago=2)
        seed_attempt(db, user_id=USER, problem_id=4, status="solved", time_taken_minutes=120, days_ago=3)
        seed_attempt(db, user_id=USER, problem_id=1, status="skipped", time_taken_minutes=None, days_ago=4)

        now = dt.datetime.now(dt.UTC)
        out = analysis_service.analyze_performance(
            db, USER, timeframe="30d", min_attempts_per_topic=1, now=now
        )

        assert out.summary.total_attempts == 5
        assert out.summary.solved == 3
        assert out.summary.attempted == 1
        assert out.summary.skipped == 1
        assert out.summary.solve_rate == pytest.approx(0.75, abs=1e-3)

        array = next(t for t in out.topics if t.topic == "Array")
        graph = next(t for t in out.topics if t.topic == "Graph")
        assert (array.attempted, array.solved) == (3, 3)
        assert array.accuracy == 1.0
        assert array.is_weak is False
        assert (graph.attempted, graph.solved) == (2, 1)
        assert graph.accuracy == pytest.approx(0.5, abs=1e-3)
        assert graph.is_weak is True
        assert out.weak_topics == ["Graph"]
        assert find(db, "user_profile", user_id=USER)[0]["weak_topics"] == ["Graph"]

        easy = next(d for d in out.difficulties if d.difficulty.value == "Easy")
        medium = next(d for d in out.difficulties if d.difficulty.value == "Medium")
        hard = next(d for d in out.difficulties if d.difficulty.value == "Hard")
        assert easy.avg_time_minutes == 30.0
        assert medium.avg_time_minutes == 90.0
        assert hard.avg_time_minutes == 120.0

    def test_no_activity_raises_not_found(self):
        db = new_db()
        with pytest.raises(NotFoundError):
            analysis_service.analyze_performance(db, USER, timeframe="all")

    def test_timeframe_filters_out_old_attempts(self):
        db = new_db()
        seed_profile(db, USER)
        seed_problem(db, 1)
        seed_attempt(db, user_id=USER, problem_id=1, status="solved", days_ago=20)

        now = dt.datetime.now(dt.UTC)
        recent = analysis_service.analyze_performance(db, USER, timeframe="7d", now=now)
        assert recent.summary.total_attempts == 0

        all_time = analysis_service.analyze_performance(db, USER, timeframe="all", now=now)
        assert all_time.summary.total_attempts == 1


# ---------------------------------------------------------------------------
# planning_service
# ---------------------------------------------------------------------------


class TestGeneratePrepPlan:
    def _populate(self):
        db = new_db()
        seed_profile(db, USER, weak_topics=["Graph"])
        for i in range(1, 16):
            seed_problem(db, i, topics=["Array"], difficulty="Easy")
        for i in range(16, 21):
            seed_problem(db, i, topics=["Graph"], difficulty="Medium")
        seed_problem(db, 50, topics=["Array"], difficulty="Hard")  # solved earlier
        seed_attempt(db, user_id=USER, problem_id=50, status="solved", days_ago=4)
        # Make "Graph" measurably weak (2 attempted, 0 solved).
        seed_attempt(db, user_id=USER, problem_id=16, status="attempted", days_ago=5)
        seed_attempt(db, user_id=USER, problem_id=17, status="attempted", days_ago=6)
        return db

    def test_day_count_and_focus_rotation(self):
        db = self._populate()
        today = dt.date.today()
        plan = planning_service.generate_prep_plan(
            db, USER, target_role="general_swe", weeks=2,
            daily_time_minutes=120, today=today,
        )
        assert len(plan.days) == 14
        assert plan.days[0].focus == "Graph"  # weak topic leads the cycle

    def test_only_unsolved_problems_are_picked_and_never_repeat(self):
        db = self._populate()
        today = dt.date.today()
        plan = planning_service.generate_prep_plan(
            db, USER, target_role="general_swe", weeks=1,
            daily_time_minutes=120, today=today,
        )
        seen: set[int] = set()
        for day in plan.days:
            for problem in day.problems:
                assert problem.problem_id != 50  # solved must never reappear
                assert problem.problem_id not in seen
                seen.add(problem.problem_id)
        assert len(seen) >= 1

    def test_spaced_repetition_review_is_scheduled(self):
        db = new_db()
        seed_profile(db, USER)
        seed_problem(db, 1, topics=["Array"])
        seed_problem(db, 2, topics=["Array"])
        # Missed problem yesterday -> interval of 1 lands review on day 1.
        seed_attempt(db, user_id=USER, problem_id=2, status="attempted", days_ago=1)

        today = dt.date.today()
        plan = planning_service.generate_prep_plan(
            db, USER, target_role="general_swe", weeks=1,
            daily_time_minutes=60, today=today,
        )
        day1 = plan.days[0]
        assert any(r.problem_id == 2 for r in day1.reviews)
        # Reviewed problems are excluded from being *new* picks but only for
        # solved ids; missed problems must not be a NEW recommendation.
        assert all(p.problem_id != 2 for p in day1.problems)

    def test_problems_per_day_respects_budget(self):
        db = self._populate()
        today = dt.date.today()
        for budget, expected in ((60, 1), (120, 3)):
            plan = planning_service.generate_prep_plan(
                db, USER, target_role="general_swe", weeks=1,
                daily_time_minutes=budget, today=today,
            )
            assert max(len(d.problems) for d in plan.days) == expected