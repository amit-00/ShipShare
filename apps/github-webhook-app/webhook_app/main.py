from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request

from .config import get_settings
from .dedup import DeliveryStore
from .github import UnsupportedEventError, normalize_commands, parse_webhook, verify_signature
from .internal_client import DjangoInternalClient, InternalSyncError


settings = get_settings()
delivery_store = DeliveryStore(settings.delivery_db_path)
internal_client = DjangoInternalClient(settings)


@asynccontextmanager
async def lifespan(_: FastAPI):
    delivery_store.initialize()
    yield
    await internal_client.aclose()


app = FastAPI(title=settings.app_name, lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/webhooks/github/")
async def github_webhook(
    request: Request,
    x_github_event: str = Header(...),
    x_github_delivery: str = Header(...),
    x_hub_signature_256: str | None = Header(default=None),
) -> dict[str, object]:
    raw_body = await request.body()
    if not verify_signature(settings.github_webhook_secret, raw_body, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid GitHub webhook signature.")

    try:
        webhook = parse_webhook(
            event_type=x_github_event,
            delivery_id=x_github_delivery,
            raw_body=raw_body,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {exc}") from exc

    accepted = delivery_store.accept_delivery(
        github_delivery_id=webhook.delivery_id,
        event_type=webhook.event_type,
        action=webhook.action,
        installation_id=webhook.installation_id,
        payload_hash=webhook.payload_hash,
    )
    if not accepted:
        existing = delivery_store.get(webhook.delivery_id)
        return {
            "ok": True,
            "duplicate": True,
            "processing_status": existing.processing_status if existing else "unknown",
        }

    try:
        commands = normalize_commands(webhook)
        for command in commands:
            await internal_client.send(command)
    except UnsupportedEventError as exc:
        delivery_store.mark_processed(webhook.delivery_id)
        return {"ok": True, "ignored": True, "reason": str(exc)}
    except InternalSyncError as exc:
        delivery_store.mark_failed(webhook.delivery_id, str(exc))
        retryable_status = 503 if exc.status_code in {404, 409, 429} or (exc.status_code or 500) >= 500 else 502
        raise HTTPException(status_code=retryable_status, detail="Internal sync failed.") from exc
    except Exception as exc:  # pragma: no cover - defensive fallback
        delivery_store.mark_failed(webhook.delivery_id, str(exc))
        raise HTTPException(status_code=500, detail="Unexpected webhook processing error.") from exc

    delivery_store.mark_processed(webhook.delivery_id)
    return {"ok": True, "accepted": True, "commands_sent": len(commands)}
