"""Small HTTP API for the ESP32 eye display, the debug page, and manual control.

Endpoints (compatible with the firmware in ``esp32_display/``):
    GET  /                              -> HAL control dashboard (HTML)
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


DASHBOARD_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HAL 9000</title>
<style>
  :root { --red:#e01010; --amber:#f5a623; --green:#39d353; --orange:#ff7a00; --bg:#0a0a0a; --panel:#141414; --dim:#6a6a6a; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:#d8d8d8; font-family:"Courier New",monospace; }
  header { text-align:center; padding:14px; border-bottom:1px solid #222; letter-spacing:6px; color:#aaa; font-size:14px; }
  .wrap { max-width:960px; margin:0 auto; padding:16px; display:grid; gap:16px; grid-template-columns:1fr 1fr; }
  @media (max-width:720px){ .wrap{ grid-template-columns:1fr; } }
  .panel { background:var(--panel); border:1px solid #222; border-radius:10px; padding:16px; }
  .eye-wrap { grid-column:1 / -1; display:flex; align-items:center; gap:24px; justify-content:center; flex-wrap:wrap; }
  .eye { position:relative; width:180px; height:180px; border-radius:50%;
         background:radial-gradient(circle at 50% 45%, #150202 0%, #0a0000 68%, #000 100%);
         box-shadow:0 0 0 1px #050505, 0 0 46px 7px var(--accent,var(--red)),
                    0 0 100px 16px color-mix(in srgb, var(--accent,var(--red)) 36%, transparent),
                    inset 0 0 24px 7px #000;
         display:flex; align-items:center; justify-content:center;
         transition:box-shadow .55s ease; animation:breathe 5s ease-in-out infinite; }
  .eye::after { content:""; position:absolute; inset:8px; border-radius:50%;
         background:radial-gradient(circle at 50% 38%, #1b1b1b 0%, #0b0b0b 55%, #000 100%);
         box-shadow:inset 0 0 20px 7px #000, inset 0 3px 4px rgba(255,255,255,.05); }
  .lens { position:relative; z-index:1; width:56%; height:56%; border-radius:50%;
         background:radial-gradient(circle at 50% 40%, #ff7a5c 0%, #ff2410 22%, #cc0a00 46%, #6e0000 72%, #260000 100%);
         box-shadow:0 0 28px 8px rgba(255,40,16,.8), inset 0 0 22px 6px rgba(0,0,0,.65), inset 0 0 7px 1px rgba(255,150,120,.45);
         animation:flicker 6s ease-in-out infinite; }
  .core { position:absolute; top:40%; left:50%; width:30%; height:30%; transform:translate(-50%,-50%); border-radius:50%;
         background:radial-gradient(circle, #fffef6 0%, #ffe6a0 32%, #ffab18 56%, rgba(255,130,0,0) 78%);
         box-shadow:0 0 18px 6px rgba(255,200,96,.85); animation:corepulse 4s ease-in-out infinite; }
  .glint { position:absolute; top:29%; left:37%; width:13%; height:13%; border-radius:50%;
         background:radial-gradient(circle, rgba(255,255,255,.92) 0%, rgba(255,255,255,0) 70%); filter:blur(1px); }
  @keyframes breathe { 0%,100%{ transform:scale(.99);} 50%{ transform:scale(1.025);} }
  @keyframes flicker { 0%,100%{ filter:brightness(1);} 48%{ filter:brightness(1.09);} 52%{ filter:brightness(.95);} }
  @keyframes corepulse { 0%,100%{ opacity:.82; transform:translate(-50%,-50%) scale(.95);} 50%{ opacity:1; transform:translate(-50%,-50%) scale(1.07);} }
  .mode { font-size:26px; letter-spacing:3px; text-transform:uppercase; color:var(--accent,var(--red)); }
  .sub { color:var(--dim); font-size:13px; margin-top:4px; }
  h2 { margin:0 0 10px; font-size:12px; letter-spacing:2px; color:#888; text-transform:uppercase; }
  .row { display:flex; justify-content:space-between; padding:4px 0; border-bottom:1px solid #1d1d1d; font-size:14px; }
  .row span:last-child { color:#fff; }
  .say { min-height:40px; padding:8px 10px; background:#101010; border-left:3px solid #333; border-radius:4px; margin-top:6px; font-size:14px; }
  .say.you { border-color:var(--green); } .say.hal { border-color:var(--orange); }
  img#cam { width:100%; border-radius:8px; background:#000; aspect-ratio:1/1; object-fit:cover; filter:saturate(1.1); }
  input,button { font-family:inherit; font-size:14px; }
  input { background:#0c0c0c; border:1px solid #333; color:#eee; padding:8px; border-radius:6px; }
  button { background:#1c1c1c; border:1px solid #444; color:#eee; padding:8px 14px; border-radius:6px; cursor:pointer; }
  button:hover { background:#2a2a2a; border-color:var(--red); }
  .ctl { display:flex; gap:8px; margin-top:8px; flex-wrap:wrap; }
  .ctl input { flex:1; min-width:120px; }
  .pill { font-size:11px; padding:2px 8px; border-radius:10px; border:1px solid #333; color:#999; }
  .online { color:var(--green); border-color:#1e4; } .offline { color:var(--red); border-color:#611; }
  .tag { color:var(--dim); font-size:12px; }
</style>
</head>
<body>
<header>H A L &nbsp; 9 0 0 0 &nbsp;&mdash;&nbsp; CONTROL</header>
<div class="wrap">
  <div class="panel eye-wrap">
    <div class="eye" id="eye"><div class="lens"><div class="core"></div><div class="glint"></div></div></div>
    <div>
      <div class="mode" id="mode">&mdash;</div>
      <div class="sub" id="sub">connecting&hellip;</div>
      <div style="margin-top:8px"><span class="pill" id="net">&mdash;</span> <span class="pill" id="esp">eye &mdash;</span> <span class="pill" id="wake">wake &mdash;</span></div>
    </div>
  </div>

  <div class="panel">
    <h2>Status</h2>
    <div class="row"><span>Speaking with</span><span id="person">&mdash;</span></div>
    <div class="row"><span>In conversation</span><span id="inconv">&mdash;</span></div>
    <div class="row"><span>People in view</span><span id="present">&mdash;</span></div>
    <div class="row"><span>Known faces</span><span id="faces">&mdash;</span></div>
    <div class="row"><span>Conversations</span><span id="count">&mdash;</span></div>
    <div class="row"><span>Brain / Ears / Voice</span><span id="svc" class="tag">&mdash;</span></div>
    <h2 style="margin-top:16px">Transcript</h2>
    <div class="say you"><span class="tag">YOU&nbsp;</span><span id="you">&mdash;</span></div>
    <div class="say hal"><span class="tag">HAL&nbsp;</span><span id="hal">&mdash;</span></div>
  </div>

  <div class="panel">
    <h2>Camera</h2>
    <img id="cam" alt="camera" src="/api/vision/frame">
    <h2 style="margin-top:16px">Controls</h2>
    <div class="ctl">
      <input id="startName" placeholder="name (e.g. Erik)">
      <button onclick="startConv()">Start</button>
      <button onclick="endConv()">End</button>
    </div>
    <div class="ctl">
      <input id="sayText" placeholder="make HAL say&hellip;" onkeydown="if(event.key==='Enter')speak()">
      <button onclick="speak()">Speak</button>
    </div>
    <div class="ctl">
      <input id="regName" placeholder="name the last unknown face">
      <button onclick="register()">Register face</button>
    </div>
    <div class="sub" id="msg" style="margin-top:8px"></div>
  </div>
</div>

<script>
const EYE = { idle:getcss('--red'), listening:getcss('--green'), thinking:getcss('--amber'), speaking:getcss('--orange'), offline:'#500' };
function getcss(v){ return getComputedStyle(document.documentElement).getPropertyValue(v).trim(); }
function $(id){ return document.getElementById(id); }
function flash(t){ $('msg').textContent = t; setTimeout(()=>{ if($('msg').textContent===t) $('msg').textContent=''; }, 4000); }

async function poll(){
  try {
    const r = await fetch('/api/hal/status',{cache:'no-store'}); const d = await r.json();
    const mode = d.mode || 'idle';
    document.documentElement.style.setProperty('--accent', EYE[mode] || EYE.idle);
    $('mode').textContent = mode;
    $('sub').textContent = d.in_conversation ? ('talking with '+(d.person||'someone')) : 'idle — watching';
    $('person').textContent = d.person || '—';
    $('inconv').textContent = d.in_conversation ? 'yes' : 'no';
    $('present').textContent = (d.people_present&&d.people_present.length)? d.people_present.join(', ') : 'nobody';
    $('faces').textContent = (d.known_faces&&d.known_faces.length)? d.known_faces.join(', ') : 'none enrolled';
    $('count').textContent = d.conversation_count ?? 0;
    const s = d.services||{}; $('svc').textContent = (s.llm||'?')+' / '+(s.stt||'?')+' / '+(s.tts||'?');
    $('you').textContent = d.last_user_text || '—';
    $('hal').textContent = d.last_hal_text || '—';
    $('net').textContent = d.online ? 'online' : 'offline'; $('net').className = 'pill '+(d.online?'online':'offline');
    const e = d.esp32||{}; $('esp').textContent = 'eye '+(e.connected?'connected':'offline'); $('esp').className='pill '+(e.connected?'online':'offline');
    $('wake').textContent = d.wake_armed ? 'wake armed' : (d.in_conversation ? 'wake paused' : 'wake off'); $('wake').className='pill '+(d.wake_armed?'online':'offline');
  } catch(err){ $('sub').textContent = 'backend unreachable'; }
}
function refreshCam(){ $('cam').src = '/api/vision/frame?t=' + Date.now(); }
async function post(url, body){
  try { const r = await fetch(url,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body||{})});
    const d = await r.json().catch(()=>({})); flash(JSON.stringify(d)); poll(); }
  catch(e){ flash('request failed'); }
}
function startConv(){ post('/api/hal/start', {name: $('startName').value || undefined}); }
function endConv(){ post('/api/hal/end'); }
function speak(){ const t=$('sayText').value.trim(); if(t){ post('/api/hal/speak',{text:t}); $('sayText').value=''; } }
function register(){ const n=$('regName').value.trim(); if(n){ post('/api/hal/register',{name:n}); $('regName').value=''; } }

poll(); setInterval(poll, 1000); setInterval(refreshCam, 1500);
</script>
</body>
</html>
"""


def create_status_app(ctx: "AppContext") -> web.Application:
    app = web.Application()
    app["ctx"] = ctx
    app.add_routes(
        [
            web.get("/", _dashboard),
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


async def _dashboard(request: web.Request) -> web.Response:
    return web.Response(text=DASHBOARD_HTML, content_type="text/html")


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
