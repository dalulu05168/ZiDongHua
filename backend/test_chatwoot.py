import hashlib
import hmac
import json
import time
import tempfile

from fastapi.testclient import TestClient
from backend.app import app


def test_chatwoot_missing_settings(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setenv("XBW_DB_PATH", tmp + "/test.sqlite")
        monkeypatch.setenv("XBW_API_KEY", "admin_test")
        for key in ("CHATWOOT_URL", "CHATWOOT_ACCOUNT_ID", "CHATWOOT_API_TOKEN", "CHATWOOT_WEBHOOK_SECRET"):
            monkeypatch.delenv(key, raising=False)
        with TestClient(app) as client:
            assert client.get("/api/chatwoot/status").status_code == 401
            head = {"X-API-Key": "admin_test"}
            assert client.get("/api/chatwoot/status", headers=head).json()["configured"] is False
            assert client.get("/api/chatwoot/inboxes", headers=head).status_code == 503
            assert client.post("/api/chatwoot/webhook", content=b"{}").status_code == 503


def test_chatwoot_webhook_signature_and_dedup(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setenv("XBW_DB_PATH", tmp + "/test.sqlite")
        monkeypatch.setenv("XBW_API_KEY", "admin_test")
        monkeypatch.setenv("CHATWOOT_WEBHOOK_SECRET", "unique_test_secret")
        body = json.dumps({"event": "conversation_created", "conversation": {"id": 51}}).encode()
        stamp = str(int(time.time()))
        signature = "sha256=" + hmac.new(b"unique_test_secret", stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
        with TestClient(app) as client:
            headers = {"X-Chatwoot-Timestamp": stamp, "X-Chatwoot-Signature": signature, "X-Chatwoot-Delivery": "abc-1"}
            assert client.post("/api/chatwoot/webhook", content=body).status_code == 401
            assert client.post("/api/chatwoot/webhook", content=body, headers={**headers, "X-Chatwoot-Signature": "incorrect"}).status_code == 401
            first = client.post("/api/chatwoot/webhook", content=body, headers=headers)
            assert first.status_code == 200, first.text
            assert first.json()["recorded"] and first.json()["network_sent"] is False
            assert client.post("/api/chatwoot/webhook", content=body, headers=headers).json()["duplicate"]
            assert len(client.get("/api/chatwoot-events", headers={"X-API-Key": "admin_test"}).json()) == 1
            old = {**headers, "X-Chatwoot-Timestamp": "1"}
            assert client.post("/api/chatwoot/webhook", content=body, headers=old).status_code == 401
