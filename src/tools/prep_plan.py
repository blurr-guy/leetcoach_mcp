"""MCP tool: generate_prep_plan."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from src.data.db import get_client, resolve_user_id
from src.models import PrepPlanInput
from src.services import planning_service
from src.tools._util import error_payload


def register(mcp: MCPServer) -> None:
    @mcp.tool()
    def generate_prep_plan(
        target_role: str = "general_swe",
        weeks: int = 4,
        daily_time_minutes: int = 60,
        user_id: str | None = None,
    ) -> dict:
        """Generate a day-by-day interview-prep plan with spaced repetition.

        Call this when the user wants a structured multi-week study schedule.
        The plan blends the user's weak topics (analyze_performance output)
        with a role-based curriculum, then adds spaced-repetition review days
        for problems they previously missed.

        Args:
            target_role: Curriculum to optimize for: "general_swe", "backend",
                    "frontend", "data_ml", "mobile", or "devops".
            weeks: Plan length in weeks (1-12). Defaults to 4.
            daily_time_minutes: Daily study budget (15-480). Defaults to 60.
            user_id: Optional explicit user; omit to use the configured
                     default user.

        Returns:
            A list of days; each day has a focus topic, recommended problems,
            and any review tasks falling on that day.
        """
        try:
            inp = PrepPlanInput(
                target_role=target_role,
                weeks=weeks,
                daily_time_minutes=daily_time_minutes,
                user_id=user_id,
            )
            uid = resolve_user_id(inp.user_id)
            result = planning_service.generate_prep_plan(
                get_client(),
                uid,
                target_role=inp.target_role,
                weeks=inp.weeks,
                daily_time_minutes=inp.daily_time_minutes,
            )
            return result.model_dump()
        except Exception as exc:
            return error_payload(exc)