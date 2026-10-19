"""Chat workspace checks. No personal or platform account is required."""
import tempfile
from fastapi.testclient import TestClient
from backend.app import app


def test_chat_home_and_settings(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setenv("XBW_DB_PATH", tmp + "/db.sqlite3")
        with TestClient(app) as client:
            page = client.get("/")
            assert page.status_code == 200
            assert "多账号聊天工作台" in page.text
            assert 'id="threadList"' in page.text
            assert 'id="messages"' in page.text
            assert 'id="routeForm"' in page.text
            assert 'class="send" disabled' in page.text
            assert client.get("/settings").status_code == 200
            assert "多账号聊天工作台" in client.get("/settings").text
            assert "V0.2 · 仅模拟" not in client.get("/settings").text
            assert 'id="settingsModal"' in client.get("/").text


def test_readonly_whatsapp_chat_bridge(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setenv("XBW_DB_PATH", tmp + "/db.sqlite3")
        monkeypatch.setenv("XBW_API_KEY", "admin_test")
        calls = []
        def fake_bridge(method, path):
            calls.append((method, path))
            if path.endswith("/messages"):
                return {"jid": "123@g.us", "messages": [{"text":"Hello"}], "sending_enabled": False}
            return {"chats": [{"jid": "123@g.us", "title":"Test group"}], "sending_enabled": False}
        monkeypatch.setattr("backend.app.bridge", fake_bridge)
        with TestClient(app) as client:
            assert client.get("/api/chat/whatsapp/wa1/chats").status_code == 401
            headers = {"X-API-Key":"admin_test"}
            res = client.get("/api/chat/whatsapp/wa1/chats", headers=headers)
            assert res.status_code == 200
            assert res.json()["chats"][0]["title"] == "Test group"
            messages = client.get("/api/chat/whatsapp/wa1/chats/123@g.us/messages", headers=headers)
            assert messages.status_code == 200
            assert messages.json()["sending_enabled"] is False
            assert client.get("/api/chat/whatsapp/wa1/chats/not-a-jid/messages",headers=headers).status_code==422
            assert all(method=="GET" for method,_ in calls)


def test_telegram_threads_only_after_matching_enabled_route(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setenv("XBW_DB_PATH", tmp + "/db.sqlite3")
        monkeypatch.setenv("XBW_API_KEY", "admin_test")
        monkeypatch.setenv("XBW_TG_KEY", "tg_test")
        headers={"X-API-Key":"admin_test"}
        worker={"X-TG-Key":"tg_test"}
        with TestClient(app) as client:
            assert client.get("/api/chat/telegram/threads",headers=headers).json()==[]
            data={"tg_account":"tg1","tg_chat_id":"-10055","wa_session":"wa1","wa_group_jid":"123@g.us"}
            rid=client.post("/api/routes",json=data,headers=headers).json()["id"]
            client.patch(f"/api/routes/{rid}",json={"enabled":True},headers=headers)
            incoming={"tg_account":"tg1","tg_chat_id":"-10055","tg_message_id":"101","text":"A sample source message"}
            assert client.post("/api/telegram/events",json=incoming,headers=worker).status_code==200
            threads=client.get("/api/chat/telegram/threads",headers=headers).json()
            assert len(threads)==1 and threads[0]["tg_account"]=="tg1"
            messages=client.get("/api/chat/telegram/tg1/-10055/messages",headers=headers)
            assert messages.json()["messages"][0]["text"]=="A sample source message"
            assert messages.json()["sending_enabled"] is False


def test_pause_saved_whatsapp_account_requires_admin(monkeypatch):
    """Account pause is a local credential-preserving control, not a message send."""
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setenv("XBW_DB_PATH", tmp + "/db.sqlite3")
        monkeypatch.setenv("XBW_API_KEY", "admin_test")
        calls = []
        def fake_bridge(method, path):
            calls.append((method, path))
            return {"name": "wa1", "status": "paused", "credentials_preserved": True}
        monkeypatch.setattr("backend.app.bridge", fake_bridge)
        with TestClient(app) as client:
            url = "/api/whatsapp/sessions/wa1/pause"
            assert client.post(url).status_code == 401
            assert client.post("/api/whatsapp/sessions/../pause", headers={"X-API-Key": "admin_test"}).status_code in (404, 422)
            res = client.post(url, headers={"X-API-Key": "admin_test"})
            assert res.status_code == 200
            assert res.json()["credentials_preserved"] is True
            assert calls == [("POST", "/v1/sessions/wa1/pause")]
