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
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAzMiAzMiIgd2lkdGg9IjMyIiBoZWlnaHQ9IjMyIj4KICA8dGl0bGU+SEFMIDkwMDA8L3RpdGxlPgogIDxkZWZzPgogICAgPCEtLSBEYXJrIG1ldGFsbGljIGJlemVsIC0tPgogICAgPHJhZGlhbEdyYWRpZW50IGlkPSJiZXplbCIgY3g9IjUwJSIgY3k9IjQyJSIgcj0iNjAlIj4KICAgICAgPHN0b3Agb2Zmc2V0PSIwJSIgc3RvcC1jb2xvcj0iIzIwMjAyMCIvPgogICAgICA8c3RvcCBvZmZzZXQ9IjcwJSIgc3RvcC1jb2xvcj0iIzBkMGQwZCIvPgogICAgICA8c3RvcCBvZmZzZXQ9IjEwMCUiIHN0b3AtY29sb3I9IiMwMDAwMDAiLz4KICAgIDwvcmFkaWFsR3JhZGllbnQ+CiAgICA8IS0tIEV5ZSBib2R5OiByZWQgLT4gZGFyayByZWQgLT4gYmxhY2sgKG1hdGNoZXMgLmhhbC1leWUpIC0tPgogICAgPHJhZGlhbEdyYWRpZW50IGlkPSJleWUiIGN4PSI1MCUiIGN5PSI1MCUiIHI9IjUwJSI+CiAgICAgIDxzdG9wIG9mZnNldD0iMCUiIHN0b3AtY29sb3I9IiNmZjAwMDAiLz4KICAgICAgPHN0b3Agb2Zmc2V0PSI1MCUiIHN0b3AtY29sb3I9IiM4YjAwMDAiLz4KICAgICAgPHN0b3Agb2Zmc2V0PSIxMDAlIiBzdG9wLWNvbG9yPSIjMDAwMDAwIi8+CiAgICA8L3JhZGlhbEdyYWRpZW50PgogICAgPCEtLSBHbG93aW5nIGxlbnM6IHllbGxvdyAtPiByZWQgKG1hdGNoZXMgLmV5ZS1pbm5lcikgLS0+CiAgICA8cmFkaWFsR3JhZGllbnQgaWQ9ImxlbnMiIGN4PSI1MCUiIGN5PSI1MCUiIHI9IjUwJSI+CiAgICAgIDxzdG9wIG9mZnNldD0iMCUiIHN0b3AtY29sb3I9IiNmZmZmMDAiLz4KICAgICAgPHN0b3Agb2Zmc2V0PSIxMDAlIiBzdG9wLWNvbG9yPSIjZmYwMDAwIi8+CiAgICA8L3JhZGlhbEdyYWRpZW50PgogICAgPHJhZGlhbEdyYWRpZW50IGlkPSJnbG93IiBjeD0iNTAlIiBjeT0iNTAlIiByPSI1MCUiPgogICAgICA8c3RvcCBvZmZzZXQ9IjAlIiBzdG9wLWNvbG9yPSIjZmYwMDAwIiBzdG9wLW9wYWNpdHk9IjAuNTUiLz4KICAgICAgPHN0b3Agb2Zmc2V0PSIxMDAlIiBzdG9wLWNvbG9yPSIjZmYwMDAwIiBzdG9wLW9wYWNpdHk9IjAiLz4KICAgIDwvcmFkaWFsR3JhZGllbnQ+CiAgPC9kZWZzPgoKICA8IS0tIEJlemVsIHBsYXRlIC0tPgogIDxjaXJjbGUgY3g9IjE2IiBjeT0iMTYiIHI9IjE2IiBmaWxsPSJ1cmwoI2JlemVsKSIvPgogIDxjaXJjbGUgY3g9IjE2IiBjeT0iMTYiIHI9IjE1LjMiIGZpbGw9Im5vbmUiIHN0cm9rZT0iIzJhMDAwMCIgc3Ryb2tlLXdpZHRoPSIwLjciLz4KCiAgPCEtLSBPdXRlciByZWQgZ2xvdyAtLT4KICA8Y2lyY2xlIGN4PSIxNiIgY3k9IjE2IiByPSIxMyIgZmlsbD0idXJsKCNnbG93KSIvPgoKICA8IS0tIEV5ZSBib2R5IC0tPgogIDxjaXJjbGUgY3g9IjE2IiBjeT0iMTYiIHI9IjEwLjUiIGZpbGw9InVybCgjZXllKSIvPgoKICA8IS0tIEdsb3dpbmcgY2VudHJhbCBsZW5zIC0tPgogIDxjaXJjbGUgY3g9IjE2IiBjeT0iMTYiIHI9IjMuNiIgZmlsbD0idXJsKCNsZW5zKSIvPgoKICA8IS0tIFRpbnkgc3BlY3VsYXIgaGlnaGxpZ2h0IC0tPgogIDxjaXJjbGUgY3g9IjE0LjciIGN5PSIxNC43IiByPSIwLjkiIGZpbGw9IiNmZmZmZmYiIGZpbGwtb3BhY2l0eT0iMC44NSIvPgo8L3N2Zz4K">
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
  .people-panel { grid-column:1 / -1; }
  .people-head { display:flex; align-items:center; justify-content:space-between; }
  .people { margin-top:8px; display:flex; flex-direction:column; gap:6px; }
  .person { display:flex; align-items:center; gap:10px; padding:8px 10px; background:#101010;
            border:1px solid #1d1d1d; border-radius:6px; }
  .person .pname { font-size:15px; color:#fff; min-width:120px; }
  .person .meta { color:var(--dim); font-size:12px; flex:1; }
  .person .here { color:var(--green); }
  .badge { font-size:10px; padding:1px 6px; border-radius:8px; border:1px solid #333; color:#999; }
  .badge.face { border-color:#355; color:#8cc; } .badge.mem { border-color:#453; color:#cb8; }
  .btn-ren { background:#161616; border:1px solid #444; color:#ccc; padding:5px 12px; border-radius:6px; cursor:pointer; }
  .btn-ren:hover { background:#262626; border-color:var(--amber); color:#fff; }
  .btn-del { background:#1c1010; border:1px solid #633; color:#e88; padding:5px 12px; border-radius:6px; cursor:pointer; }
  .btn-del:hover { background:#3a1414; border-color:var(--red); color:#fff; }
  .empty { color:var(--dim); font-size:13px; padding:6px 2px; }
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

  <div class="panel people-panel">
    <div class="people-head">
      <h2 style="margin:0">People HAL knows</h2>
      <button onclick="loadPeople()">Refresh</button>
    </div>
    <div class="people" id="people"><div class="empty">loading&hellip;</div></div>
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
    const d = await r.json().catch(()=>({})); flash(JSON.stringify(d)); poll(); loadPeople(); return d; }
  catch(e){ flash('request failed'); return {}; }
}
function startConv(){ post('/api/hal/start', {name: $('startName').value || undefined}); }
function endConv(){ post('/api/hal/end'); }
function speak(){ const t=$('sayText').value.trim(); if(t){ post('/api/hal/speak',{text:t}); $('sayText').value=''; } }
function register(){ const n=$('regName').value.trim(); if(n){ post('/api/hal/register',{name:n}); $('regName').value=''; } }

function badge(cls, text, color){
  const b=document.createElement('span'); b.className='badge '+(cls||''); b.textContent=text;
  if(color){ b.style.borderColor=color; b.style.color=color; } return b;
}
async function loadPeople(){
  const box=$('people');
  try {
    const r=await fetch('/api/hal/people',{cache:'no-store'}); const list=(await r.json()).people||[];
    box.innerHTML='';
    if(!list.length){ box.innerHTML='<div class="empty">No one enrolled yet. HAL adds people as it meets them.</div>'; return; }
    for(const p of list){
      const row=document.createElement('div'); row.className='person';
      const nm=document.createElement('div'); nm.className='pname'; nm.textContent=p.name; row.appendChild(nm);
      const meta=document.createElement('div'); meta.className='meta';
      const bits=[(p.conversation_count||0)+' conv'+(p.conversation_count===1?'':'s')];
      if(p.last_seen) bits.push('last seen '+String(p.last_seen).replace('T',' '));
      meta.textContent=bits.join('  •  '); row.appendChild(meta);
      if(p.present) row.appendChild(badge('', 'here now', '#39d353'));
      if(p.has_face) row.appendChild(badge('face','face'));
      if(p.has_memory) row.appendChild(badge('mem','memory'));
      const ren=document.createElement('button'); ren.className='btn-ren'; ren.textContent='Rename';
      ren.onclick=()=>renPerson(p.name); row.appendChild(ren);
      const del=document.createElement('button'); del.className='btn-del'; del.textContent='Delete';
      del.onclick=()=>delPerson(p.name); row.appendChild(del);
      box.appendChild(row);
    }
  } catch(e){ box.innerHTML='<div class="empty">could not load people</div>'; }
}
async function delPerson(name){
  if(!confirm('Delete '+name+'?\n\nThis erases their face, profile, notes, transcripts and semantic memory. It cannot be undone.')) return;
  await post('/api/hal/delete', {name});
}
async function renPerson(name){
  const nn=prompt('Rename '+name+' to:', name);
  if(nn===null) return;
  const t=nn.trim();
  if(!t || t===name) return;
  await post('/api/hal/rename', {old:name, new:t});
}

poll(); loadPeople(); setInterval(poll, 1000); setInterval(refreshCam, 1500); setInterval(loadPeople, 5000);
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
            web.get("/api/hal/people", _people),
            web.post("/api/hal/delete", _delete_person),
            web.post("/api/hal/rename", _rename_person),
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


async def _people(request: web.Request) -> web.Response:
    ctx: AppContext = request.app["ctx"]
    return web.json_response({"people": ctx.list_people()})


async def _delete_person(request: web.Request) -> web.Response:
    ctx: AppContext = request.app["ctx"]
    name = str((await request.json()).get("name", "")).strip()
    if not name:
        return web.json_response({"error": "name required"}, status=400)
    result = await ctx.delete_person(name)
    return web.json_response(result, status=200 if result.get("ok") else 409)


async def _rename_person(request: web.Request) -> web.Response:
    ctx: AppContext = request.app["ctx"]
    body = await request.json()
    old = str(body.get("old", "")).strip()
    new = str(body.get("new", "")).strip()
    if not old or not new:
        return web.json_response({"error": "old and new names required"}, status=400)
    result = await ctx.rename_person(old, new)
    return web.json_response(result, status=200 if result.get("ok") else 409)


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
