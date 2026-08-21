import asyncio
import os
import sys
from uuid import uuid4

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from cinegraph.mcp_server.server import mcp
from cinegraph.shared.graph import GraphRepository


def test_mcp_tool_schemas_are_read_only_and_bounded():
    tools = asyncio.run(mcp.list_tools())
    assert {tool.name for tool in tools} == {"search_movies", "get_movie", "recommend_movies"}
    search = next(tool for tool in tools if tool.name == "search_movies")
    assert search.inputSchema["properties"]["limit"]["maximum"] == 100
    assert "ctx" not in search.inputSchema["properties"]


@pytest.mark.skipif(os.getenv("CINEGRAPH_INTEGRATION") != "1",
                    reason="Real stdio subprocess and Neo4j require CINEGRAPH_INTEGRATION=1")
def test_real_stdio_protocol():
    repository = GraphRepository()
    key = "mcp-" + uuid4().hex
    repository.ensure_schema()
    repository.upsert_movie({"id": key, "title": key, "released": 2020,
                             "summary": "Protocol smoke movie", "genres": [],
                             "cast": [], "directors": []})

    async def run():
        parameters = StdioServerParameters(command=sys.executable,
                                           args=["-m", "cinegraph.mcp_server.server"],
                                           env=dict(os.environ))
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                tools = await client.list_tools()
                assert len(tools.tools) == 3
                for name, arguments in (
                    ("search_movies", {"q": key}),
                    ("get_movie", {"movie_id": key}),
                    ("recommend_movies", {"movie_id": key, "limit": 1}),
                ):
                    result = await client.call_tool(name, arguments)
                    assert not result.isError
                    assert result.content
                    if name != "recommend_movies":
                        assert key in str(result.content)
                invalid = await client.call_tool("search_movies", {"limit": 1000})
                assert invalid.isError
    try:
        asyncio.run(run())
    finally:
        repository.delete_movie(key)
        repository.close()
