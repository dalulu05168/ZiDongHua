"""In-process Telethon sessions for XiaoBaWang's local desktop UI.

Telegram first-party phone verification and optional 2FA happen inside the UI.
Only user-authorized groups that are explicitly selected are observed.
No Telegram messages are sent; session/API credentials never go to GitHub.
"""
import asyncio
import base64
import ctypes
import json
import os
import re
import sys
from pathlib import Path

from telethon import TelegramClient, events
from telethon.errors import (
    PhoneCodeExpiredError, PhoneCodeInvalidError, PhoneNumberInvalidError,
    SessionPasswordNeededError, PasswordHashInvalidError, FloodWaitError,
)

_ALIAS = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class TelegramError(Exception):
    """Sanitized user-facing failure (never includes Telegram credentials)."""


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _dpapi(data, *, decrypt=False):
    """Encrypt API credentials for the current Windows user using native DPAPI."""
    if sys.platform != "win32":
        raise TelegramError("Credential persistence requires Windows; use environment credentials for local development")
    source = ctypes.create_string_buffer(data, len(data))
    input_blob = _Blob(len(data), ctypes.cast(source, ctypes.POINTER(ctypes.c_byte)))
    output = _Blob()
    crypt = ctypes.windll.crypt32
    operation = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    if decrypt:
        ok = operation(ctypes.byref(input_blob), None, None, None, None, 0, ctypes.byref(output))
    else:
        ok = operation(ctypes.byref(input_blob), None, None, None, None, None, 0, ctypes.byref(output))
    if not ok:
        raise TelegramError("Windows could not unlock local Telegram credentials")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)


