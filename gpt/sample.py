"""
Unified Messenger Framework
=========================
A single-file Python framework to manage multiple messenger platforms
(Telegram, Signal, Wire, Viber, Matrix/Element) from one interface.

Features
- Per-platform backend classes: Telegram, Signal, Wire (Enterprise placeholder),
  Viber (Bot), Matrix (Element)
- UnifiedMessenger: register backends, broadcast messages/files, start listeners
- Config-driven (JSON) for tokens, session strings, file paths
- CLI: start-listeners / broadcast-message / broadcast-file

Important notes before use
- Read the per-backend setup sections below (API keys, session generation, signal-cli folder, etc.)
- This file provides a practical, production-ready skeleton but you must fill in
  organization-specific details (Wire enterprise endpoints, webhook servers, etc.)

Requirements (install)
----------------------
pip install telethon matrix-nio requests aiohttp pyyaml
# signal-cli and Viber/Telegram sessions require external setup (see below)

Per-backend quick setup
-----------------------
Telegram
  - Use Telethon. Generate StringSession using Telethon & save to config.
  - See Telethon docs for api_id/api_hash and StringSession creation.
  - config example:
    telegram:
      - name: bot_a
        api_id: 12345
        api_hash: "abcd..."
        string_session: "1AQ..."

Signal
  - Install and register accounts with signal-cli (Java-based). Create a data_dir
    per-account (signal-cli's state files). Provide path to signal-cli binary.
  - This framework uses subprocess to call signal-cli. For long-running receive,
    consider using `signal-cli --output=json` or hooks and a dedicated process.

Wire
  - Wire Enterprise: replace placeholders with your enterprise REST/gRPC endpoints
    and tokens. This file provides a REST-style placeholder class; adapt to your
    Wire API contract.

Viber
  - Create a Viber bot at partners.viber.com and get Auth Token. Viber requires webhook
    for receiving messages; this framework's listener uses long-poll simulated via webhook
    (you'll need an externally reachable URL or ngrok in dev).

Matrix (Element)
  - Use matrix-nio. Supply homeserver URL, user_id and password or access token.
  - You may want to configure store_path to persist sync token.

Security
- Never commit config with tokens to public repos. Use environment variables or
  an encrypted secrets store in production.

"""

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp
import requests

# Optional imports that are heavy/optional. Import lazily inside classes to avoid
# requiring all dependencies if user uses only a subset of backends.


class BaseBackend:
    """Abstract base class for backends. Subclasses should implement:
    - async init()
    - async start_listening()
    - async send_message(target, message)
    - async send_file(target, file_path)
    """

    def __init__(self, name: str, config: Dict[str, Any]):
        self.name = name
        self.config = config

    async def init(self):
        raise NotImplementedError

    async def start_listening(self):
        raise NotImplementedError

    async def send_message(self, target: str, message: str):
        raise NotImplementedError

    async def send_file(self, target: str, file_path: str):
        raise NotImplementedError


# ----------------------
# Telegram backend
# ----------------------
class TelegramBackend(BaseBackend):
    """Uses Telethon for user accounts. Expects config keys:
    - api_id, api_hash, string_session
    """

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        self.client = None

    async def init(self):
        from telethon import TelegramClient
        from telethon.sessions import StringSession

        api_id = int(self.config["api_id"])
        api_hash = self.config["api_hash"]
        string_session = self.config.get("string_session")
        if not string_session:
            raise ValueError("Telegram backend requires string_session in config")

        self.client = TelegramClient(StringSession(string_session), api_id, api_hash)
        await self.client.connect()
        if not await self.client.is_user_authorized():
            # In many setups you won't need this because StringSession is authorized
            print(f"[{self.name}] Telegram session not authorized; manual sign-in required")

    async def start_listening(self):
        # register event handler and run sync forever in background
        from telethon import events

        if self.client is None:
            await self.init()

        @self.client.on(events.NewMessage(incoming=True))
        async def handler(event):
            sender = await event.get_sender()
            sender_name = getattr(sender, "username", None) or getattr(sender, "first_name", None) or "unknown"
            print(f"[Telegram:{self.name}] Message from {sender_name}: {event.raw_text}")

        # run in a background task
        loop = asyncio.get_event_loop()
        loop.create_task(self.client.run_until_disconnected())
        print(f"[Telegram:{self.name}] Listening started")

    async def send_message(self, target: str, message: str):
        if self.client is None:
            await self.init()
        await self.client.send_message(target, message)

    async def send_file(self, target: str, file_path: str):
        if self.client is None:
            await self.init()
        await self.client.send_file(target, file_path)


