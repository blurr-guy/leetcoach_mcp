"""MCP tool: analyze_performance."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from src.data.db import get_client, resolve_user_id
from src.models import AnalyzePerformanceInput
from src.services import analysis_service
from src.tools._util import error_payload


def register(mcp: MCPServer) -> None:
    @mcp.tool()
    def analyze_performance(
        timeframe: str = "30d",
        min_attempts_per_topic: int = 2,
        user_id: str | None = None,
    ) -> dict:
        """Analyze the user's solve rate, per-topic accuracy, and timing.

        Call this when the user asks "how am I doing?", wants to know their
        weak topics, or before generating a prep plan.  Weak topics are
        recomputed and persisted, which makes future recommend_problem calls
        weight toward them.

        Args:
            timeframe: Window to analyze: "7d", "30d", "90d", or "all".
            min_attempts_per_topic: Minimum attempts before a topic's
                    accuracy is considered measured (and can be flagged weak).
            user_id: Optional explicit user; omit to use the configured
                     default user.

        Returns:
            Solve rate + attempt counts, per-topic accuracy, average time per
            difficulty, and the persisted weak-topic list.
        """
        try:
            inp = AnalyzePerformanceInput(
                timeframe=timeframe,
                min_attempts_per_topic=min_attempts_per_topic,
                user_id=user_id,
            )
            uid = resolve_user_id(inp.user_id)
            result = analysis_service.analyze_performance(
                get_client(),
                uid,
                timeframe=inp.timeframe,
                min_attempts_per_topic=inp.min_attempts_per_topic,
            )
            return result.model_dump()
        except Exception as exc:
            return error_payload(exc)