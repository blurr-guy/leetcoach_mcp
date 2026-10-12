"""MCP transport smoke tests.

These exercise the actual tool pipeline (registration → handler → service) and
spawn the real server over stdio to prove it boots.  Database access is faked
by patching the client accessors the tool handlers import.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from src import server as server_module
from tests.db_helpers import new_db, seed_problem

ROOT = Path(__file__).resolve().parent.parent
TOOL_MODULES = ("src.tools.recommend", "src.tools.log_attempt", "src.tools.analyze", "src.tools.prep_plan")
USER = "user-1"


def _point_tools_at(db, monkeypatch) -> None:
    for mod in TOOL_MODULES:
        monkeypatch.setattr(f"{mod}.get_client", lambda: db)
        monkeypatch.setattr(f"{mod}.resolve_user_id", lambda uid: USER)


async def _call(mcp, name: str, args: dict):
    return await mcp.call_tool(name, args)


def test_recommend_problem_tool_responds(monkeypatch):
    db = new_db()
    seed_problem(db, 1, topics=["Array"])
    seed_problem(db, 2, topics=["Graph"])
    _point_tools_at(db, monkeypatch)

    async def run():
        mcp = server_module.build_server()
        res = await _call(mcp, "recommend_problem", {"limit": 2, "topic": "Array"})
        return res

    result = asyncio.run(run())
    assert not result.is_error
    text = result.content[0].text
    assert "problem_id" in text and "rationale" in text


def test_log_attempt_then_analyze_then_plan(monkeypatch):
    db = new_db()
    for pid in (1, 2, 3):
        seed_problem(db, pid, topics=["Array"], difficulty="Easy")
    _point_tools_at(db, monkeypatch)

    async def run():
        mcp = server_module.build_server()
        logged = await _call(mcp, "log_attempt", {
            "problem_id": 1, "status": "solved", "time_taken_minutes": 25,
        })
        analyzed = await _call(mcp, "analyze_performance", {"timeframe": "all"})
        planned = await _call(mcp, "generate_prep_plan", {"weeks": 1, "daily_time_minutes": 60})
        return logged, analyzed, planned

    logged, analyzed, planned = asyncio.run(run())
    assert not logged.is_error and "streak" in logged.content[0].text
    assert not analyzed.is_error and "solve_rate" in analyzed.content[0].text
    assert not planned.is_error and "days" in planned.content[0].text


def test_tool_returns_structured_error_not_exception(monkeypatch):
    db = new_db()  # empty catalog
    _point_tools_at(db, monkeypatch)

    async def run():
        mcp = server_module.build_server()
        return await _call(mcp, "recommend_problem", {"limit": 3})

    result = asyncio.run(run())
    assert not result.is_error  # we return an error *payload*, never raise
    assert '"error"' in result.content[0].text
    assert '"code"' in result.content[0].text


def test_server_boots_over_stdio_and_lists_tools():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=sys.executable, args=["-m", "src.server"], cwd=str(ROOT))

    async def run():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), timeout=15)
                tools = await asyncio.wait_for(session.list_tools(), timeout=15)
                return [t.name for t in tools.tools]

    names = asyncio.run(run())
    assert set(names) == {
        "recommend_problem",
        "log_attempt",
        "analyze_performance",
        "generate_prep_plan",
    }