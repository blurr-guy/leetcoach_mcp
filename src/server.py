"""LeetCode Coach MCP server.

Thin layer: registers the four MCP tools (recommend_problem, log_attempt,
analyze_performance, generate_prep_plan) and runs the stdio transport.

No business logic lives here - tool handlers in ``src/tools/`` parse input,
delegate to ``src/services/``, and return structured output.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from src.tools import analyze, log_attempt, prep_plan, recommend

SERVER_NAME = "leetcode-coach"
SERVER_VERSION = "1.0.0"


def build_server() -> MCPServer:
    mcp = MCPServer(
        SERVER_NAME,
        version=SERVER_VERSION,
        instructions=(
            "You are a LeetCode coach. Help users pick problems "
            "(recommend_problem), record attempts (log_attempt), understand "
            "their performance (analyze_performance), and follow structured "
            "prep plans (generate_prep_plan)."
        ),
    )
    recommend.register(mcp)
    log_attempt.register(mcp)
    analyze.register(mcp)
    prep_plan.register(mcp)
    return mcp


def main() -> None:
    mcp = build_server()
    mcp.run()  # stdio transport by default


if __name__ == "__main__":
    main()