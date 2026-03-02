"""Webhook test endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth.middleware import get_api_key
from app.models.api_key import APIKey
from app.services.webhook_sender import send_webhook

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class WebhookTestRequest(BaseModel):
    url: str
    secret: str = ""


@router.post("/test")
async def test_webhook(
    req: WebhookTestRequest,
    api_key: APIKey = Depends(get_api_key),
):
    """Send a test webhook payload to verify your endpoint."""
    success = await send_webhook(
        req.url,
        {"event": "webhook.test", "message": "DocExtract AI webhook test"},
        req.secret,
    )
    return {"success": success, "url": req.url}
