FROM python:3.12-slim

ENV UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir --upgrade pip uv

WORKDIR /workspace

COPY pyproject.toml uv.lock .python-version ./
COPY apps/core-app apps/core-app
COPY apps/github-webhook-app apps/github-webhook-app

RUN uv sync --frozen --no-dev --package shipshare-github-webhook-app

ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /workspace/apps/github-webhook-app

EXPOSE 8001

CMD ["uv", "run", "--frozen", "--package", "shipshare-github-webhook-app", "uvicorn", "webhook_app.main:app", "--host", "0.0.0.0", "--port", "8001"]
