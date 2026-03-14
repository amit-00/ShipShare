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

RUN uv sync --frozen --no-dev --package shipshare-core-app

ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /workspace/apps/core-app

EXPOSE 8000

CMD ["uv", "run", "--frozen", "--package", "shipshare-core-app", "python", "manage.py", "runserver", "0.0.0.0:8000"]