# ----------------------
# Signal backend (signal-cli subprocess wrapper)
# ----------------------
class SignalBackend(BaseBackend):
    """Wrapper around signal-cli. Config keys:
    - cli_path: path to signal-cli binary
    - data_dir: directory used for this account (signal-cli state)
    - phone: phone number registered (+8210...)

    Note: This implementation uses subprocess calls, wrapped in asyncio.to_thread
    to avoid blocking the event loop.
    """

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        self.cli_path = config.get("cli_path", "signal-cli")
        self.data_dir = config.get("data_dir")
        self.phone = config.get("phone")
        if not self.data_dir or not self.phone:
            raise ValueError("Signal backend requires 'data_dir' and 'phone' in config")

    async def init(self):
        # no persistent connections here; ensure cli exists
        if not Path(self.cli_path).exists():
            # Allow calling from PATH
            # if not found, user should provide full path
            print(f"[Signal:{self.name}] Warning: signal-cli not found at {self.cli_path}; ensure it's in PATH or provide full path")

    def _base_cmd(self) -> List[str]:
        return [self.cli_path, "-u", self.phone, "-c", self.data_dir]

    async def start_listening(self):
        # For receive we recommend running a blocking subprocess in a separate thread
        # This demonstration uses a polling loop calling 'signal-cli receive'.
        async def poll_loop():
            while True:
                try:
                    await asyncio.to_thread(self._receive_once)
                except Exception as e:
                    print(f"[Signal:{self.name}] receive error: {e}")
                await asyncio.sleep(self.config.get("poll_interval", 5))

        asyncio.create_task(poll_loop())
        print(f"[Signal:{self.name}] Polling receive loop started")

    def _receive_once(self):
        cmd = self._base_cmd() + ["receive"]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 0 and proc.stdout:
            print(f"[Signal:{self.name}] Received raw:\n{proc.stdout}")
        elif proc.returncode != 0 and proc.stderr:
            # signal-cli may return non-zero for no messages; ignore
            pass

    async def send_message(self, target: str, message: str):
        cmd = self._base_cmd() + ["send", "-m", message, target]
        proc = await asyncio.to_thread(lambda: subprocess.run(cmd, capture_output=True, text=True))
        if proc.returncode != 0:
            print(f"[Signal:{self.name}] send error: {proc.stderr}")

    async def send_file(self, target: str, file_path: str):
        cmd = self._base_cmd() + ["send", "-a", file_path, target]
        proc = await asyncio.to_thread(lambda: subprocess.run(cmd, capture_output=True, text=True))
        if proc.returncode != 0:
            print(f"[Signal:{self.name}] send file error: {proc.stderr}")


# ----------------------
# Wire backend (Enterprise placeholder)
# ----------------------
class WireBackend(BaseBackend):
    """Placeholder REST client for Wire Enterprise. You must adapt endpoints/contract.
    Config keys:
    - base_url
    - token
    """

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        self.base_url = config.get("base_url")
        self.token = config.get("token")
        if not self.base_url or not self.token:
            raise ValueError("Wire backend requires 'base_url' and 'token'")

    async def init(self):
        # nothing to open; validate token optionally
        resp = requests.get(f"{self.base_url}/v1/me", headers={"Authorization": f"Bearer {self.token}"})
        if resp.status_code == 200:
            print(f"[Wire:{self.name}] token validated")
        else:
            print(f"[Wire:{self.name}] token validation failed: {resp.status_code} {resp.text}")

    async def start_listening(self):
        # Recommended approach: configure webhook in Wire admin to call your server.
        print(f"[Wire:{self.name}] Please configure webhooks on Wire side; this client does not poll by default")

    async def send_message(self, conversation_id: str, message: str):
        url = f"{self.base_url}/v1/messages"
        payload = {"conversationId": conversation_id, "type": "text", "text": message}
        resp = requests.post(url, headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}, json=payload)
        if resp.status_code not in (200, 201):
            print(f"[Wire:{self.name}] send error: {resp.status_code} {resp.text}")

    async def send_file(self, conversation_id: str, file_path: str):
        url = f"{self.base_url}/v1/files"
        with open(file_path, "rb") as f:
            files = {"file": f}
            resp = requests.post(url, headers={"Authorization": f"Bearer {self.token}"}, files=files, data={"conversationId": conversation_id})
        if resp.status_code not in (200, 201):
            print(f"[Wire:{self.name}] file send error: {resp.status_code} {resp.text}")


