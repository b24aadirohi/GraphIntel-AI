"""Prepare SQL/graph schema; queued delivery and recovery belong to the workers.

Stop workers using the legacy global-lock protocol before applying the
per-movie-lock migration. Existing retries and dead letters are preserved and
must never prevent unrelated services or workers from starting.
"""

import os

import django
from django.core.management import call_command

from cinegraph.shared.graph import GraphRepository


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cinegraph.catalog.settings")
    django.setup()
    call_command("migrate", interactive=False)
    if os.getenv("SEED_SAMPLE_DATA", "false").lower() == "true":
        call_command("seed")
    repository = GraphRepository()
    try:
        repository.ensure_schema()
    finally:
        repository.close()


if __name__ == "__main__":
    main()