class TelegramService:
    def __init__(self, data_dir, on_message):
        self.root = Path(data_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        self.on_message = on_message
        self.clients = {}
        self.pending = {}
        self.connected = set()
        self._restoring = None

    def _path(self, alias):
        if not _ALIAS.fullmatch(alias):
            raise TelegramError("Invalid account alias")
        return self.root / alias

    def _save_api(self, alias, api_id, api_hash):
        # Save only after Telegram completes authorization; DPAPI binds to the OS user.
        if sys.platform != "win32":
            return
        raw = json.dumps({"api_id": api_id, "api_hash": api_hash}).encode("utf-8")
        protected = base64.b64encode(_dpapi(raw))
        target = self._path(alias).with_suffix(".credentials")
        temp = target.with_suffix(".credentials.tmp")
        try:
            with temp.open("wb") as stream:
                stream.write(protected)
            temp.replace(target)
        finally:
            temp.unlink(missing_ok=True)

    def _load_api(self, alias):
        target = self._path(alias).with_suffix(".credentials")
        if target.exists():
            raw = _dpapi(base64.b64decode(target.read_bytes()), decrypt=True)
            credentials = json.loads(raw.decode("utf-8"))
            return int(credentials["api_id"]), credentials["api_hash"]
        api_id, api_hash = os.getenv("TELEGRAM_API_ID", ""), os.getenv("TELEGRAM_API_HASH", "")
        if api_id.isdecimal() and api_hash:
            return int(api_id), api_hash
        raise TelegramError("No saved Telegram app credentials for this account")

    def _client(self, alias, api_id, api_hash):
        # Telethon's on-disk .session is a login credential; it stays in userData.
        return TelegramClient(str(self._path(alias)), api_id, api_hash, auto_reconnect=True)

    async def _observe(self, alias, client):
        @client.on(events.NewMessage(incoming=True))
        async def on_event(event):
            if not event.is_group or not event.raw_text or not event.raw_text.strip():
                return
            try:
                self.on_message(alias, str(event.chat_id), str(event.id), event.raw_text[:8000])
            except Exception:
                # Do not leak message content or credentials to crash logs.
                pass

    async def _connect_saved(self, alias):
        if alias in self.clients or alias in self.pending:
            return
        try:
            api_id, api_hash = self._load_api(alias)
            client = self._client(alias, api_id, api_hash)
            await asyncio.wait_for(client.connect(), timeout=25)
            if not await client.is_user_authorized():
                await client.disconnect()
                return
            await self._observe(alias, client)
            self.clients[alias] = client
            self.connected.add(alias)
        except Exception:
            # Unavailable networks do not stop the desktop application from opening.
            return

    async def restore(self):
        aliases = {p.stem for p in self.root.glob("*.credentials") if _ALIAS.fullmatch(p.stem)}
        if os.getenv("TELEGRAM_API_ID") and os.getenv("TELEGRAM_API_HASH"):
            aliases.update(p.stem for p in self.root.glob("*.session") if _ALIAS.fullmatch(p.stem))
        for alias in sorted(aliases):
            await self._connect_saved(alias)

    def start_restore(self):
        self._restoring = asyncio.create_task(self.restore())

    async def shutdown(self):
        if self._restoring:
            self._restoring.cancel()
            await asyncio.gather(self._restoring, return_exceptions=True)
        for client in list(self.clients.values()) + [x["client"] for x in self.pending.values()]:
            try:
                await client.disconnect()
            except Exception:
                pass
        self.clients.clear()
        self.pending.clear()
        self.connected.clear()

    def accounts(self):
        stored = {p.stem for p in self.root.glob("*.credentials") if _ALIAS.fullmatch(p.stem)}
        aliases = sorted(stored | set(self.pending) | set(self.clients))
        return [
            {"alias": a,
             "status": "connected" if a in self.connected and self.clients[a].is_connected()
                else "code_sent" if a in self.pending else "offline",
             "authorized": a in self.connected,
             "sending_enabled": False}
            for a in aliases
        ]

    async def start(self, alias, api_id, api_hash, phone):
        self._path(alias)
        if alias in self.clients and self.clients[alias].is_connected():
            raise TelegramError("Account is already connected")
        if alias in self.pending:
            try:
                await self.pending.pop(alias)["client"].disconnect()
            except Exception:
                pass
        client = self._client(alias, api_id, api_hash)
        try:
            await asyncio.wait_for(client.connect(), timeout=25)
            response = await asyncio.wait_for(client.send_code_request(phone), timeout=35)
            self.pending[alias] = {
                "client": client, "api_id": api_id, "api_hash": api_hash,
                "phone": phone, "hash": response.phone_code_hash,
            }
            return {"alias": alias, "status": "code_sent", "sending_enabled": False}
        except PhoneNumberInvalidError as exc:
            await client.disconnect()
            raise TelegramError("Invalid Telegram phone number") from exc
        except FloodWaitError as exc:
            await client.disconnect()
            raise TelegramError("Telegram rate limit; try again later") from exc
        except Exception:
            await client.disconnect()
            raise

    async def verify(self, alias, code="", password=""):
        self._path(alias)
        attempt = self.pending.get(alias)
        if not attempt:
            raise TelegramError("No pending login; request a verification code first")
        client = attempt["client"]
        try:
            if password:
                await client.sign_in(password=password)
            else:
                if not code:
                    raise TelegramError("Enter the Telegram verification code")
                await client.sign_in(
                    phone=attempt["phone"], code=code,
                    phone_code_hash=attempt["hash"])
        except SessionPasswordNeededError:
            return {"alias": alias, "status": "password_required", "sending_enabled": False}
        except (PhoneCodeInvalidError, PhoneCodeExpiredError) as exc:
            raise TelegramError("Invalid or expired verification code") from exc
        except PasswordHashInvalidError as exc:
            raise TelegramError("Incorrect Telegram two-step password") from exc
        except FloodWaitError as exc:
            raise TelegramError("Telegram rate limit; try again later") from exc
        if not await client.is_user_authorized():
            raise TelegramError("Telegram did not authorize this session")
        self._save_api(alias, attempt["api_id"], attempt["api_hash"])
        await self._observe(alias, client)
        self.pending.pop(alias, None)
        self.clients[alias] = client
        self.connected.add(alias)
        me = await client.get_me()
        return {
            "alias": alias, "status": "connected",
            "telegram_user_id": getattr(me, "id", None),
            "sending_enabled": False,
        }

    async def groups(self, alias):
        self._path(alias)
        client = self.clients.get(alias)
        if not client or not client.is_connected():
            # A restart might leave previously saved credentials offline.
            await self._connect_saved(alias)
            client = self.clients.get(alias)
        if not client or not client.is_connected():
            raise TelegramError("Telegram account is not connected")
        result = []
        async for dialog in client.iter_dialogs():
            if dialog.is_group:
                result.append({"id": str(dialog.id), "title": dialog.name or str(dialog.id)})
                if len(result) >= 500:
                    break
        return result
