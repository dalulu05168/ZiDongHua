import os
import tempfile
from fastapi.testclient import TestClient
from backend.app import app

def test_management_flow(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setenv("XBW_DB_PATH", tmp + "/data.sqlite3")
        monkeypatch.setenv("XBW_API_KEY", "admin_test")
        monkeypatch.setenv("XBW_TG_KEY", "worker_test")
        monkeypatch.setenv("DRY_RUN", "true")
        monkeypatch.setenv("XBW_SEND_ENABLED", "false")
        with TestClient(app) as client:
            admin = {"X-API-Key": "admin_test"}
            tg = {"X-TG-Key": "worker_test"}
            assert client.get("/health").json()["real_sending"] is False
            assert client.get("/api/routes").status_code == 401
            assert client.get("/api/routes", headers=tg).status_code == 401
            assert client.post("/api/telegram/events", json={
                "tg_account":"tg1","tg_chat_id":"-10042","tg_message_id":"1","text":"hello"
            }, headers=admin).status_code == 401
            rule = {"tg_account":"tg1", "tg_chat_id":"-10042",
                    "wa_session":"wa1", "wa_group_jid":"12345@g.us"}
            created = client.post("/api/routes",headers=admin,json=rule)
            assert created.status_code == 201, created.text
            rid = created.json()["id"]
            assert created.json()["enabled"] is False
            assert client.post("/api/routes",headers=admin,json=rule).status_code == 409
            event = {"tg_account":"tg1","tg_chat_id":"-10042","tg_message_id":"1","text":"hello"}
            assert client.post("/api/telegram/events",headers=tg,json=event).json()["ignored"] is True
            assert client.patch(f"/api/routes/{rid}",headers=admin,json={"enabled":True}).status_code == 200
            assert client.get("/api/telegram/allowed/tg1",headers=tg).json()["chat_ids"] == ["-10042"]
            assert client.post("/api/telegram/events",headers=tg,json=event).json()["created"] == 1
            assert client.post("/api/telegram/events",headers=tg,json=event).json()["duplicate"] is True
            records = client.get("/api/deliveries",headers=admin).json()
            assert len(records) == 1 and records[0]["status"] == "pending_review"
            delivery_id = records[0]["id"]
            assert client.patch(f"/api/routes/{rid}",headers=admin,json={"enabled":False}).status_code == 200
            assert client.post(f"/api/deliveries/{delivery_id}/simulate",headers=admin).status_code == 409
            assert client.post(f"/api/deliveries/{delivery_id}/reject",headers=admin).json()["network_sent"] is False
            assert client.post(f"/api/deliveries/{delivery_id}/reject",headers=admin).status_code == 409

def test_simulation_does_not_send(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setenv("XBW_DB_PATH", tmp + "/db.sqlite3")
        monkeypatch.setenv("XBW_API_KEY", "admin_test")
        monkeypatch.setenv("XBW_TG_KEY", "worker_test")
        monkeypatch.setenv("DRY_RUN", "false")  # even unsafe env cannot send from this version
        monkeypatch.setenv("XBW_SEND_ENABLED", "true")
        with TestClient(app) as client:
            admin = {"X-API-Key": "admin_test"}
            tg = {"X-TG-Key": "worker_test"}
            r = client.post("/api/routes", headers=admin,json={
                "tg_account":"t","tg_chat_id":"-1","wa_session":"w","wa_group_jid":"123@g.us"}).json()
            client.patch(f"/api/routes/{r['id']}",headers=admin,json={"enabled":True})
            event = client.post("/api/telegram/events",headers=tg,json={
                "tg_account":"t","tg_chat_id":"-1","tg_message_id":"10","text":"message"}).json()
            result = client.post(f"/api/deliveries/{event['delivery_ids'][0]}/simulate",headers=admin)
            assert result.json()=={"id":event["delivery_ids"][0],"status":"simulated","network_sent":False}
            assert client.get("/health").json()["real_sending"] is False

def test_interface_and_validation(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setenv("XBW_DB_PATH", tmp + "/db.sqlite3")
        monkeypatch.setenv("XBW_API_KEY", "admin_test")
        with TestClient(app) as client:
            assert "小霸王" in client.get("/").text
            assert client.post("/api/routes",headers={"X-API-Key":"admin_test"},json={
                "tg_account":"tg", "tg_chat_id":"-1","wa_session":"wa","wa_group_jid":"invalid"
            }).status_code == 422
