"""Webhook test endpoint."""
from __future__ import annotations

import ipaddress
import socket
import urllib.parse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.auth.middleware import require_roles
from app.models.api_key import APIKey
from app.services.webhook_sender import send_webhook

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def validate_webhook_url(url: str) -> None:
    """Reject non-https schemes and private, loopback, or link-local targets.

    Raises ValueError with a safe message; callers map it to HTTP 400.
    Resolves the hostname so a public name that points at a private address
    is rejected too.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("Webhook URL must use https")
    hostname = parsed.hostname or ""
    if not hostname:
        raise ValueError("Webhook URL must include a hostname")
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ValueError("Webhook hostname does not resolve") from exc
    for info in infos:
        addr = ipaddress.ip_address(info[4][0])
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
            raise ValueError("Webhook URL must not target a private address")


def _validate_webhook_url(url: str) -> None:
    try:
        validate_webhook_url(url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class WebhookTestRequest(BaseModel):
    url: str
    secret: str = ""


@router.post("/test")
async def test_webhook(
    req: WebhookTestRequest,
    api_key: APIKey = Depends(require_roles("operator")),
):
    """Send a test webhook payload to verify your endpoint."""
    await run_in_threadpool(_validate_webhook_url, req.url)
    success = await send_webhook(
        req.url,
        {"event": "webhook.test", "message": "DocExtract AI webhook test"},
        req.secret,
    )
    return {"success": success, "url": req.url}
