# syntax=docker/dockerfile:1.7
# ============================================================
#  FastAPI backend — multi-stage Dockerfile
#  Тargets: dev (с tooling, ходим uvicorn --reload) | runtime (тонкий, prod)
# ============================================================

ARG PYTHON_VERSION=3.12

# ---------- Stage: base ----------
FROM python:${PYTHON_VERSION}-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    POETRY_VIRTUALENVS_CREATE=false

# Системные библиотеки (asyncpg, weasyprint и т.п.)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
        ca-certificates \
        && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ---------- Stage: dev (tooling, hot-reload) ----------
FROM base AS dev

# Установка зависимостей разработки
COPY requirements.txt requirements-dev.txt ./
RUN pip install -r requirements-dev.txt

# pytest, ruff и т.п. уже в requirements-dev.txt
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ---------- Stage: runtime (prod) ----------
FROM base AS runtime

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && \
    apt-get purge -y --auto-remove build-essential

COPY . /app

# Создать непривилегированного пользователя
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
