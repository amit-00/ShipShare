from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class Settings:
    app_name: str = "shipshare-github-webhook-app"
    github_webhook_secret: str = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
    internal_base_url: str = os.environ.get("DJANGO_INTERNAL_BASE_URL", "http://localhost:8000")
    internal_shared_secret: str = os.environ.get("INTERNAL_SHARED_SECRET", "shipshare-internal-secret")
    delivery_db_path: Path = Path(
        os.environ.get("WEBHOOK_DELIVERY_DB_PATH", "data/webhook-deliveries.sqlite3")
    )


def get_settings() -> Settings:
    return Settings()
