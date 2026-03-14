from __future__ import annotations

import json

from webhook_app.github import normalize_commands, parse_webhook, verify_signature


def test_verify_signature_accepts_valid_signature() -> None:
    secret = "top-secret"
    body = b'{"action":"created"}'
    import hashlib
    import hmac

    signature = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    assert verify_signature(secret, body, signature) is True


def test_installation_event_normalizes_to_upsert_command() -> None:
    payload = {
        "action": "created",
        "installation": {
            "id": 123,
            "account": {"login": "amit", "id": 456},
            "permissions": {"contents": "read"},
            "events": ["installation", "installation_repositories"],
        },
    }
    webhook = parse_webhook(
        event_type="installation",
        delivery_id="delivery-1",
        raw_body=json.dumps(payload).encode("utf-8"),
    )
    commands = normalize_commands(webhook)

    assert len(commands) == 1
    assert commands[0].endpoint == "internal/github/installations/upsert"
    assert commands[0].payload["installation_id"] == 123


def test_installation_repositories_event_normalizes_add_and_remove() -> None:
    payload = {
        "action": "added",
        "installation": {"id": 123},
        "repositories_added": [{"id": 1, "name": "repo", "full_name": "amit/repo", "owner": {"login": "amit"}}],
        "repositories_removed": [{"id": 2}],
    }
    webhook = parse_webhook(
        event_type="installation_repositories",
        delivery_id="delivery-2",
        raw_body=json.dumps(payload).encode("utf-8"),
    )
    commands = normalize_commands(webhook)

    assert [command.endpoint for command in commands] == [
        "internal/github/installations/repositories/sync",
        "internal/github/repositories/access/revoke",
    ]
