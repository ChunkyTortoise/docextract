"""Webhook test endpoint."""
from __future__ import annotations

import ipaddress
import urllib.parse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth.middleware import get_api_key
from app.models.api_key import APIKey
from app.services.webhook_sender import send_webhook

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _validate_webhook_url(url: str) -> None:
    """Reject non-https schemes and RFC-1918 / loopback targets."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise HTTPException(status_code=400, detail="Webhook URL must use https")
    hostname = parsed.hostname or ""
    try:
        addr = ipaddress.ip_address(hostname)
        if addr.is_private or addr.is_loopback or addr.is_link_local:
            raise HTTPException(status_code=400, detail="Webhook URL must not target a private address")
    except ValueError:
        pass  # domain name, not an IP -- allow it


class WebhookTestRequest(BaseModel):
    url: str
    secret: str = ""


@router.post("/test")
async def test_webhook(
    req: WebhookTestRequest,
    api_key: APIKey = Depends(get_api_key),
):
    """Send a test webhook payload to verify your endpoint."""
    _validate_webhook_url(req.url)
    success = await send_webhook(
        req.url,
        {"event": "webhook.test", "message": "DocExtract AI webhook test"},
        req.secret,
    )
    return {"success": success, "url": req.url}
