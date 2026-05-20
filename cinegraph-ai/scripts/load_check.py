"""Small authenticated local concurrency check, not a production capacity benchmark."""
import argparse
import json
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://localhost:8100')
    parser.add_argument('--requests', type=int, default=100)
    parser.add_argument('--concurrency', type=int, default=8)
    args = parser.parse_args()
    if not 1 <= args.requests <= 1000 or not 1 <= args.concurrency <= 32:
        parser.error('requests must be1..1000 and concurrency1..32')
    credential = os.environ.get('CINEGRAPH_API_KEY', '')
    if not credential:
        parser.error('CINEGRAPH_API_KEY is required')

    def request(_):
        started = time.perf_counter()
        req = Request(args.base_url.rstrip('/') + '/movies?limit=5',
                      headers={'Authorization': 'Bearer ' + credential})
        try:
            with urlopen(req, timeout=15) as response:
                body = json.load(response)
                return time.perf_counter() - started, response.status, len(body.get('items', []))
        except HTTPError as error:
            return time.perf_counter() - started, error.code, 0

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        results = list(pool.map(request, range(args.requests)))
    elapsed = time.perf_counter() - started
    durations = sorted(row[0] for row in results)
    errors = sum(status != 200 for _, status, _ in results)
    print(json.dumps({'requests': args.requests, 'concurrency': args.concurrency,
                      'errors': errors, 'elapsed_seconds': round(elapsed, 3),
                      'p50_ms': round(statistics.median(durations) * 1000, 2),
                      'p95_ms': round(durations[min(len(durations)-1, int(len(durations)*.95))]*1000, 2),
                      'requests_per_second': round(len(results)/elapsed, 2),
                      'scope': 'Local movie-list endpoint; small catalog, not sustained capacity'}, indent=2))
    raise SystemExit(1 if errors else 0)


if __name__ == '__main__':
    main()
