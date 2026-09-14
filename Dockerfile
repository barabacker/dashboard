# Образ с uv и Python — зависимости ставятся строго по uv.lock
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    # окружение вне /app, чтобы bind-mount с кодом его не перекрывал
    UV_PROJECT_ENVIRONMENT=/venv \
    PATH="/venv/bin:$PATH" \
    # база и файлы вне кода: их место — на томе
    DJANGO_DB_PATH=/data/db.sqlite3

WORKDIR /app

# Зависимости отдельным слоем: пересобираются только при изменении лока
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-group dev --no-install-project

COPY . .
RUN uv sync --locked --no-group dev

RUN useradd --create-home --uid 1000 app \
    && mkdir -p /data \
    && chown -R app:app /app /data /venv
USER app

EXPOSE 8000

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
