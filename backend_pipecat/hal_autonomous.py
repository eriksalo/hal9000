#!/usr/bin/env python3
"""HAL 9000 autonomous mode: watch the camera, greet people, converse, remember.

Runs on the Pi with local audio devices. Also serves the status API the ESP32
eye display polls.
"""

from __future__ import annotations

import asyncio
import signal

from loguru import logger
from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams

from hal.app import AppContext, configure_logging
from hal.config import HALConfig, load_config
from hal.status_server import start_status_server


def local_audio_transport(config: HALConfig) -> LocalAudioTransport:
    return LocalAudioTransport(
        LocalAudioTransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_sample_rate=config.audio.sample_rate,
            audio_out_sample_rate=config.audio.output_sample_rate,
            input_device_index=config.audio.input_device_index,
            output_device_index=config.audio.output_device_index,
        )
    )


async def main() -> None:
    config = load_config()
    configure_logging(config.log_level)
    ctx = AppContext(config, transport_factory=lambda: local_audio_transport(config))
    await ctx.start()
    server = await start_status_server(ctx, config.server.host, config.server.status_port)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows
            signal.signal(sig, lambda *_: stop.set())

    logger.info("HAL 9000 is watching. Press Ctrl+C to stop.")
    try:
        await stop.wait()
    finally:
        await ctx.stop()
        await server.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
