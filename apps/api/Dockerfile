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
# weasyprint: Pango/HarfBuzz (рендер PDF, §16 п.25) + DejaVu (кириллица).
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
        ca-certificates \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz0b \
        fonts-dejavu-core \
        && rm -rf /var/lib/apt/lists/*

# Сам pip обновляем в base — иначе advisory на старый pip наследуют оба stage (§16 п.30)
RUN python -m pip install --upgrade pip

WORKDIR /app

# ---------- Stage: dev (tooling, hot-reload) ----------
FROM base AS dev

# Установка зависимостей разработки
COPY requirements.txt requirements-dev.txt ./
RUN pip install -r requirements-dev.txt

# pytest, ruff и т.п. уже в requirements-dev.txt
EXPOSE 8000
# --proxy-headers + --forwarded-allow-ips: доверяем заголовкам X-Forwarded-For от nginx
# (сеть docker доверенная), иначе request.client.host = IP nginx и пер-IP rate-limit'ы
# (например login 5/15min) становятся ГЛОБАЛЬНЫМИ: 5 неудачных входов кого угодно → 429 для всех.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", "--proxy-headers", "--forwarded-allow-ips", "*"]

# ---------- Stage: runtime (prod) ----------
FROM base AS runtime

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && \
    apt-get purge -y --auto-remove build-essential

# Pango/HarfBuzz/шрифты для weasyprint — ставим ПОСЛЕ purge build-essential,
# чтобы --auto-remove не снёс их вместе с build-депами (§16 п.25).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz0b \
        fonts-dejavu-core \
        && rm -rf /var/lib/apt/lists/*

COPY . /app

# Создать непривилегированного пользователя
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
# --proxy-headers + --forwarded-allow-ips: доверяем заголовкам X-Forwarded-For от nginx
# (сеть docker доверенная), иначе request.client.host = IP nginx и пер-IP rate-limit'ы
# (например login 5/15min) становятся ГЛОБАЛЬНЫМИ: 5 неудачных входов кого угодно → 429 для всех.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