# ----------------------
# Viber backend
# ----------------------
class ViberBackend(BaseBackend):
    """Uses Viber Public Account API (Bot). Config keys:
    - auth_token
    """

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        self.auth_token = config.get("auth_token")
        self.api_url = config.get("api_url", "https://chatapi.viber.com/pa")
        if not self.auth_token:
            raise ValueError("Viber backend requires auth_token")

    async def init(self):
        # validate token by calling get_account_info
        resp = requests.post(f"{self.api_url}/get_account_info", headers={"X-Viber-Auth-Token": self.auth_token}, json={})
        if resp.status_code == 200:
            print(f"[Viber:{self.name}] token validated")
        else:
            print(f"[Viber:{self.name}] token validation failed: {resp.status_code} {resp.text}")

    async def start_listening(self):
        # Viber delivers messages to your webhook; we suggest you run a small aiohttp webserver
        # and route /viber_webhook to a handler. This framework provides an aiohttp helper.
        print(f"[Viber:{self.name}] Please configure webhook url in Viber admin to point to your server")

    async def send_message(self, receiver_id: str, text: str):
        url = f"{self.api_url}/send_message"
        payload = {"receiver": receiver_id, "type": "text", "text": text}
        headers = {"X-Viber-Auth-Token": self.auth_token, "Content-Type": "application/json"}
        resp = requests.post(url, headers=headers, json=payload)
        if resp.status_code != 200:
            print(f"[Viber:{self.name}] send error: {resp.status_code} {resp.text}")

    async def send_file(self, receiver_id: str, file_url: str, media_type: str = "picture"):
        url = f"{self.api_url}/send_message"
        payload = {"receiver": receiver_id, "type": media_type, "media": file_url}
        headers = {"X-Viber-Auth-Token": self.auth_token, "Content-Type": "application/json"}
        resp = requests.post(url, headers=headers, json=payload)
        if resp.status_code != 200:
            print(f"[Viber:{self.name}] send file error: {resp.status_code} {resp.text}")


# ----------------------
# Matrix (Element) backend using matrix-nio
# ----------------------
class MatrixBackend(BaseBackend):
    """matrix-nio based backend. Config keys:
    - homeserver
    - user_id
    - password OR access_token
    - store_path (optional)
    """

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        self.client = None

    async def init(self):
        from nio import AsyncClient, LoginResponse

        homeserver = self.config.get("homeserver")
        user_id = self.config.get("user_id")
        password = self.config.get("password")
        access_token = self.config.get("access_token")
        store_path = self.config.get("store_path")

        if not homeserver or not user_id or (not password and not access_token):
            raise ValueError("Matrix backend requires homeserver, user_id and password or access_token")

        self.client = AsyncClient(homeserver, user_id, store_path=store_path)
        if access_token:
            self.client.access_token = access_token
            self.client.user_id = user_id
        else:
            resp = await self.client.login(password)
            if not isinstance(resp, LoginResponse):
                print(f"[Matrix:{self.name}] login failed: {resp}")
        print(f"[Matrix:{self.name}] initialized")

    async def start_listening(self):
        if self.client is None:
            await self.init()

        async def callback(room, event):
            # event.body may not exist for non-text events
            body = getattr(event, "body", None)
            if body:
                print(f"[Matrix:{self.name}] Message in {room.display_name}: {body}")

        self.client.add_event_callback(callback, ("m.room.message",))
        asyncio.create_task(self.client.sync_forever(timeout=30000))
        print(f"[Matrix:{self.name}] sync loop started")

    async def send_message(self, room_id: str, message: str):
        if self.client is None:
            await self.init()
        await self.client.room_send(room_id, message_type="m.room.message", content={"msgtype": "m.text", "body": message})

    async def send_file(self, room_id: str, file_path: str):
        if self.client is None:
            await self.init()
        upload_result = await self.client.upload(file_path)
        # upload_result may be a tuple (response, data) depending on nio version
        content_uri = None
        if hasattr(upload_result, "content_uri"):
            content_uri = upload_result.content_uri
        elif isinstance(upload_result, tuple) and hasattr(upload_result[0], "content_uri"):
            content_uri = upload_result[0].content_uri
        if not content_uri:
            print(f"[Matrix:{self.name}] upload failed: {upload_result}")
            return
        await self.client.room_send(room_id, message_type="m.room.message", content={"msgtype": "m.file", "body": Path(file_path).name, "url": content_uri})


