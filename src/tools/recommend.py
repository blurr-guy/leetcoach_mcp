"""MCP tool: recommend_problem."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from src.data.db import get_client, resolve_user_id
from src.models import Difficulty, RecommendProblemInput
from src.services import problem_service
from src.tools._util import error_payload


def register(mcp: MCPServer) -> None:
    @mcp.tool()
    def recommend_problem(
        topic: str | None = None,
        difficulty: Difficulty | None = None,
        exclude_solved: bool = True,
        limit: int = 3,
        user_id: str | None = None,
    ) -> dict:
        """Recommend 1-3 LeetCode problems tailored to the user.

        Call this when the user wants a fresh problem (or a batch) to practice.
        Weighting prefers the user's weak topics (from analyze_performance),
        higher-frequency problems, and a sensible difficulty sweet spot.

        Args:
            topic: Optional single topic to filter on (e.g. "Array",
                   "Dynamic Programming", "Graph").
            difficulty: Optional "Easy" / "Medium" / "Hard" filter.
            exclude_solved: Skip problems the user has already solved.
                            Defaults to true.
            limit: How many candidates to return (1-10). Defaults to 3.
            user_id: Optional explicit user; omit to use the configured
                     default user.

        Returns:
            A list of candidate problems with title, url, difficulty,
            acceptance rate, frequency, an internal relevance score, and a
            plain-English rationale for each pick.
        """
        try:
            inp = RecommendProblemInput(
                topic=topic,
                difficulty=difficulty,
                exclude_solved=exclude_solved,
                limit=limit,
                user_id=user_id,
            )
            uid = resolve_user_id(inp.user_id)
            result = problem_service.recommend_problems(
                get_client(),
                topic=inp.topic,
                difficulty=inp.difficulty,
                exclude_solved=inp.exclude_solved,
                limit=inp.limit,
                user_id=uid,
            )
            return result.model_dump()
        except Exception as exc:
            return error_payload(exc)