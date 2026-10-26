"""Small HTTP API for the ESP32 eye display, the debug page, and manual control.

Endpoints (compatible with the firmware in ``esp32_display/``):
    GET  /health
    GET  /api/hal/display               -> {"mode": "eye"|"face", "state": ..., "person": ...}
    GET  /api/hal/face_frame?red=true&size=480  -> JPEG
    GET  /api/vision/frame              -> JPEG (full size)
    GET  /api/hal/status                -> runtime state + presence debug info
    POST /api/hal/speak  {"text": ...}  -> HAL says the text (if a session is active)
    POST /api/hal/register {"name": ...}-> register the last unknown face under a name
    POST /api/hal/start  {"name": ...}  -> start a conversation manually
    POST /api/hal/end                   -> end the active conversation
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiohttp import web
from loguru import logger

from hal.vision.camera import red_filter

if TYPE_CHECKING:
    from hal.app import AppContext


def create_status_app(ctx: "AppContext") -> web.Application:
    app = web.Application()
    app["ctx"] = ctx
    app.add_routes(
        [
            web.get("/health", _health),
            web.get("/api/hal/display", _display),
            web.get("/api/hal/face_frame", _face_frame),
            web.get("/api/vision/frame", _vision_frame),
            web.get("/api/hal/status", _status),
            web.post("/api/hal/speak", _speak),
            web.post("/api/hal/register", _register),
            web.post("/api/hal/start", _start),
            web.post("/api/hal/end", _end),
        ]
    )
    return app


async def start_status_server(ctx: "AppContext", host: str, port: int) -> web.AppRunner:
    runner = web.AppRunner(create_status_app(ctx), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, host, port).start()
    logger.info(f"Status server listening on http://{host}:{port}")
    return runner


async def _health(request: web.Request) -> web.Response:
    return web.json_response({"status": "operational", "message": "All systems functional"})


async def _display(request: web.Request) -> web.Response:
    ctx: AppContext = request.app["ctx"]
    ctx.note_esp32(request.remote)
    return web.json_response(ctx.state.display_payload())


async def _face_frame(request: web.Request) -> web.Response:
    ctx: AppContext = request.app["ctx"]
    if ctx.camera is None:
        return web.json_response({"error": "camera disabled"}, status=503)
    size = min(max(int(request.query.get("size", "480")), 64), 480)
    jpeg = ctx.camera.jpeg(size=size)
    if jpeg is None:
        return web.json_response({"error": "no frame"}, status=503)
    if request.query.get("red", "false").lower() == "true":
        jpeg = red_filter(jpeg)
    return web.Response(body=jpeg, content_type="image/jpeg")


async def _vision_frame(request: web.Request) -> web.Response:
    ctx: AppContext = request.app["ctx"]
    jpeg = ctx.camera.jpeg() if ctx.camera else None
    if jpeg is None:
        return web.json_response({"error": "no frame"}, status=503)
    return web.Response(body=jpeg, content_type="image/jpeg")


async def _status(request: web.Request) -> web.Response:
    ctx: AppContext = request.app["ctx"]
    payload = ctx.state.status_payload()
    payload["tracker"] = ctx.presence.tracker.debug_info() if ctx.presence else {}
    payload["known_faces"] = ctx.recognizer.known_names() if ctx.recognizer else []
    payload["esp32"] = ctx.esp32_info()
    payload["services"] = ctx.service_profile_info()
    return web.json_response(payload)


async def _speak(request: web.Request) -> web.Response:
    ctx: AppContext = request.app["ctx"]
    text = str((await request.json()).get("text", "")).strip()
    if not text:
        return web.json_response({"error": "text required"}, status=400)
    if not await ctx.say(text):
        return web.json_response({"error": "no active conversation"}, status=409)
    return web.json_response({"status": "queued"})


async def _register(request: web.Request) -> web.Response:
    ctx: AppContext = request.app["ctx"]
    name = str((await request.json()).get("name", "")).strip()
    if not name:
        return web.json_response({"error": "name required"}, status=400)
    if not ctx.register_last_unknown_face(name):
        return web.json_response({"error": "no unknown face seen recently"}, status=409)
    return web.json_response({"status": "registered", "name": name})


async def _start(request: web.Request) -> web.Response:
    ctx: AppContext = request.app["ctx"]
    body = await request.json() if request.can_read_body else {}
    name = str(body.get("name", "")).strip() or ctx.config.default_person
    started = await ctx.start_conversation(name)
    return web.json_response({"status": "started" if started else "busy", "name": name})


async def _end(request: web.Request) -> web.Response:
    ctx: AppContext = request.app["ctx"]
    await ctx.end_conversation("manual")
    return web.json_response({"status": "ending"})
