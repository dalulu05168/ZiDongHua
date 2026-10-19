"""End-to-end local smoke test with real HTTP servers and NO WhatsApp/TG login.

The WhatsApp bridge is started with no active accounts, ensuring no outbound messages.
The Telegram source is simulated by an authenticated request to the actual backend.
"""
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_ready(url, process, seconds=35):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError("Server exited before HTTP readiness")
        try:
            with httpx.Client(timeout=0.5) as client:
                client.get(url)
            return
        except httpx.RequestError:
            time.sleep(0.2)
    raise AssertionError("Server failed to listen in time: " + url)


def assert_status(response, expected):
    assert response.status_code == expected, (response.status_code, response.text[:350])
    return response.json()


def run_smoke():
    with tempfile.TemporaryDirectory(prefix="xbw-smoke-") as temp:
        backend_port, bridge_port = free_port(), free_port()
        root = f"http://127.0.0.1:{backend_port}"
        bridge_url = f"http://127.0.0.1:{bridge_port}"
        admin = secrets.token_urlsafe(32)
        telegram = secrets.token_urlsafe(32)
        wa = secrets.token_urlsafe(32)
        env = dict(os.environ)
        env.update({
            "XBW_DB_PATH": str(Path(temp) / "xiaobawang.sqlite"),
            "XBW_API_KEY": admin, "XBW_TG_KEY": telegram, "XBW_BRIDGE_KEY": wa,
            "DRY_RUN": "true", "XBW_SEND_ENABLED": "false",
            "BAILEYS_SEND_ENABLED": "false", "XBW_BRIDGE_PORT": str(bridge_port),
            "XBW_BRIDGE_URL": bridge_url, "WA_AUTH_DIR": str(Path(temp) / "auth"),
        })
        bridge = subprocess.Popen(
            ["node", "bridge.mjs"], cwd=ROOT / "integrations" / "whatsapp",
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        backend = None
        try:
            wait_ready(bridge_url + "/v1/sessions", bridge)
            backend = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "backend.app:app",
                 "--host", "127.0.0.1", "--port", str(backend_port)],
                cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            wait_ready(root + "/health", backend)
            with httpx.Client(timeout=8) as http:
                admin_h = {"X-API-Key": admin}
                tg_h = {"X-TG-Key": telegram}
                bridge_h = {"X-Bridge-Key": wa}
                assert_status(http.get(bridge_url + "/v1/sessions"), 401)
                assert_status(http.get(bridge_url + "/v1/sessions", headers=bridge_h), 200) == []
                assert_status(http.get(root + "/api/routes"), 401)
                health = assert_status(http.get(root + "/health"), 200)
                assert health["real_sending"] is False

                # Real FastAPI-to-Node bridge HTTP integration; no WhatsApp pairing.
                assert_status(http.get(root + "/api/whatsapp/sessions", headers=admin_h), 200) == []
                assert_status(http.post(bridge_url + "/v1/sessions/invalid@alias/connect", headers=bridge_h), 400)
                assert_status(http.get(root + "/api/chatwoot/status", headers=admin_h), 200)

                rule = {"tg_account": "tg01", "tg_chat_id": "-1001234",
                        "wa_session": "wa01", "wa_group_jid": "123456789@g.us"}
                entry = assert_status(http.post(root + "/api/routes", headers=admin_h, json=rule), 201)
                rid = entry["id"]
                assert entry["enabled"] is False
                event = {"tg_account": "tg01", "tg_chat_id": "-1001234",
                         "tg_message_id": "22", "text": "Hello from a simulated group"}
                assert assert_status(http.post(root + "/api/telegram/events", headers=tg_h, json=event), 200)["ignored"]
                assert_status(http.patch(root + f"/api/routes/{rid}", headers=admin_h, json={"enabled": True}), 200)
                allowed = assert_status(http.get(root + "/api/telegram/allowed/tg01", headers=tg_h), 200)
                assert allowed["chat_ids"] == ["-1001234"]
                first = assert_status(http.post(root + "/api/telegram/events", headers=tg_h, json=event), 200)
                assert first["created"] == 1
                repeated = assert_status(http.post(root + "/api/telegram/events", headers=tg_h, json=event), 200)
                assert repeated["duplicate"] is True
                deliveries = assert_status(http.get(root + "/api/deliveries", headers=admin_h), 200)
                assert len(deliveries) == 1 and deliveries[0]["status"] == "pending_review"
                assert_status(http.patch(root + f"/api/routes/{rid}", headers=admin_h, json={"enabled": False}), 200)
                assert_status(http.post(root + f"/api/deliveries/{deliveries[0]['id']}/simulate", headers=admin_h), 409)
                rejected = assert_status(http.post(root + f"/api/deliveries/{deliveries[0]['id']}/reject", headers=admin_h), 200)
                assert rejected["network_sent"] is False

            print("PASS: real FastAPI and Node HTTP processes started and linked")
            print("PASS: unauthenticated requests blocked, inactive route filtered")
            print("PASS: TG event routed, deduplicated, paused route blocked")
            print("PASS: simulated review recorded; no external WA/TG messages sent")
        finally:
            for process in (backend, bridge):
                if process and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=7)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=4)


if __name__ == "__main__":
    run_smoke()
