#!/usr/bin/env python3
"""HAL 9000 over WebRTC from a browser (Pipecat dev runner, no Daily.co).

    python hal_webrtc.py -t webrtc --host 0.0.0.0 --port 7860

Then open http://<pi>:7860/client in a browser. Each connection is one
conversation with PERSON_NAME (or ?person=Name on the /client URL is not
supported by the prebuilt UI; set PERSON_NAME in .env).
"""

from __future__ import annotations

from loguru import logger
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.transports.base_transport import TransportParams

from hal.app import AppContext, configure_logging
from hal.config import load_config

_config = load_config()
configure_logging(_config.log_level)
_ctx = AppContext(_config, enable_vision=False)


async def bot(runner_args: RunnerArguments) -> None:
    transport = await create_transport(
        runner_args,
        {
            "webrtc": lambda: TransportParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
                audio_in_sample_rate=_config.audio.sample_rate,
                audio_out_sample_rate=_config.audio.output_sample_rate,
            ),
        },
    )
    if _ctx.http is None:
        await _ctx.start()
    person = (runner_args.body or {}).get("person") if isinstance(runner_args.body, dict) else None
    person = person or _config.default_person
    logger.info(f"WebRTC client connected; starting conversation with {person}")
    if await _ctx.start_conversation(person, transport=transport):
        await _ctx.wait_for_session()
    else:
        logger.warning("A conversation is already running; rejecting new WebRTC client")


if __name__ == "__main__":
    from pipecat.runner.run import main

    main()
