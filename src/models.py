"""Pydantic models for every MCP tool input/output and core domain objects.

These are the single source of truth for the tool schemas.  The MCP tool
handlers in ``src/tools/`` annotate their arguments with these models, so the
schema the AI client sees is generated straight from this module.
"""

from __future__ import annotations

import datetime as dt
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class Difficulty(str, Enum):
    EASY = "Easy"
    MEDIUM = "Medium"
    HARD = "Hard"


class AttemptStatus(str, Enum):
    SOLVED = "solved"
    ATTEMPTED = "attempted"
    SKIPPED = "skipped"


class Problem(BaseModel):
    """A single row from the ``problems`` catalog."""

    id: int
    title: str
    slug: str
    difficulty: Difficulty
    topics: list[str] = Field(default_factory=list)
    leetcode_url: str
    acceptance_rate: float = 0.0
    frequency: float = 0.0


class Attempt(BaseModel):
    """A single row from the ``attempts`` table."""

    id: Optional[int] = None
    user_id: str
    problem_id: int
    status: AttemptStatus
    time_taken_minutes: Optional[int] = None
    timestamp: dt.datetime = Field(default_factory=dt.datetime.now)
    notes: Optional[str] = None


class UserProfile(BaseModel):
    """A single row from the ``user_profile`` table."""

    user_id: str
    weak_topics: list[str] = Field(default_factory=list)
    target_companies: list[str] = Field(default_factory=list)
    streak: int = 0
    last_active: Optional[dt.date] = None


# ---------------------------------------------------------------------------
# recommend_problem
# ---------------------------------------------------------------------------


class RecommendProblemInput(BaseModel):
    """Inputs for ``recommend_problem``.

    Call this when the user wants fresh problems to practice.  ``topic`` and
    ``difficulty`` narrow the search; ``exclude_solved`` (default True) drops
    already-solved problems from the candidate pool.
    """

    topic: Optional[str] = Field(
        None, description="Restrict to a topic, e.g. 'Array', 'Dynamic Programming'."
    )
    difficulty: Optional[Difficulty] = Field(
        None, description="One of Easy / Medium / Hard."
    )
    exclude_solved: bool = Field(
        True, description="Exclude problems the user has already solved."
    )
    limit: int = Field(3, ge=1, le=10, description="How many candidates to return.")
    user_id: Optional[str] = Field(
        None, description="Override the default user. Leave unset for single-user setups."
    )


class ProblemCandidate(BaseModel):
    problem_id: int
    title: str
    slug: str
    difficulty: Difficulty
    leetcode_url: str
    topics: list[str] = Field(default_factory=list)
    acceptance_rate: float = 0.0
    frequency: float = 0.0
    score: float = Field(..., description="Internal relevance score (higher = better fit).")
    rationale: str


class RecommendProblemOutput(BaseModel):
    candidates: list[ProblemCandidate] = Field(..., min_length=0, max_length=10)
    message: str = Field(..., description="Human-readable summary for the user.")


# ---------------------------------------------------------------------------
# log_attempt
# ---------------------------------------------------------------------------


class LogAttemptInput(BaseModel):
    """Inputs for ``log_attempt``.

    Call this after the user finishes (or gives up on) a problem.  ``status``
    must be solved / attempted / skipped.  ``time_taken_minutes`` is optional
    but helps the performance analysis.
    """

    problem_id: int
    status: AttemptStatus
    time_taken_minutes: Optional[int] = Field(
        None, ge=0, description="Minutes spent on this attempt (optional)."
    )
    notes: Optional[str] = Field(None, description="Free-form note (optional).")
    user_id: Optional[str] = Field(
        None, description="Override the default user. Leave unset for single-user setups."
    )

    @field_validator("time_taken_minutes", mode="before")
    @classmethod
    def _blank_time_is_none(cls, v):
        if v == "":
            return None
        return v


class LogAttemptOutput(BaseModel):
    attempt_id: Optional[int] = None
    problem_id: int
    status: AttemptStatus
    streak: int = Field(..., description="The user's current day streak after this attempt.")
    message: str


# ---------------------------------------------------------------------------
# analyze_performance
# ---------------------------------------------------------------------------


class AnalyzePerformanceInput(BaseModel):
    """Inputs for ``analyze_performance``.

    Call this to get a performance report: solve rate, per-topic accuracy,
    average time by difficulty, and the persisting weak-topic list.  Weaker
    topics are written back to ``user_profile`` so future recommendations
    can weight toward them.
    """

    timeframe: Literal["7d", "30d", "90d", "all"] = Field(
        "30d", description="Window to analyze. One of 7d / 30d / 90d / all."
    )
    min_attempts_per_topic: int = Field(
        2, ge=1, description="Minimum attempts before a topic counts as 'measured'."
    )
    user_id: Optional[str] = Field(
        None, description="Override the default user. Leave unset for single-user setups."
    )


class TimeframeSummary(BaseModel):
    total_attempts: int = 0
    solved: int = 0
    attempted: int = 0
    skipped: int = 0
    solve_rate: float = Field(
        default=0.0, ge=0.0, le=1.0, description="solved / (solved + attempted)."
    )


class TopicStat(BaseModel):
    topic: str
    attempted: int = 0
    solved: int = 0
    accuracy: float = Field(default=0.0, ge=0.0, le=1.0)
    is_weak: bool = False


class DifficultyStat(BaseModel):
    difficulty: Difficulty
    solved: int = 0
    avg_time_minutes: Optional[float] = None


class AnalyzePerformanceOutput(BaseModel):
    timeframe: str
    summary: TimeframeSummary
    topics: list[TopicStat] = Field(default_factory=list)
    difficulties: list[DifficultyStat] = Field(default_factory=list)
    weak_topics: list[str] = Field(default_factory=list)
    message: str


# ---------------------------------------------------------------------------
# generate_prep_plan
# ---------------------------------------------------------------------------


class PrepPlanInput(BaseModel):
    """Inputs for ``generate_prep_plan``.

    Call this when the user wants a structured interview-prep schedule.  The
    plan blends analysis output (weak topics) with a role-based topic
    curriculum and adds spaced-repetition review days for problems the user
    previously missed.
    """

    target_role: Literal[
        "general_swe", "backend", "frontend", "data_ml", "mobile", "devops"
    ] = Field("general_swe", description="Role to optimize the curriculum for.")
    weeks: int = Field(4, ge=1, le=12, description="Plan length in weeks.")
    daily_time_minutes: int = Field(
        60, ge=15, le=480, description="Minutes the user can dedicate per day."
    )
    user_id: Optional[str] = Field(
        None, description="Override the default user. Leave unset for single-user setups."
    )


class PlanProblem(BaseModel):
    problem_id: int
    title: str
    slug: str
    difficulty: Difficulty
    leetcode_url: str
    topic: str
    rationale: str


class ReviewTask(BaseModel):
    problem_id: int
    title: str
    slug: str
    leetcode_url: str
    days_since_last_attempt: int


class PrepPlanDay(BaseModel):
    day: int
    date: str
    focus: str
    problems: list[PlanProblem] = Field(default_factory=list)
    reviews: list[ReviewTask] = Field(default_factory=list)
    suggested_minutes: int


class PrepPlanOutput(BaseModel):
    target_role: str
    weeks: int
    daily_time_minutes: int
    days: list[PrepPlanDay] = Field(default_factory=list)
    message: str