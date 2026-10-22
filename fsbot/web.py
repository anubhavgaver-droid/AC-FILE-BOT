"""Tiny dependency-free HTTP server for Render (health check + keep-alive pings)."""
from __future__ import annotations

import asyncio
import json
import logging
import time

import httpx

log = logging.getLogger(__name__)
_started = time.time()
_info: dict[str, object] = {}
_server = None


def set_info(**kwargs: object) -> None:
    _info.update(kwargs)


async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    method = "GET"
    try:
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5)
        method = head.split(b" ", 1)[0].decode("ascii", "ignore").upper() or "GET"
    except Exception:  # noqa: BLE001
        pass
    body = json.dumps({"status": "ok", "uptime_seconds": int(time.time() - _started), **_info}).encode()
    headers = (
        "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
    ).encode()
    try:
        writer.write(headers + (b"" if method == "HEAD" else body))
        await writer.drain()
    except ConnectionError:
        pass
    finally:
        writer.close()


async def start_server(port: int, host: str = "0.0.0.0") -> int:
    global _server
    _server = await asyncio.start_server(_handle, host, port)
    bound = _server.sockets[0].getsockname()[1]
    log.info("Health server listening on port %s", bound)
    return bound


async def stop_server() -> None:
    if _server:
        _server.close()
        await _server.wait_closed()


async def keepalive_loop(url: str, interval: int = 600) -> None:
    """Ping our own public URL so Render's free tier does not spin the service down."""
    async with httpx.AsyncClient(timeout=20) as client:
        while True:
            await asyncio.sleep(interval)
            try:
                await client.get(f"{url}/health")
            except Exception:  # noqa: BLE001
                log.warning("Keep-alive ping failed")
