"""
Self-contained cue-panel HTML for the showcontrol plugin.

Served from GET /api/plugins/showcontrol/panel -- the xiotech M2 "panel de
control HTTP para disparar cues desde navegador/tablet". No frameworks, no CDN,
no external assets: one string, works offline on the hotspot LAN. All actions
go through the plugin's existing validated JSON endpoints.
"""

PANEL_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>xio · show control</title>
<style>
  :root{--bg:#111317;--panel:#191c22;--line:#2a2e37;--ink:#eef0f3;--dim:#8a90a0;
        --accent:#7fd1ae;--warn:#ffd166;--hot:#ff6b6b;}
  *{box-sizing:border-box;-webkit-tap-highlight-color:transparent;}
  body{margin:0;background:var(--bg);color:var(--ink);
       font-family:ui-monospace,Menlo,Consolas,monospace;padding:14px 12px 40px;}
  h1{font-size:14px;font-weight:600;margin:0 0 2px;}
  .sub{color:var(--dim);font-size:11px;margin-bottom:14px;}
  #go{width:100%;padding:26px 0;font-size:28px;font-weight:700;letter-spacing:.12em;
      background:var(--accent);color:#0b0d10;border:none;border-radius:14px;cursor:pointer;}
  #go:active{filter:brightness(1.15);}
  #go:disabled{background:#2a2e37;color:var(--dim);}
  .row{display:flex;gap:8px;margin-top:10px;}
  .row button{flex:1;padding:14px 0;font-size:14px;font-weight:600;border-radius:10px;
      border:1px solid var(--line);background:var(--panel);color:var(--ink);cursor:pointer;}
  #stop:active{border-color:var(--warn);color:var(--warn);}
  #release:active{border-color:var(--hot);color:var(--hot);}
  .state{display:flex;gap:8px;align-items:center;margin:14px 0 8px;font-size:12px;}
  .dot{width:10px;height:10px;border-radius:50%;background:var(--dim);flex:none;}
  .dot.fading{background:var(--warn);}
  .dot.idle{background:var(--accent);}
  .dot.stopped{background:var(--hot);}
  #statetxt{color:var(--dim);}
  #cuelist{margin-top:6px;}
  .cue{display:flex;gap:10px;padding:10px 12px;border:1px solid var(--line);
       border-radius:10px;margin-bottom:6px;font-size:13px;align-items:center;cursor:pointer;}
  .cue .n{color:var(--dim);width:24px;}
  .cue .lbl{flex:1;}
  .cue .meta{color:var(--dim);font-size:11px;}
  .cue.current{border-color:var(--accent);background:#13201b;}
  details{margin-top:16px;}
  summary{color:var(--dim);font-size:12px;cursor:pointer;}
  textarea{width:100%;height:150px;margin-top:8px;background:#0e1015;color:var(--ink);
       border:1px solid var(--line);border-radius:8px;font-family:inherit;font-size:11px;padding:8px;}
  .mini{margin-top:8px;display:flex;gap:8px;}
  .mini input{flex:1;background:#0e1015;color:var(--ink);border:1px solid var(--line);
       border-radius:8px;padding:8px;font-family:inherit;font-size:12px;}
  .mini button{padding:8px 14px;border-radius:8px;border:1px solid var(--line);
       background:var(--panel);color:var(--ink);cursor:pointer;font-size:12px;}
  #err{color:var(--hot);font-size:11px;min-height:14px;margin-top:8px;word-break:break-all;}
</style>
</head>
<body>
<h1>xio &middot; show control</h1>
<div class="sub">cue engine &middot; GO / STOP / RELEASE &middot; corre en el telefono</div>

<button id="go">GO</button>
<div class="row">
  <button id="stop">STOP</button>
  <button id="release">RELEASE 2s</button>
</div>

<div class="state"><div class="dot" id="dot"></div><span id="statetxt">&mdash;</span></div>
<div id="cuelist"></div>

<details>
  <summary>timeline (el show se dispara solo)</summary>
  <div class="row"><button id="tlplay">PLAY</button><button id="tlpause">PAUSE</button>
    <button id="tlreset">|&lt;</button></div>
  <div id="tlstate" class="meta">&mdash;</div>
  <textarea id="tljson" placeholder='{"events":[{"at":0,"cue":0},{"at":5,"cue":1},{"at":20,"cue":2}]}'></textarea>
  <div class="mini"><button id="tlload">cargar timeline</button></div>
</details>

<details>
  <summary>cargar cue list (JSON)</summary>
  <textarea id="json" placeholder='{"output":{"protocol":"artnet","host":"192.168.1.50"},"cues":[{"label":"open","fade":3,"levels":{"0":{"1":255}}}]}'></textarea>
  <div class="mini"><button id="load">cargar</button></div>
</details>

<details>
  <summary>telemetria</summary>
  <div id="obs" class="meta">&mdash;</div>
</details>

<details>
  <summary>descubrir nodos art-net</summary>
  <div class="mini"><button id="scan">SCAN LAN</button></div>
  <div id="nodes"></div>
</details>

<details>
  <summary>wake-on-lan</summary>
  <div class="mini">
    <input id="mac" placeholder="AA:BB:CC:DD:EE:FF">
    <button id="wol">WOL</button>
  </div>
</details>

<details>
  <summary>osc-in (recibir cues)</summary>
  <div class="mini">
    <input id="oscport" placeholder="9001" inputmode="numeric">
    <button id="oscstart">ESCUCHAR</button>
    <button id="oscstop">PARAR</button>
  </div>
  <div id="oscstate" class="meta">&mdash;</div>
</details>

<details>
  <summary>token de show (muros)</summary>
  <div class="mini">
    <input id="tok" placeholder="token (vacio = abierto)" type="password">
    <button id="toksave">usar</button>
  </div>
  <div id="tokstate" class="meta">&mdash;</div>
</details>

<div id="err"></div>

<script>
const B = "/api/plugins/showcontrol";
const $ = id => document.getElementById(id);
let cues = [];

function token(){ try{ return localStorage.getItem("show_token") || ""; }catch(e){ return ""; } }
async function api(path, body){
  const h = {"Content-Type":"application/json"};
  if(token()) h["X-Show-Token"] = token();
  const r = await fetch(B + path, body === undefined ? {headers: h} :
    {method:"POST", headers: h, body: JSON.stringify(body)});
  const d = await r.json().catch(() => ({}));
  if(!r.ok || d.ok === false) throw new Error(d.error || ("HTTP " + r.status));
  return d;
}
function err(e){ $("err").textContent = e ? String(e.message || e) : ""; }

function renderState(st){
  $("dot").className = "dot " + st.state;
  $("statetxt").textContent =
    st.state + (st.label ? " · " + st.label : "") +
    " · cue " + (st.position + 1) + "/" + st.cue_count +
    (st.active ? " · LIVE" : "");
  document.querySelectorAll(".cue").forEach((el, i) =>
    el.classList.toggle("current", i === st.position));
}
function renderCues(){
  $("cuelist").innerHTML = cues.map((c, i) =>
    '<div class="cue" data-i="' + i + '"><span class="n">' + (i + 1) + '</span>' +
    '<span class="lbl">' + String(c.label).replace(/[<>&]/g, "") + '</span>' +
    '<span class="meta">fade ' + c.fade + 's' +
    (c.follow != null ? ' · follow ' + c.follow + 's' : '') + '</span></div>').join("");
  document.querySelectorAll(".cue").forEach(el =>
    el.onclick = () => api("/cue/go", {index: +el.dataset.i}).catch(err));
}
async function refresh(){
  try{
    const d = await api("/cues");
    cues = d.cues || [];
    renderCues();
    renderState(d.state);
    err("");
  }catch(e){ err(e); }
}
async function poll(){
  try{ renderState((await api("/cue/state")).state); }catch(e){}
}
async function pollObs(){
  try{
    const o = await api("/obs");
    const r = o.rates_per_s || {};
    const th = Object.entries(o.threads || {})
      .filter(([,v]) => v.expected).map(([k]) => k).join(",") || "idle";
    $("obs").textContent =
      o.health + " · up " + o.uptime_s + "s · " +
      "a" + (o.sent.artnet||0) + "/s" + (r.artnet ? "(" + r.artnet + ")" : "") + " " +
      "s" + (o.sent.sacn||0) + " o" + (o.sent.osc||0) +
      " · thr " + th + (o.last_error ? " · ERR " + o.last_error : "");
  }catch(e){}
}

$("go").onclick = () => api("/cue/go", {}).catch(err);
$("stop").onclick = () => api("/cue/stop", {}).catch(err);
$("release").onclick = () => api("/cue/release", {fade: 2}).catch(err);
$("load").onclick = () => {
  let body;
  try{ body = JSON.parse($("json").value); }catch(e){ return err("JSON invalido: " + e.message); }
  api("/cues", body).then(refresh).catch(err);
};
$("wol").onclick = () => api("/wol", {mac: $("mac").value}).catch(err);

async function pollOscin(){
  try{
    const st = (await api("/oscin")).state;
    $("oscstate").textContent = st.listening
      ? "escuchando :" + st.port + " · rx " + st.stats.received +
        " · ok " + st.stats.acted + " · ign " + st.stats.ignored +
        (st.stats.last_address ? " · " + st.stats.last_address : "")
      : "apagado";
  }catch(e){}
}
$("oscstart").onclick = () => {
  const p = parseInt($("oscport").value, 10);
  api("/oscin", p ? {port: p} : {}).then(pollOscin).catch(err);
};
$("oscstop").onclick = () => api("/oscin/stop", {}).then(pollOscin).catch(err);

async function pollAuth(){
  try{
    const a = await api("/auth");
    $("tokstate").textContent = a.protected
      ? (token() ? "protegido · token guardado en este navegador" : "protegido · FALTA token aqui")
      : "abierto (sin token)";
  }catch(e){}
}
$("toksave").onclick = () => {
  try{ localStorage.setItem("show_token", $("tok").value.trim()); }catch(e){}
  $("tok").value = "";
  pollAuth();
  err("");
};

function fmt(s){ s = Math.max(0, s|0); return (s/60|0) + ":" + String(s%60).padStart(2,"0"); }
async function pollTl(){
  try{
    const st = (await api("/timeline/state")).state;
    $("tlstate").textContent = (st.playing ? "▶ " : "▮▮ ") +
      fmt(st.position) + " / " + fmt(st.duration) +
      " · " + st.fired + "/" + st.events + " cues";
  }catch(e){}
}
$("tlload").onclick = () => {
  let body;
  try{ body = JSON.parse($("tljson").value); }catch(e){ return err("JSON invalido: " + e.message); }
  api("/timeline", body).then(pollTl).catch(err);
};
$("tlplay").onclick = () => api("/timeline/play", {}).then(pollTl).catch(err);
$("tlpause").onclick = () => api("/timeline/pause", {}).then(pollTl).catch(err);
$("tlreset").onclick = () => api("/timeline/locate", {t: 0}).then(pollTl).catch(err);

function clean(s){ return String(s == null ? "" : s).replace(/[<>&]/g, ""); }
function renderNodes(nodes){
  if(!nodes.length){ $("nodes").innerHTML = '<div class="meta">sin nodos</div>'; return; }
  $("nodes").innerHTML = nodes.map(n =>
    '<div class="cue" data-ip="' + clean(n.ip) + '"><span class="lbl">' +
    (clean(n.short_name) || clean(n.ip)) + '</span><span class="meta">' + clean(n.ip) +
    (n.ports ? ' · ' + n.ports + 'p' : '') + (n.mac ? ' · ' + clean(n.mac) : '') +
    '</span></div>').join("");
  // tap a node -> drop its IP into the show-JSON output host
  document.querySelectorAll("#nodes .cue").forEach(el => el.onclick = () => {
    let body; try{ body = JSON.parse($("json").value || "{}"); }catch(e){ body = {}; }
    body.output = Object.assign({protocol:"artnet"}, body.output, {host: el.dataset.ip});
    $("json").value = JSON.stringify(body);
    err("output.host = " + el.dataset.ip);
  });
}
$("scan").onclick = () => {
  $("scan").disabled = true; $("nodes").innerHTML = '<div class="meta">escaneando...</div>';
  api("/discover", {timeout: 3}).then(d => { renderNodes(d.nodes || []); err(""); })
    .catch(err).finally(() => { $("scan").disabled = false; });
};

refresh();
pollAuth();
pollOscin();
setInterval(poll, 1000);
setInterval(pollObs, 2000);
setInterval(pollTl, 1000);
setInterval(pollOscin, 2000);
</script>
</body>
</html>
"""
