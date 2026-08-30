# --- Builder: resolves deps and produces the static asset bundle ---
FROM python:3.12-slim AS builder

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY . .
RUN uv sync --frozen --no-dev

# collectstatic must load Django settings, and SECRET_KEY has no
# default by design (see settings.py) - this placeholder satisfies
# that at build time only. The app never runs with it; the real value
# is injected at container start from the secrets store.
ENV DJANGO_SECRET_KEY=build-time-placeholder
RUN uv run python manage.py collectstatic --noinput

# --- Runtime: lean image, no build tooling, non-root user ---
FROM python:3.12-slim AS runtime

RUN useradd --create-home --shell /usr/sbin/nologin appuser

WORKDIR /app

COPY --from=builder /app /app
RUN chown -R appuser:appuser /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/src"

USER appuser

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
