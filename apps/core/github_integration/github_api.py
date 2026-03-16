from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import jwt
from django.conf import settings


@dataclass(slots=True)
class InstallationSnapshot:
    installation_id: int
    account_login: str
    account_id: int
    permissions: dict[str, Any]
    events: list[str]
    raw: dict[str, Any]


class GitHubAppClient:
    def __init__(self) -> None:
        self._client = httpx.Client(
            timeout=httpx.Timeout(10.0),
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "ShipShare core",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    def _app_jwt(self) -> str:
        now = datetime.now(tz=timezone.utc)
        return jwt.encode(
            {
                "iat": int((now - timedelta(seconds=30)).timestamp()),
                "exp": int((now + timedelta(minutes=9)).timestamp()),
                "iss": settings.GITHUB_APP_ID,
            },
            settings.GITHUB_APP_PRIVATE_KEY,
            algorithm="RS256",
        )

    def _app_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._app_jwt()}"}

    def _installation_headers(self, installation_id: int) -> dict[str, str]:
        response = self._client.post(
            f"https://api.github.com/app/installations/{installation_id}/access_tokens",
            headers=self._app_headers(),
        )
        response.raise_for_status()
        token = response.json()["token"]
        return {"Authorization": f"Bearer {token}"}

    def get_installation(self, installation_id: int) -> InstallationSnapshot:
        response = self._client.get(
            f"https://api.github.com/app/installations/{installation_id}",
            headers=self._app_headers(),
        )
        response.raise_for_status()
        payload = response.json()
        account = payload["account"]
        return InstallationSnapshot(
            installation_id=payload["id"],
            account_login=account["login"],
            account_id=account["id"],
            permissions=payload.get("permissions", {}),
            events=payload.get("events", []),
            raw=payload,
        )

    def list_installation_repositories(self, installation_id: int) -> list[dict[str, Any]]:
        response = self._client.get(
            "https://api.github.com/installation/repositories",
            headers=self._installation_headers(installation_id),
        )
        response.raise_for_status()
        payload = response.json()
        return payload.get("repositories", [])

    def close(self) -> None:
        self._client.close()
