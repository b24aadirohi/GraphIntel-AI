"""Bounded-cardinality HTTP telemetry with no request bodies, credentials or query strings."""
import json
import logging
import re
import time
from uuid import uuid4

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Histogram, generate_latest
from starlette.responses import Response

logger = logging.getLogger('cinegraph.http')
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(message)s'))
    logger.addHandler(handler)


class RequestTelemetry:
    def __init__(self, app, registry):
        self.app = app
        self.requests = Counter('cinegraph_http_requests_total', 'HTTP requests',
                                ['method', 'route', 'status'], registry=registry)
        self.latency = Histogram('cinegraph_http_request_duration_seconds', 'HTTP latency',
                                 ['method', 'route'], registry=registry,
                                 buckets=(.005, .01, .025, .05, .1, .25, .5, 1, 2.5, 5, 10, 30))

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        headers = dict(scope.get('headers', []))
        proposed = headers.get(b'x-request-id', b'').decode('ascii', errors='replace')
        request_id = proposed if re.fullmatch(r'[A-Za-z0-9._-]{1,64}', proposed) else uuid4().hex
        scope.setdefault('state', {})['request_id'] = request_id
        started = time.monotonic()
        status = 500

        async def send_with_id(message):
            nonlocal status
            if message['type'] == 'http.response.start':
                status = message['status']
                message['headers'] = [
                    (key, value) for key, value in message.get('headers', [])
                    if key.lower() != b'x-request-id'
                ] + [(b'x-request-id', request_id.encode('ascii'))]
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            duration = time.monotonic() - started
            route = getattr(scope.get('route'), 'path', 'unmatched')
            method = scope.get('method', 'OTHER')
            if method not in {'GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'}:
                method = 'OTHER'
            self.requests.labels(method, route, str(status)).inc()
            self.latency.labels(method, route).observe(duration)
            logger.info(json.dumps({'event': 'http_request', 'request_id': request_id,
                                    'method': method, 'route': route, 'status': status,
                                    'duration_ms': round(duration * 1000, 2)}))


def install_api_observability(app):
    registry = CollectorRegistry()
    app.state.metrics_registry = registry
    app.add_middleware(RequestTelemetry, registry=registry)

    @app.get('/metrics', include_in_schema=False)
    def metrics():
        return Response(generate_latest(registry), headers={'Content-Type': CONTENT_TYPE_LATEST})


def _request_id(value):
    return value if re.fullmatch(r'[A-Za-z0-9._-]{1,64}', value or '') else uuid4().hex


def install_flask_observability(app):
    from flask import g, request

    @app.before_request
    def trace_start():
        g.request_id = _request_id(request.headers.get('X-Request-ID'))
        g.request_started = time.monotonic()

    @app.after_request
    def trace_end(response):
        trace = getattr(g, 'request_id', uuid4().hex)
        response.headers['X-Request-ID'] = trace
        logger.info(json.dumps({'event': 'http_request', 'service': 'dashboard',
                                'request_id': trace, 'method': request.method,
                                'route': request.url_rule.rule if request.url_rule else 'unmatched',
                                'status': response.status_code,
                                'duration_ms': round((time.monotonic() - getattr(
                                    g, 'request_started', time.monotonic())) * 1000, 2)}))
        return response


class DjangoRequestTelemetry:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = _request_id(request.headers.get('X-Request-ID'))
        started = time.monotonic()
        response = self.get_response(request)
        response['X-Request-ID'] = request.request_id
        route = getattr(request.resolver_match, 'route', 'unmatched')
        logger.info(json.dumps({'event': 'http_request', 'service': 'catalog',
                                'request_id': request.request_id, 'method': request.method,
                                'route': route, 'status': response.status_code,
                                'duration_ms': round((time.monotonic() - started) * 1000, 2)}))
        return response
