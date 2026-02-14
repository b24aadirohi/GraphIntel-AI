"""Deterministic, held-out toy relevance benchmark; no database or paid provider."""
import json
from importlib.resources import files

from cinegraph.shared.rag import retrieve
from cinegraph.shared.recommendations import recommend


class FixtureRepository:
    def __init__(self, movies):
        self.movies = movies

    def list_movies(self, limit=1000):
        return self.movies[:limit]

    def get_movie(self, movie_id):
        return next((movie for movie in self.movies if movie["id"] == movie_id), None)


    def relevant_candidates(self, question, limit=80):
        # The deterministic fixture models candidate retrieval, never production fallback.
        from cinegraph.shared.recommendations import content_scores
        scores = content_scores(question, self.movies)
        ranked = sorted(zip(self.movies, scores, strict=True), key=lambda item: (-item[1], item[0]["id"]))
        return [movie for movie, score in ranked if score > 0][:limit]

    def neighbors(self, movie_id, limit=80):
        seed = self.get_movie(movie_id)
        return [movie for movie in self.movies if movie["id"] != movie_id and any(
            set(seed.get(field, [])) & set(movie.get(field, []))
            for field in ("genres", "cast", "directors")
        )][:limit]

    def recommendation_candidates(self, seed, limit=160):
        return [movie for movie in self.movies if movie["id"] != seed["id"]][:limit]


def evaluate():
    fixture = json.loads(files("cinegraph.shared").joinpath("evaluation.json").read_text())
    repository = FixtureRepository(fixture["movies"])
    recalls = []
    for query in fixture["queries"]:
        found = {m["id"] for m in retrieve(repository, query["question"], limit=2)}
        expected = set(query["relevant"])
        recalls.append(len(found & expected) / len(expected))
    hits = [recommend(repository, case["seed"], 1)[0]["id"] == case["relevant"]
            for case in fixture["recommendations"]]
    return {"retrieval_recall_at_2": sum(recalls) / len(recalls),
            "recommendation_hit_at_1": sum(hits) / len(hits),
            "retrieval_cases": len(recalls), "recommendation_cases": len(hits),
            "scope": "Small synthetic held-out fixture; not a production quality claim"}


def main():
    print(json.dumps(evaluate(), indent=2))


if __name__ == "__main__":
    main()