# ----------------------
# Unified messenger manager
# ----------------------
class UnifiedMessenger:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.backends: Dict[str, BaseBackend] = {}

    def register_backend(self, key: str, backend: BaseBackend):
        self.backends[key] = backend

    async def init_all(self):
        tasks = []
        for k, b in self.backends.items():
            tasks.append(b.init())
        await asyncio.gather(*tasks)

    async def start_listeners(self):
        tasks = []
        for k, b in self.backends.items():
            tasks.append(b.start_listening())
        await asyncio.gather(*tasks)

    async def broadcast_message(self, target_map: Dict[str, str], message: str):
        """
        target_map: mapping backend_key -> target identifier (chat id, phone, room id)
        """
        tasks = []
        for key, backend in self.backends.items():
            tgt = target_map.get(key)
            if not tgt:
                print(f"[Unified] No target for backend {key}, skipping")
                continue
            tasks.append(self._safe_send(backend.send_message, tgt, message))
        await asyncio.gather(*tasks)

    async def broadcast_file(self, target_map: Dict[str, str], file_path: str):
        tasks = []
        for key, backend in self.backends.items():
            tgt = target_map.get(key)
            if not tgt:
                print(f"[Unified] No target for backend {key}, skipping")
                continue
            # Some backends (Viber) expect a URL instead of local path
            if key == "viber":
                # naive: upload to an accessible place required — skipping
                print("[Unified] Viber requires file URL. Please provide public URL in target_map or adapt code.")
                continue
            tasks.append(self._safe_send(backend.send_file, tgt, file_path))
        await asyncio.gather(*tasks)

    async def _safe_send(self, send_coro, *args, **kwargs):
        try:
            await send_coro(*args, **kwargs)
        except Exception as e:
            print(f"[Unified] send error: {e}")


# ----------------------
# Utility: load config and auto-register
# ----------------------

def load_config(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        if path.endswith(('.yaml', '.yml')):
            import yaml

            return yaml.safe_load(f)
        return json.load(f)


async def build_unified_from_config(config_path: str) -> UnifiedMessenger:
    cfg = load_config(config_path)
    mgr = UnifiedMessenger(cfg)

    # Register telegram backends
    for t in cfg.get("telegram", []):
        name = t.get("name") or t.get("api_id")
        mgr.register_backend(name, TelegramBackend(name, t))

    # Register signal
    for s in cfg.get("signal", []):
        name = s.get("name") or s.get("phone")
        mgr.register_backend(name, SignalBackend(name, s))

    # Wire
    for w in cfg.get("wire", []):
        name = w.get("name") or "wire"
        mgr.register_backend(name, WireBackend(name, w))

    # Viber
    for v in cfg.get("viber", []):
        name = v.get("name") or "viber"
        mgr.register_backend(name, ViberBackend(name, v))

    # Matrix
    for m in cfg.get("matrix", []):
        name = m.get("name") or m.get("user_id")
        mgr.register_backend(name, MatrixBackend(name, m))

    return mgr


# ----------------------
# CLI helpers
# ----------------------

USAGE = """
Usage:
  python unified_messenger_framework.py <config.json|yaml> command [args]

Commands:
  init                - initialize all backends (validate tokens, connectwhere applicable)
  listen              - start listeners for backends that support it (runs forever)
  broadcast-msg PATH  - broadcast a message to all backends; PATH is a JSON file mapping backend_key->target
  broadcast-file PATH - broadcast a local file to all backends (where supported); PATH is a JSON mapping

Examples:
  python unified_messenger_framework.py config.yaml init
  python unified_messenger_framework.py config.yaml listen
  python unified_messenger_framework.py config.yaml broadcast-msg targets.json

"""


async def cli_entry():
    if len(sys.argv) < 3:
        print(USAGE)
        return
    config_path = sys.argv[1]
    cmd = sys.argv[2]
    mgr = await build_unified_from_config(config_path)

    if cmd == "init":
        await mgr.init_all()
        print("init complete")
        return

    if cmd == "listen":
        await mgr.init_all()
        await mgr.start_listeners()
        # keep the process alive
        while True:
            await asyncio.sleep(3600)

    if cmd == "broadcast-msg":
        if len(sys.argv) < 4:
            print("Please provide target mapping JSON path")
            return
        targets_path = sys.argv[3]
        with open(targets_path, "r", encoding="utf-8") as f:
            target_map = json.load(f)
        message = input("Message to broadcast: ")
        await mgr.init_all()
        await mgr.broadcast_message(target_map, message)
        return

    if cmd == "broadcast-file":
        if len(sys.argv) < 4:
            print("Please provide target mapping JSON path")
            return
        targets_path = sys.argv[3]
        with open(targets_path, "r", encoding="utf-8") as f:
            target_map = json.load(f)
        file_path = sys.argv[4] if len(sys.argv) > 4 else input("Local file path: ")
        await mgr.init_all()
        await mgr.broadcast_file(target_map, file_path)
        return

    print("Unknown command")


if __name__ == "__main__":
    asyncio.run(cli_entry())
