from cinegraph.shared.graph import decode_cursor, encode_cursor, literal_fulltext_query
from cinegraph.shared.recommendations import cache_info, content_scores


def test_literal_search_and_cursor_binding():
    assert literal_fulltext_query('space OR *:* (title:x)') == '"space" OR "OR" OR "title" OR "x"'
    assert literal_fulltext_query("After the Applause", require_all=True) == '"After" AND "the" AND "Applause"'
    cursor = encode_cursor("space", "Title", "id")
    assert decode_cursor(cursor, "space") == ("Title", "id")
    import pytest
    with pytest.raises(ValueError):
        decode_cursor(cursor, "other")


def test_tfidf_candidate_fingerprint_cache():
    movies = [{"id": "cache-test", "title": "Space", "summary": "A planet", "genres": []}]
    content_scores("planet", movies)
    first = cache_info()
    content_scores("space", movies)
    assert cache_info()["fits"] == first["fits"]
    movies[0]["summary"] = "A bakery"
    content_scores("bakery", movies)
    assert cache_info()["fits"] == first["fits"] + 1


def test_cache_storage_is_bounded():
    from cinegraph.shared.recommendations import CACHE_SIZE

    for index in range(CACHE_SIZE + 2):
        content_scores("planet", [{"id": str(index), "title": f"Bounded {index}",
                                   "summary": "planet", "genres": []}])
    assert cache_info()["entries"] <= CACHE_SIZE


def test_health_requires_online_indexes():
    import pytest
    from neo4j.exceptions import ServiceUnavailable

    from cinegraph.shared.graph import GraphRepository

    class Driver:
        def verify_connectivity(self):
            return None

    repository = GraphRepository(driver=Driver())
    repository._read = lambda *args, **kwargs: [{"name": "movie_search", "state": "ONLINE"}]
    with pytest.raises(ServiceUnavailable, match="indexes"):
        repository.health()
    repository._read = lambda *args, **kwargs: [
        {"name": "movie_search", "state": "POPULATING"},
        {"name": "movie_order", "state": "ONLINE"},
    ]
    with pytest.raises(ServiceUnavailable, match="indexes"):
        repository.health()
    repository._read = lambda *args, **kwargs: [
        {"name": "movie_search", "state": "ONLINE"},
        {"name": "movie_order", "state": "ONLINE"},
    ]
    repository.health()
