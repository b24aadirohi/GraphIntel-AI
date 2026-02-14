"""Parameterized Neo4j projection. Each replacement is one managed transaction."""
import base64
import hashlib
import json
import re
from typing import Annotated

from neo4j import GraphDatabase, Query, unit_of_work
from neo4j.exceptions import ServiceUnavailable
from pydantic import BaseModel, Field, StringConstraints, field_validator

from cinegraph.shared.config import Settings

RelationshipName = Annotated[str, StringConstraints(min_length=1, max_length=200)]


class Movie(BaseModel):
    id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    title: str = Field(min_length=1, max_length=250)
    released: int = Field(ge=1888, le=2200)
    summary: str = Field(default="", max_length=10000)
    genres: list[RelationshipName] = Field(default_factory=list, max_length=100)
    cast: list[RelationshipName] = Field(default_factory=list, max_length=100)
    directors: list[RelationshipName] = Field(default_factory=list, max_length=100)

    @field_validator("genres", "cast", "directors")
    @classmethod
    def nonblank_relationship_names(cls, values):
        if any(not value.strip() for value in values):
            raise ValueError("relationship names cannot be blank")
        return values

    @field_validator("id")
    @classmethod
    def safe_path_id(cls, value):
        if value in {".", ".."}:
            raise ValueError("id cannot be a path traversal segment")
        return value


def bounded_limit(limit, maximum=100):
    if not 1 <= limit <= maximum:
        raise ValueError(f"limit must be between 1 and {maximum}")
    return limit


def literal_fulltext_query(query, *, require_all=False):
    # Tokenization intentionally strips all Lucene operators and field syntax.
    terms = list(dict.fromkeys(re.findall(r"[^\W_]+", query, flags=re.UNICODE)))[:32]
    return (" AND " if require_all else " OR ").join('"' + term + '"' for term in terms)


def encode_cursor(query, title, movie_id):
    payload = [hashlib.sha256(query.encode()).hexdigest(), title, movie_id]
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def decode_cursor(cursor, query):
    try:
        if len(cursor) > 4096:
            raise ValueError("Oversized cursor")
        digest, title, movie_id = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
        if digest != hashlib.sha256(query.encode()).hexdigest():
            raise ValueError("Cursor belongs to another query")
        if not isinstance(title, str) or not isinstance(movie_id, str):
            raise ValueError("Invalid cursor fields")
        return title, movie_id
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ValueError("Invalid pagination cursor") from exc


