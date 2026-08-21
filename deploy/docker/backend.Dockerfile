FROM python:3.12.10-slim-bookworm

ARG PYPI_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_DEFAULT_INDEX=${PYPI_INDEX_URL} \
    UV_CONCURRENT_DOWNLOADS=4 \
    UV_HTTP_TIMEOUT=120 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
RUN python -m pip install --no-cache-dir --index-url "${PYPI_INDEX_URL}" uv==0.6.14
COPY pyproject.toml uv.lock README.md ./
COPY packages ./packages
COPY apps ./apps
COPY skills ./skills
COPY migrations ./migrations
COPY alembic.ini ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev

RUN addgroup --system synapsekb && adduser --system --ingroup synapsekb synapsekb \
    && mkdir -p /data/storage && chown -R synapsekb:synapsekb /app /data
USER synapsekb

CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
