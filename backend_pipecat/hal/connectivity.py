"""Is the outside world reachable? Decides between cloud and Hailo-only operation."""

from __future__ import annotations

import asyncio
import socket

from loguru import logger

PROBE_HOSTS = (("api.anthropic.com", 443), ("api.deepgram.com", 443), ("1.1.1.1", 443))


async def is_online(timeout: float = 2.0) -> bool:
    """True if any probe host accepts a TCP connection within ``timeout`` seconds."""

    def probe(host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False

    results = await asyncio.gather(*(asyncio.to_thread(probe, h, p) for h, p in PROBE_HOSTS))
    online = any(results)
    if not online:
        logger.warning("No internet connectivity detected")
    return online
