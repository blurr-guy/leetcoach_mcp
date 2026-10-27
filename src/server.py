"""LeetCode Coach MCP server.

Thin layer: registers the four MCP tools (recommend_problem, log_attempt,
analyze_performance, generate_prep_plan) and runs the transport.

Defaults to **stdio** (for desktop clients). Set ``LEETCOACH_TRANSPORT=http`` to
instead serve Streamable HTTP on ``LEETCOACH_HOST``/``LEETCOACH_PORT``, which is
what you need to expose the server to a web LLM through a tunnel (ngrok, etc.).

No business logic lives here - tool handlers in ``src/tools/`` parse input,
delegate to ``src/services/``, and return structured output.
"""

from __future__ import annotations

import os

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

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
    transport = os.getenv("LEETCOACH_TRANSPORT", "stdio").strip().lower()

    if transport in {"http", "streamable-http", "streamable_http"}:
        mcp.run(
            transport="streamable-http",
            host=os.getenv("LEETCOACH_HOST", "127.0.0.1"),
            port=int(os.getenv("LEETCOACH_PORT", "8000")),
            # Required behind a tunnel: the SDK auto-enables DNS-rebinding
            # protection for localhost, which rejects the tunnel's Host header
            # with HTTP 421. Public exposure is the tunnel's job, not ours.
            transport_security=TransportSecuritySettings(
                enable_dns_rebinding_protection=False
            ),
        )
    else:
        mcp.run()  # stdio (default)


if __name__ == "__main__":
    main()