from typing import Literal

from pydantic import BaseModel

from cinegraph.shared.graph import Movie


class MoviePage(BaseModel):
    items: list[Movie]
    next_cursor: str | None = None
    has_more: bool = False


class Recommendation(Movie):
    score: float
    explanation: str


class Recommendations(BaseModel):
    items: list[Recommendation]


class GraphNode(BaseModel):
    id: str
    label: str
    type: Literal["Movie", "Person", "Genre"]


class GraphLink(BaseModel):
    source: str
    target: str
    type: Literal["ACTED_IN", "DIRECTED", "IN_GENRE"]


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    links: list[GraphLink]


class Stats(BaseModel):
    movies: int
    people: int
    genres: int


class Activity(BaseModel):
    search: int = 0
    recommendation: int = 0
    chat: int = 0


class DailyActivity(Activity):
    date: str


class Analytics(BaseModel):
    daily: list[DailyActivity]
    totals: Activity


class Source(BaseModel):
    id: str
    title: str
    summary: str


class ChatResponse(BaseModel):
    answer: str
    mode: Literal["evidence", "generated"]
    sources: list[Source]
