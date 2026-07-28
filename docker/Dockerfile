# The build context is the repository root — `compose.yaml` sets `context: ..` for this file.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/usr/local \
    UV_COMPILE_BYTECODE=1

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Dependencies first, so editing a source file does not re-resolve the lock file.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY . .

# Then the project itself, editable — that is what puts src/ on the import path.
RUN uv sync --frozen --no-dev

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
