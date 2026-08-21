import json

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_request_id_and_metrics_use_route_templates_without_query_secrets(caplog):
    from cinegraph.shared.observability import install_api_observability

    app = FastAPI()
    install_api_observability(app)

    @app.get('/films/{movie_id}')
    def movie(movie_id: str):
        return {'id': movie_id}

    client = TestClient(app)
    response = client.get('/films/private-film?token=secret-value', headers={'X-Request-ID': 'test-trace-123'})
    assert response.headers['X-Request-ID'] == 'test-trace-123'
    metrics = client.get('/metrics').text
    assert 'cinegraph_http_requests_total' in metrics
    assert 'route="/films/{movie_id}"' in metrics
    assert 'private-film' not in metrics and 'secret-value' not in metrics
    for record in caplog.records:
        if record.name == 'cinegraph.http':
            event = json.loads(record.message)
            assert event['route'] == '/films/{movie_id}' or event['route'] == '/metrics'
            assert 'secret-value' not in record.message


def test_untrusted_request_id_is_replaced_and_unmatched_routes_share_label():
    from cinegraph.shared.observability import install_api_observability

    app = FastAPI()
    install_api_observability(app)
    client = TestClient(app)
    response = client.get('/unknown-customer', headers={'X-Request-ID': 'unsafe request id!'})
    assert len(response.headers['X-Request-ID']) == 32
    metrics = client.get('/metrics').text
    assert 'route="unmatched"' in metrics
    assert 'unknown-customer' not in metrics


def test_flask_request_id_available_for_forwarding_and_safe_logging():
    from flask import Flask, g

    from cinegraph.shared.observability import install_flask_observability

    app = Flask(__name__)
    install_flask_observability(app)

    @app.get('/films/<identifier>')
    def show(identifier):
        return {'trace': g.request_id}

    response = app.test_client().get('/films/hidden', headers={'X-Request-ID': 'forward-me'})
    assert response.json['trace'] == 'forward-me'
    assert response.headers['X-Request-ID'] == 'forward-me'
