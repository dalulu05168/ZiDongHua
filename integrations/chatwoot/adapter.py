"""Read-only Chatwoot Application API client and signed webhook verifier.

No POST requests to Chatwoot; this module cannot send customer messages.
"""
import hashlib
import hmac
import os
import time
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException


def _settings():
    url = os.getenv("CHATWOOT_URL", "").rstrip("/")
    account = os.getenv("CHATWOOT_ACCOUNT_ID", "")
    token = os.getenv("CHATWOOT_API_TOKEN", "")
    if not url or not account.isdecimal() or not token:
        raise HTTPException(503, "Chatwoot is not configured")
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise HTTPException(503, "Invalid Chatwoot URL")
    if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1", "chatwoot"):
        raise HTTPException(503, "Use HTTPS for remote Chatwoot")
    return url, account, token


def available():
    return bool(os.getenv("CHATWOOT_URL") and os.getenv("CHATWOOT_ACCOUNT_ID") and os.getenv("CHATWOOT_API_TOKEN"))


def get_collection(collection):
    if collection not in ("inboxes", "conversations", "contacts"):
        raise HTTPException(400, "Unsupported Chatwoot resource")
    url, account, token = _settings()
    try:
        with httpx.Client(timeout=8, follow_redirects=False) as client:
            response = client.get(
                f"{url}/api/v1/accounts/{account}/{collection}",
                headers={"api_access_token": token, "Accept": "application/json"},
            )
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, "Chatwoot request failed") from exc


def validate_webhook(raw: bytes, signature: str | None, timestamp: str | None):
    secret = os.getenv("CHATWOOT_WEBHOOK_SECRET", "")
    if not secret:
        raise HTTPException(503, "Chatwoot webhook is not configured")
    if len(raw) > 262144:
        raise HTTPException(413, "Payload too large")
    if not timestamp or not timestamp.isdecimal():
        raise HTTPException(401, "Missing webhook timestamp")
    if abs(int(time.time()) - int(timestamp)) > 300:
        raise HTTPException(401, "Expired webhook")
    digest = hmac.new(secret.encode("utf-8"), timestamp.encode("ascii") + b"." + raw, hashlib.sha256).hexdigest()
    expected = "sha256=" + digest
    if not signature or not hmac.compare_digest(expected, signature):
        raise HTTPException(401, "Invalid webhook signature")
    return hashlib.sha256(raw).hexdigest()
