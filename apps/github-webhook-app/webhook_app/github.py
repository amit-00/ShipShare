from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any

from .internal_client import InternalCommand


class UnsupportedEventError(ValueError):
    """Raised when the webhook event/action pair is not handled by this service."""


@dataclass(slots=True)
class ParsedWebhook:
    event_type: str
    delivery_id: str
    action: str | None
    installation_id: int | None
    payload: dict[str, Any]
    payload_hash: str


def verify_signature(secret: str, raw_body: bytes, signature_header: str | None) -> bool:
    if not secret or not signature_header:
        return False
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def parse_webhook(
    *,
    event_type: str,
    delivery_id: str,
    raw_body: bytes,
) -> ParsedWebhook:
    payload = json.loads(raw_body.decode("utf-8"))
    action = payload.get("action")
    installation = payload.get("installation") or {}
    installation_id = installation.get("id")
    payload_hash = hashlib.sha256(raw_body).hexdigest()
    return ParsedWebhook(
        event_type=event_type,
        delivery_id=delivery_id,
        action=action,
        installation_id=installation_id,
        payload=payload,
        payload_hash=payload_hash,
    )


def normalize_commands(webhook: ParsedWebhook) -> list[InternalCommand]:
    if webhook.event_type == "installation":
        return _installation_commands(webhook.payload)
    if webhook.event_type == "installation_repositories":
        return _installation_repositories_commands(webhook.payload)
    raise UnsupportedEventError(f"Unsupported GitHub event: {webhook.event_type}")


def _installation_commands(payload: dict[str, Any]) -> list[InternalCommand]:
    action = payload.get("action")
    installation = payload["installation"]
    account = installation["account"]

    if action in {"created", "new_permissions_accepted", "unsuspend"}:
        return [
            InternalCommand(
                endpoint="internal/github/installations/upsert",
                payload={
                    "installation_id": installation["id"],
                    "account_login": account["login"],
                    "account_id": account["id"],
                    "permissions": installation.get("permissions", {}),
                    "events": installation.get("events", []),
                },
            )
        ]

    if action in {"deleted", "suspend"}:
        return [
            InternalCommand(
                endpoint="internal/github/installations/deactivate",
                payload={
                    "installation_id": installation["id"],
                    "suspended_at": payload.get("suspended_at"),
                },
            )
        ]

    raise UnsupportedEventError(f"Unsupported installation action: {action}")


def _installation_repositories_commands(payload: dict[str, Any]) -> list[InternalCommand]:
    installation = payload["installation"]
    repositories_added = payload.get("repositories_added", [])
    repositories_removed = payload.get("repositories_removed", [])

    commands: list[InternalCommand] = []
    if repositories_added:
        commands.append(
            InternalCommand(
                endpoint="internal/github/installations/repositories/sync",
                payload={
                    "installation_id": installation["id"],
                    "repositories": repositories_added,
                    "sync_mode": "delta",
                },
            )
        )
    if repositories_removed:
        commands.append(
            InternalCommand(
                endpoint="internal/github/repositories/access/revoke",
                payload={
                    "installation_id": installation["id"],
                    "repository_ids": [repository["id"] for repository in repositories_removed],
                },
            )
        )
    if commands:
        return commands
    raise UnsupportedEventError("installation_repositories event carried no repository changes")
