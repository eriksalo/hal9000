#!/usr/bin/env python3
"""HAL 9000 developer mode: one conversation over local audio, no camera.

    python hal_local.py --person Erik

Useful for testing voice, turn-taking and memory on a laptop or on the Pi
without the face-recognition loop.
"""

from __future__ import annotations

import argparse
import asyncio

from loguru import logger

from hal.app import AppContext, configure_logging
from hal.config import load_config
from hal.status_server import start_status_server
from hal_autonomous import local_audio_transport


async def main() -> None:
    parser = argparse.ArgumentParser(description="Talk to HAL over local audio")
    parser.add_argument("--person", help="Who HAL is talking to (default: PERSON_NAME from .env)")
    parser.add_argument("--no-status-server", action="store_true", help="Do not start the HTTP status API")
    parser.add_argument("--vision", action="store_true", help="Enable camera + analyze_camera tool")
    args = parser.parse_args()

    config = load_config()
    configure_logging(config.log_level)
    person = args.person or config.default_person

    ctx = AppContext(config, transport_factory=lambda: local_audio_transport(config), enable_vision=args.vision)
    await ctx.start()
    server = None if args.no_status_server else await start_status_server(ctx, config.server.host, config.server.status_port)
    try:
        await ctx.start_conversation(person)
        logger.info(f"Talking to {person}. Say goodbye or press Ctrl+C to end.")
        await ctx.wait_for_session()
    except KeyboardInterrupt:
        await ctx.end_conversation("keyboard_interrupt")
        await ctx.wait_for_session()
    finally:
        await ctx.stop()
        if server:
            await server.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
