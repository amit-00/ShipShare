from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import httpx

from .config import Settings


class InternalSyncError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(slots=True)
class InternalCommand:
    endpoint: str
    payload: dict[str, Any]


class DjangoInternalClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            headers={
                "Content-Type": "application/json",
                "X-Internal-Token": settings.internal_shared_secret,
            },
        )

    async def send(self, command: InternalCommand) -> dict[str, Any]:
        response = await self._client.post(urljoin(f"{self.settings.internal_base_url}/", command.endpoint), json=command.payload)
        if response.is_success:
            return response.json()
        raise InternalSyncError(
            f"Internal sync failed for {command.endpoint} with status {response.status_code}: {response.text}",
            status_code=response.status_code,
        )

    async def aclose(self) -> None:
        await self._client.aclose()
