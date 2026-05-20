from contextlib import asynccontextmanager
from typing import Annotated

from anyio import to_thread
from mcp.server.fastmcp import Context, FastMCP
from pydantic import Field

from cinegraph.shared.graph import GraphRepository
from cinegraph.shared.recommendations import recommend


@asynccontextmanager
async def lifespan(server):
    repository = GraphRepository()
    try:
        yield {"repository": repository}
    finally:
        await to_thread.run_sync(repository.close)


mcp = FastMCP("GraphIntel AI", lifespan=lifespan)


@mcp.tool()
async def search_movies(
    ctx: Context,
    q: Annotated[str, Field(max_length=500)] = "",
    limit: Annotated[int, Field(ge=1, le=100)] = 20,
) -> dict:
    """Search catalog titles, descriptions, cast, directors and genres."""
    repository = ctx.request_context.lifespan_context["repository"]
    return {"items": await to_thread.run_sync(repository.search, q, limit)}


@mcp.tool()
async def get_movie(ctx: Context, movie_id: Annotated[str, Field(min_length=1, max_length=128)]) -> dict:
    """Retrieve a movie and its graph relationship metadata."""
    repository = ctx.request_context.lifespan_context["repository"]
    movie = await to_thread.run_sync(repository.get_movie, movie_id)
    if movie is None:
        raise ValueError("Movie not found")
    return movie


@mcp.tool()
async def recommend_movies(
    ctx: Context,
    movie_id: Annotated[str, Field(min_length=1, max_length=128)],
    limit: Annotated[int, Field(ge=1, le=20)] = 5,
) -> dict:
    """Recommend movies with TF-IDF and shared graph relationship explanations."""
    repository = ctx.request_context.lifespan_context["repository"]
    return {"items": await to_thread.run_sync(recommend, repository, movie_id, limit)}


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
