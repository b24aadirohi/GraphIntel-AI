"""Small-catalog classical ML baseline: TF-IDF cosine plus graph overlap."""
import hashlib
import json
import threading
import time
from collections import OrderedDict

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from cinegraph.shared.graph import bounded_limit

_cache = OrderedDict()
_cache_lock = threading.Lock()
_cache_fits = 0
CACHE_TTL = 300
CACHE_SIZE = 32


def cache_info():
    with _cache_lock:
        return {"entries": len(_cache), "fits": _cache_fits}


def content_scores(query, movies):
    global _cache_fits
    texts = [m["title"] + " " + m.get("summary", "") + " " + " ".join(m.get("genres", []) + m.get("cast", []) + m.get("directors", []))
             for m in movies]
    if not texts:
        return np.array([])
    fingerprint = hashlib.sha256(json.dumps(texts, ensure_ascii=False).encode()).hexdigest()
    with _cache_lock:
        cached = _cache.get(fingerprint)
        if cached is None or time.monotonic() - cached[0] >= CACHE_TTL:
            vectorizer = TfidfVectorizer(stop_words="english")
            try:
                vectors = vectorizer.fit_transform(texts)
            except ValueError:
                return np.zeros(len(texts))
            cached = (time.monotonic(), vectorizer, vectors)
            _cache[fingerprint] = cached
            _cache_fits += 1
        _cache.move_to_end(fingerprint)
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    return cosine_similarity(cached[1].transform([query]), cached[2]).ravel()


def recommend(repository, movie_id, limit=5):
    bounded_limit(limit, 20)
    seed = repository.get_movie(movie_id)
    if seed is None:
        raise LookupError("Movie not found")
    candidates = repository.recommendation_candidates(seed, 160)
    scores = content_scores(seed["title"] + " " + seed["summary"], candidates)
    results = []
    for movie, content in zip(candidates, scores, strict=True):
        shared, overlap = [], []
        for field in ("genres", "cast", "directors"):
            a, b = set(seed.get(field, [])), set(movie.get(field, []))
            overlap.append(len(a & b) / max(1, len(a | b)))
            if a & b:
                shared.append(f"shared {field}: {', '.join(sorted(a & b))}")
        score = 0.65 * float(content) + 0.35 * sum(overlap) / 3
        explanation = f"TF-IDF similarity {content:.3f}"
        if shared:
            explanation += "; " + "; ".join(shared)
        results.append({**movie, "score": round(score, 6), "explanation": explanation})
    return sorted(results, key=lambda m: (-m["score"], m["id"]))[:limit]
