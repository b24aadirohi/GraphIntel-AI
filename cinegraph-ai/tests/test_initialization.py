"""Initialization prepares schema without making service startup depend on queue health."""

import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest
from django.utils import timezone

from cinegraph.catalog.models import Movie, OutboxEvent

pytestmark = pytest.mark.django_db


def load_initializer():
    path = Path(__file__).parents[1] / "scripts" / "initialize.py"
    spec = importlib.util.spec_from_file_location("cinegraph_initialize_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_initialization_succeeds_with_preserved_deadletter(monkeypatch):
    module = load_initializer()
    Movie.objects.create(id="deadletter-init", title="Pending recovery", released=2020, summary="Summary")
    event = OutboxEvent.objects.get(movie_id="deadletter-init")
    OutboxEvent.objects.filter(pk=event.pk).update(dead_lettered_at=timezone.now(), attempts=5)
    command = Mock()
    repository = Mock()
    monkeypatch.setattr(module, "call_command", command)
    monkeypatch.setattr(module, "GraphRepository", lambda: repository)
    monkeypatch.setenv("SEED_SAMPLE_DATA", "false")
    module.main()
    command.assert_called_once_with("migrate", interactive=False)
    repository.ensure_schema.assert_called_once()
    repository.close.assert_called_once()
    event.refresh_from_db()
    assert event.dead_lettered_at is not None
    assert event.attempts == 5
    assert event.processed_at is None


def test_optional_sample_seed_does_not_synchronously_drain(monkeypatch):
    module = load_initializer()
    command = Mock()
    repository = Mock()
    monkeypatch.setattr(module, "call_command", command)
    monkeypatch.setattr(module, "GraphRepository", lambda: repository)
    monkeypatch.setenv("SEED_SAMPLE_DATA", "true")
    module.main()
    assert [call.args[0] for call in command.call_args_list] == ["migrate", "seed"]
    repository.ensure_schema.assert_called_once()
