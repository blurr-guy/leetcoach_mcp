"""MCP tool: log_attempt."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from src.data.db import get_client, resolve_user_id
from src.models import AttemptStatus, LogAttemptInput, LogAttemptOutput
from src.services import progress_service
from src.tools._util import error_payload


def register(mcp: MCPServer) -> None:
    @mcp.tool()
    def log_attempt(
        problem_id: int,
        status: AttemptStatus,
        time_taken_minutes: int | None = None,
        notes: str | None = None,
        user_id: str | None = None,
    ) -> dict:
        """Record the user's attempt on a problem.

        Call this after the user finishes (or gives up on) a problem so the
        coach can track progress, solve rates, and streaks.  This tool must be
        called before analyze_performance / generate_prep_plan have anything to
        work with.

        Args:
            problem_id: Numeric LeetCode problem id from the catalog (see
                        recommend_problem output).
            status: "solved", "attempted", or "skipped".  Use "attempted" when
                    the user tried but did not solve it, "skipped" when they
                    skipped it entirely (no time allowed).
            time_taken_minutes: Optional minutes spent.  Helps the time-per-
                    difficulty analysis.  Not allowed for "skipped".
            notes: Optional free-form note (e.g. what concept tripped them up).
            user_id: Optional explicit user; omit to use the configured
                     default user.

        Returns:
            The stored attempt plus the user's updated day streak.
        """
        try:
            uid = resolve_user_id(user_id)
            inp = LogAttemptInput(
                problem_id=problem_id,
                status=status,
                time_taken_minutes=time_taken_minutes,
                notes=notes,
                user_id=uid,
            )
            attempt, streak = progress_service.log_attempt(get_client(), inp, now=None)
            return LogAttemptOutput(
                attempt_id=attempt.id,
                problem_id=inp.problem_id,
                status=inp.status,
                streak=streak,
                message=f"Logged '{inp.status.value}' for problem {inp.problem_id}. "
                f"Current streak: {streak} day(s).",
            ).model_dump()
        except Exception as exc:
            return error_payload(exc)