class GraphRepository:
    def __init__(self, driver=None, settings=None):
        self.settings = settings or Settings.from_env()
        self.driver = driver or GraphDatabase.driver(
            self.settings.neo4j_uri,
            auth=(self.settings.neo4j_user, self.settings.neo4j_password),
            connection_timeout=3, connection_acquisition_timeout=5,
            max_transaction_retry_time=3,
        )

    def _read(self, cypher, **params):
        with self.driver.session(database=self.settings.neo4j_database) as session:
            return session.execute_read(unit_of_work(timeout=10)(
                lambda tx: tx.run(cypher, params).data()
            ))

    def ensure_schema(self):
        with self.driver.session(database=self.settings.neo4j_database) as session:
            for label, key in (("Movie", "id"), ("Person", "name"), ("Genre", "name")):
                # Labels/property keys come exclusively from this constant allowlist.
                session.run(
                    Query(f"CREATE CONSTRAINT {label.lower()}_identity IF NOT EXISTS "
                          f"FOR (n:{label}) REQUIRE n.{key} IS UNIQUE", timeout=10)
                ).consume()

            session.run(Query(
                "CREATE FULLTEXT INDEX movie_search IF NOT EXISTS FOR (m:Movie) "
                "ON EACH [m.title, m.summary, m.genres, m.cast, m.directors]", timeout=10
            )).consume()
            session.run(Query(
                "CREATE INDEX movie_order IF NOT EXISTS FOR (m:Movie) ON (m.title, m.id)",
                timeout=10
            )).consume()

    def upsert_movie(self, movie: dict):
        data = Movie.model_validate(movie).model_dump()

        @unit_of_work(timeout=10)
        def replace(tx):
            tx.run("MERGE (m:Movie {id:$movie.id}) SET m = $movie", movie=data).consume()
            tx.run(
                "MATCH (m:Movie {id:$id})-[r:ACTED_IN|DIRECTED|IN_GENRE]-() DELETE r",
                id=data["id"],
            ).consume()
            for field, label, relationship, incoming in (
                ("cast", "Person", "ACTED_IN", True),
                ("directors", "Person", "DIRECTED", True),
                ("genres", "Genre", "IN_GENRE", False),
            ):
                edge = f"(n)-[:{relationship}]->(m)" if incoming else f"(m)-[:{relationship}]->(n)"
                tx.run(
                    f"MATCH (m:Movie {{id:$id}}) UNWIND $names AS name "
                    f"MERGE (n:{label} {{name:name}}) MERGE {edge}",
                    id=data["id"], names=data[field],
                ).consume()

        with self.driver.session(database=self.settings.neo4j_database) as session:
            session.execute_write(replace)

    def delete_movie(self, movie_id: str):
        with self.driver.session(database=self.settings.neo4j_database) as session:
            session.execute_write(unit_of_work(timeout=10)(lambda tx: tx.run(
                "MATCH (m:Movie {id:$id}) DETACH DELETE m", id=movie_id
            ).consume()))

    def search(self, q="", limit=20):
        return self.search_page(q, limit)["items"]

    def search_page(self, q="", limit=20, cursor=None):
        bounded_limit(limit)
        if len(q) > 500:
            raise ValueError("query exceeds 500 characters")
        after_title, after_id = decode_cursor(cursor, q) if cursor else ("", "")
        query = literal_fulltext_query(q, require_all=True)
        if q.strip() and not query:
            return {"items": [], "next_cursor": None, "has_more": False}
        start = ("CALL db.index.fulltext.queryNodes('movie_search', $query) YIELD node AS m, score "
                 if query else "MATCH (m:Movie) USING INDEX m:Movie(title, id) "
                 "WHERE m.title IS NOT NULL AND m.id IS NOT NULL ")
        rows = self._read(
            start + "WITH m WHERE NOT $has_cursor OR m.title > $title OR "
            "(m.title = $title AND m.id > $id) "
            "RETURN properties(m) AS movie ORDER BY m.title, m.id LIMIT $limit",
            query=query, has_cursor=bool(cursor), title=after_title, id=after_id, limit=limit + 1,
        )
        items = [row["movie"] for row in rows[:limit]]
        more = len(rows) > limit
        next_cursor = encode_cursor(q, items[-1]["title"], items[-1]["id"]) if more else None
        return {"items": items, "next_cursor": next_cursor, "has_more": more}

    def relevant_candidates(self, question, limit=80):
        bounded_limit(limit, 200)
        query = literal_fulltext_query(question)
        if not query:
            return []
        return [row["movie"] for row in self._read(
            "CALL db.index.fulltext.queryNodes('movie_search', $query, {limit:$limit}) "
            "YIELD node AS m, score RETURN properties(m) AS movie "
            "ORDER BY score DESC, m.id LIMIT $limit", query=query, limit=limit,
        )]

    def neighbors(self, movie_id, limit=80):
        bounded_limit(limit, 200)
        return [row["movie"] for row in self._read(
            "MATCH (seed:Movie {id:$id})-[:ACTED_IN|DIRECTED|IN_GENRE]-(n)"
            "-[:ACTED_IN|DIRECTED|IN_GENRE]-(m:Movie) WHERE m <> seed "
            "WITH m, count(DISTINCT n) AS overlap "
            "RETURN properties(m) AS movie ORDER BY overlap DESC, m.id LIMIT $limit",
            id=movie_id, limit=limit,
        )]

    def recommendation_candidates(self, seed, limit=160):
        neighbors = self.neighbors(seed["id"], min(limit, 100))
        content = self.relevant_candidates(seed["title"] + " " + seed["summary"], min(limit, 100))
        return list({m["id"]: m for m in [*neighbors, *content]
                     if m["id"] != seed["id"]}.values())[:limit]

    def get_movie(self, movie_id):
        rows = self._read("MATCH (m:Movie {id:$id}) RETURN properties(m) AS movie", id=movie_id)
        return rows[0]["movie"] if rows else None

    def list_movies(self, limit=1000):
        bounded_limit(limit, 1000)
        return [r["movie"] for r in self._read(
            "MATCH (m:Movie) RETURN properties(m) AS movie ORDER BY m.id LIMIT $limit", limit=limit
        )]

    def graph(self, limit=30):
        bounded_limit(limit)
        rows = self._read(
            "MATCH (m:Movie) WITH m ORDER BY m.id LIMIT $limit "
            "OPTIONAL MATCH (m)-[r:ACTED_IN|DIRECTED|IN_GENRE]-(n) "
            "RETURN m.id AS id, m.title AS title, n.name AS name, labels(n) AS labels, "
            "type(r) AS relationship", limit=limit,
        )
        nodes, links = {}, []
        for row in rows:
            movie_id = "movie:" + row["id"]
            nodes[movie_id] = {"id": movie_id, "label": row["title"], "type": "Movie"}
            if row["name"] is None:
                continue
            kind = "Genre" if "Genre" in row["labels"] else "Person"
            node_id = kind.lower() + ":" + row["name"]
            nodes[node_id] = {"id": node_id, "label": row["name"], "type": kind}
            source, target = (movie_id, node_id) if kind == "Genre" else (node_id, movie_id)
            links.append({"source": source, "target": target, "type": row["relationship"]})
        return {"nodes": list(nodes.values()), "links": links}

    def stats(self):
        return self._read(
            "CALL { MATCH (m:Movie) RETURN count(m) AS movies } "
            "CALL { MATCH (p:Person) WHERE EXISTS { (p)--(:Movie) } RETURN count(p) AS people } "
            "CALL { MATCH (g:Genre) WHERE EXISTS { (g)--(:Movie) } RETURN count(g) AS genres } "
            "RETURN movies, people, genres"
        )[0]

    def health(self):
        self.driver.verify_connectivity()
        indexes = self._read(
            "SHOW INDEXES YIELD name, state WHERE name IN $names RETURN name, state",
            names=["movie_search", "movie_order"],
        )
        if {row["name"] for row in indexes if row["state"] == "ONLINE"} != {
            "movie_search", "movie_order"
        }:
            raise ServiceUnavailable("Required discovery indexes are not online")

    def close(self):
        self.driver.close()
