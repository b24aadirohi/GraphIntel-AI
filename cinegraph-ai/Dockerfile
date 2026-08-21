FROM cgr.dev/chainguard/wolfi-base AS python-base
RUN apk add --no-cache python-3.12 libstdc++ libgomp

FROM python-base AS build
COPY --from=ghcr.io/astral-sh/uv:0.8.22 /uv /uvx /bin/
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
ENV UV_PYTHON=python3.12 UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY manage.py ./manage.py
COPY scripts ./scripts
RUN uv sync --frozen --no-dev && \
    DJANGO_SECRET_KEY=build-only-static-collection-key uv run python manage.py collectstatic --noinput

FROM python-base AS runtime
RUN apk add --no-cache tzdata && \
    addgroup -g 10001 cinegraph && adduser -D -u 10001 -G cinegraph cinegraph
WORKDIR /app
COPY --from=build --chown=10001:10001 /app /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENV PATH="/app/.venv/bin:$PATH"
USER 10001:10001
EXPOSE 5000 8000 8001
CMD ["uvicorn", "cinegraph.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
