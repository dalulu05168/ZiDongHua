"""小霸王 Telegram adapter. No credentials are ever transmitted to GitHub.
Run: python worker.py login tg01 | groups tg01 | listen tg01
Only monitored groups enabled by the local XiaoBaWang gateway can be forwarded.
"""
import argparse
import asyncio
import os
import re
from pathlib import Path

import httpx
from telethon import TelegramClient, events

API_URL = os.getenv("XBW_API_URL", "http://127.0.0.1:3100").rstrip("/")
SESSION_DIR = Path(os.getenv("XBW_TG_SESSION_DIR", "./tg_sessions")).resolve()

def make_client(alias):
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", alias):
        raise ValueError("Invalid account alias")
    api_id = os.getenv("TELEGRAM_API_ID", "")
    api_hash = os.getenv("TELEGRAM_API_HASH", "")
    if not api_id.isdecimal() or not api_hash:
        raise RuntimeError("TELEGRAM_API_ID and TELEGRAM_API_HASH must be set locally")
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    return TelegramClient(str(SESSION_DIR / alias), int(api_id), api_hash)

async def run(command, alias):
    client = make_client(alias)
    if command == "login":
        # Telethon asks for the phone, verification code, and optional 2FA locally.
        await client.start()
        me = await client.get_me()
        print("Authorized Telegram account ID:", me.id)
        await client.disconnect()
        return
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise RuntimeError("Not authorized; run login first")
        if command == "groups":
            async for dialog in client.iter_dialogs():
                if dialog.is_group:
                    print(f"{dialog.id}\t{dialog.name}")
            return
        secret = os.getenv("XBW_TG_KEY")
        if not secret:
            raise RuntimeError("Set XBW_TG_KEY locally")
        headers = {"X-TG-Key": secret}
        allowlist = set()
        async with httpx.AsyncClient(timeout=15) as http:
            async def refresh():
                resp = await http.get(f"{API_URL}/api/telegram/allowed/{alias}", headers=headers)
                resp.raise_for_status()
                allowlist.clear()
                allowlist.update(map(str, resp.json()["chat_ids"]))
            await refresh()
            @client.on(events.NewMessage(incoming=True))
            async def handle(event):
                if not event.is_group or str(event.chat_id) not in allowlist:
                    return
                if not event.raw_text or not event.raw_text.strip():
                    return  # media forwarding remains unimplemented
                payload = {"tg_account": alias, "tg_chat_id": str(event.chat_id),
                           "tg_message_id": str(event.id), "text": event.raw_text}
                try:
                    resp = await http.post(f"{API_URL}/api/telegram/events",
                                           json=payload, headers=headers)
                    resp.raise_for_status()
                    print("Queued event:", event.chat_id, event.id)
                except Exception as exc:
                    print("Forwarding error (no retry yet):", type(exc).__name__)
            async def refresh_loop():
                while True:
                    await asyncio.sleep(60)
                    try:
                        await refresh()
                    except Exception as exc:
                        print("Allowlist refresh failed:", type(exc).__name__)
            refresh_task = asyncio.create_task(refresh_loop())
            print("Listening with allowed chats:", sorted(allowlist))
            try:
                await client.run_until_disconnected()
            finally:
                refresh_task.cancel()
    finally:
        await client.disconnect()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["login", "groups", "listen"])
    parser.add_argument("account")
    parsed = parser.parse_args()
    asyncio.run(run(parsed.command, parsed.account))
