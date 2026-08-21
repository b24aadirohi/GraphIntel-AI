import os
from uuid import uuid4

import pytest

from cinegraph.shared.graph import GraphRepository

pytestmark = pytest.mark.skipif(os.getenv("CINEGRAPH_INTEGRATION") != "1",
                                reason="Requires live Neo4j; set CINEGRAPH_INTEGRATION=1")


def test_live_graph_projection_replaces_relationships_and_deletes():
    repository = GraphRepository()
    key = "integration-" + uuid4().hex
    person = "Actor " + key
    movie = {"id": key, "title": key, "released": 2020, "summary": "A space journey",
             "genres": ["Test Genre " + key], "cast": [person], "directors": []}
    try:
        repository.ensure_schema()
        repository.upsert_movie(movie)
        repository.upsert_movie(movie)
        assert repository.get_movie(key) == movie
        assert len(repository.search(key)) == 1
        assert repository._read(
            "MATCH (:Person {name:$name})-[:ACTED_IN]->(:Movie {id:$id}) RETURN count(*) AS n",
            name=person, id=key,
        )[0]["n"] == 1
        movie["cast"] = []
        movie["genres"] = []
        repository.upsert_movie(movie)
        assert repository._read(
            "MATCH (:Movie {id:$id})-[r]-() RETURN count(r) AS n", id=key
        )[0]["n"] == 0
        assert repository.search("' OR 1=1 //") == []
        assert repository.stats()["movies"] >= 1
        assert "nodes" in repository.graph(1)
        repository.delete_movie(key)
        assert repository.get_movie(key) is None
    finally:
        repository.delete_movie(key)
        with repository.driver.session(database=repository.settings.neo4j_database) as session:
            session.run("MATCH (n) WHERE n.name ENDS WITH $key AND NOT (n)--() DELETE n", key=key).consume()
        repository.close()


def test_indexed_retrieval_beyond_first_thousand_and_pagination():
    from cinegraph.shared.rag import retrieve
    from cinegraph.shared.recommendations import recommend

    repository = GraphRepository()
    prefix = "zz-hardening-" + uuid4().hex
    token = "needle" + uuid4().hex
    common = "collection" + uuid4().hex
    movies = [{"id": f"{prefix}-a-{index:04d}", "title": "Same Title",
               "released": 2020, "summary": common + " pottery and clay",
               "genres": [], "cast": [], "directors": []} for index in range(1001)]
    seed_id, target_id = prefix + "-z-seed", prefix + "-z-target"
    movies.extend([
        {"id": seed_id, "title": "Seed", "released": 2020,
         "summary": common + " " + token + " distant galaxy", "genres": [], "cast": [], "directors": []},
        {"id": target_id, "title": "Target", "released": 2020,
         "summary": common + " " + token + " distant galaxy", "genres": [], "cast": [], "directors": []},
    ])
    try:
        repository.ensure_schema()
        with repository.driver.session(database=repository.settings.neo4j_database) as session:
            session.run("UNWIND $movies AS movie CREATE (m:Movie) SET m = movie", movies=movies).consume()
            session.run(
                "MATCH (a:Movie {id:$seed}), (b:Movie {id:$target}) "
                "CREATE (g:Genre {name:$genre}), (a)-[:IN_GENRE]->(g), (b)-[:IN_GENRE]->(g)",
                seed=seed_id, target=target_id, genre=prefix,
            ).consume()
        assert target_id not in {m["id"] for m in repository.list_movies(1000)}
        assert target_id in {m["id"] for m in retrieve(repository, token)}
        assert repository.neighbors(seed_id, 1)[0]["id"] == target_id
        assert recommend(repository, seed_id, 1)[0]["id"] == target_id
        ids, cursor = [], None
        while True:
            page = repository.search_page(common, 100, cursor)
            ids.extend(movie["id"] for movie in page["items"])
            if not page["has_more"]:
                assert page["next_cursor"] is None
                break
            cursor = page["next_cursor"]
        assert len(ids) == len(set(ids)) == len(movies)
        with pytest.raises(ValueError):
            repository.search_page("different-query", 100, cursor)
    finally:
        with repository.driver.session(database=repository.settings.neo4j_database) as session:
            session.run("MATCH (m:Movie) WHERE m.id STARTS WITH $prefix DETACH DELETE m", prefix=prefix).consume()
            session.run("MATCH (g:Genre {name:$name}) DELETE g", name=prefix).consume()
        repository.close()


def test_catalog_multiword_search_requires_all_terms():
    repository = GraphRepository()
    prefix = "search-" + uuid4().hex
    movies = [
        {"id": prefix + "-target", "title": "After the Applause",
         "summary": "A performer returns home.", "released": 2020},
        {"id": prefix + "-other", "title": "A Tale of the Ocean",
         "summary": "A sailor explores a quiet coast.", "released": 2020},
    ]
    try:
        repository.ensure_schema()
        for movie in movies:
            repository.upsert_movie(movie)
        found = {movie["id"] for movie in repository.search("After the Applause", 100)}
        assert movies[0]["id"] in found
        assert movies[1]["id"] not in found
    finally:
        for movie in movies:
            repository.delete_movie(movie["id"])
        repository.close()
