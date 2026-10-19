"""Local Telegram desktop features; no real Telegram account or network needed."""
import asyncio
import tempfile
from fastapi.testclient import TestClient
from backend.app import app, save_telegram_event
from backend.telegram_service import TelegramService


class FakeTelegram:
    def accounts(self):
        return [{"alias":"tg_01","status":"connected","authorized":True,"sending_enabled":False}]

    async def start(self, alias, api_id, api_hash, phone):
        self.start_args = (alias, api_id, api_hash, phone)
        return {"alias":alias,"status":"code_sent","sending_enabled":False}

    async def verify(self, alias, code, password):
        self.verify_args = (alias,code,password)
        return {"alias":alias,"status":"connected","sending_enabled":False}

    async def groups(self, alias):
        assert alias == "tg_01"
        return [
            {"id":"-1001234","title":"授权测试群一"},
            {"id":"-1005678","title":"授权测试群二"}
        ]


def test_desktop_telegram_authorization_group_selection_and_inbox(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setenv("XBW_DB_PATH",tmp+"/db.sqlite3")
        monkeypatch.setenv("XBW_TG_DIR",tmp+"/telegram")
        monkeypatch.setenv("XBW_API_KEY","admin_telegram_test")
        monkeypatch.setenv("XBW_TG_KEY","tg_worker_test")
        with TestClient(app) as client:
            fake=FakeTelegram()
            app.state.telegram_service=fake
            admin={"X-API-Key":"admin_telegram_test"}
            phone={"alias":"tg_01","api_id":321123,"api_hash":"a"*32,"phone":"+40123456789"}
            assert client.get("/api/telegram/accounts").status_code == 401
            assert client.post("/api/telegram/accounts/start",json=phone).status_code == 401
            assert client.get("/api/telegram/accounts",headers=admin).json()[0]["status"]=="connected"
            start=client.post("/api/telegram/accounts/start",json=phone,headers=admin)
            assert start.status_code == 200,start.text
            assert fake.start_args==("tg_01",321123,"a"*32,"+40123456789")
            assert "api_hash" not in start.text and "40123456789" not in start.text
            assert client.post("/api/telegram/accounts/start",json={**phone,"phone":"123"},headers=admin).status_code==422
            verify=client.post("/api/telegram/accounts/tg_01/verify",json={"code":"12345"},headers=admin)
            assert verify.status_code == 200
            assert verify.json()["sending_enabled"] is False
            assert client.get("/api/telegram/accounts/tg_01/groups",headers=admin).json()[0]["id"]=="-1001234"
            url="/api/telegram/accounts/tg_01/monitors"
            assert client.put(url,json={"chat_ids":["-1001234"]}).status_code == 401
            assert client.put(url,json={"chat_ids":["-99"]},headers=admin).status_code == 422
            result=client.put(url,json={"chat_ids":["-1001234","-1001234"]},headers=admin)
            assert result.status_code==200,result.text
            assert result.json()=={"alias":"tg_01","selected":1,"sending_enabled":False}
            saved=client.get(url,headers=admin).json()
            assert len(saved)==1 and saved[0]["title"]=="授权测试群一"
            ignored=save_telegram_event("tg_01","-1005678","1","not selected")
            assert ignored["ignored"] is True
            accepted=save_telegram_event("tg_01","-1001234","1","read only group message")
            assert accepted["ignored"] is False
            assert accepted["network_sent"] is False and accepted["created"] == 0
            repeated=save_telegram_event("tg_01","-1001234","1","read only group message")
            assert repeated["duplicate"] is True
            inbox=client.get("/api/chat/telegram/threads",headers=admin).json()
            assert len(inbox)==1 and inbox[0]["tg_chat_id"]=="-1001234"
            assert client.get("/api/deliveries",headers=admin).json()==[]
            cleared=client.put(url,json={"chat_ids":[]},headers=admin)
            assert cleared.json()["selected"]==0
            assert save_telegram_event("tg_01","-1001234","2","now disabled")["ignored"] is True


def test_telegram_login_forms_are_in_desktop_chat_window(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setenv("XBW_DB_PATH",tmp+"/db.sqlite3")
        monkeypatch.setenv("XBW_TG_DIR",tmp+"/telegram")
        with TestClient(app) as client:
            page=client.get("/").text
            for item in ("tgLoginModal","tgApiId","tgApiHash","tgPhone","tgCode",
                         "tgPassword","tgGroupsModal","tgGroupSave","tgGroupsButton"):
                assert f'id="{item}"' in page
            assert 'class="send" disabled' in page
            assert "Telegram 验证码" in page


def test_service_code_login_and_groups_with_fake_client(monkeypatch):
    class Client:
        def __init__(self):
            self.connected=False
            self.callbacks=[]
        async def connect(self): self.connected=True
        def is_connected(self): return self.connected
        async def send_code_request(self, phone):
            return type("Code",(),{"phone_code_hash":"code_hash"})()
        async def sign_in(self, phone=None, code=None, phone_code_hash=None, password=None):
            assert code=="98765" and phone_code_hash=="code_hash"
        async def is_user_authorized(self):return True
        async def get_me(self):return type("Me",(),{"id":100})()
        def on(self, _event):
            def decorator(fn):
                self.callbacks.append(fn)
                return fn
            return decorator
        async def iter_dialogs(self):
            yield type("Group",(),{"is_group":True,"id":-1001234,"name":"Demo"})()
            yield type("Channel",(),{"is_group":False,"id":-1009999,"name":"Not a group"})()
        async def disconnect(self): self.connected=False

    async def scenario(directory):
        service=TelegramService(directory,lambda *args:None)
        client=Client()
        monkeypatch.setattr(service,"_client",lambda *args:client)
        monkeypatch.setattr(service,"_save_api",lambda *args:None)
        try:
            start=await service.start("tg_01",123456,"b"*32,"+40123456789")
            assert start["status"]=="code_sent"
            completed=await service.verify("tg_01","98765")
            assert completed["status"]=="connected"
            assert completed["telegram_user_id"]==100
            assert service.accounts()[0]["authorized"] is True
            assert await service.groups("tg_01")==[{"id":"-1001234","title":"Demo"}]
            assert len(client.callbacks)==1
        finally:
            await service.shutdown()

    with tempfile.TemporaryDirectory() as tmp:
        asyncio.run(scenario(tmp))
