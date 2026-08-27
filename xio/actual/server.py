"""Flask server exposing a scrcpy-like browser control panel for the Xiaomi phone."""

import os
import tempfile

from flask import Flask, Response, request, jsonify

from xiaomi_controller import XiaomiController

ADB_PATH = r"C:\XPEDR\XiaomiServer\platform-tools\adb.exe"
DEVICE_SERIAL = "192.168.127.125:5555"

app = Flask(__name__)
controller = XiaomiController(adb_path=ADB_PATH, serial=DEVICE_SERIAL)

INDEX_HTML = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Xiaomi Remote</title>
<style>
  :root {
    --bg: #0b0d12;
    --panel: #161a22;
    --panel-border: #262c38;
    --accent: #4f8cff;
    --text: #e8ebf0;
    --text-dim: #8b93a3;
    --ok: #3ecf6e;
    --bad: #e5484d;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }
  .app { display: flex; min-height: 100vh; }

  /* --- sidebar --- */
  .sidebar {
    position: fixed;
    top: 0; left: 0; bottom: 0;
    width: 260px;
    background: var(--panel);
    border-right: 1px solid var(--panel-border);
    transform: translateX(-100%);
    transition: transform 0.2s ease;
    z-index: 20;
    display: flex;
    flex-direction: column;
  }
  .sidebar.open { transform: translateX(0); }
  .sidebar-backdrop {
    position: fixed; inset: 0;
    background: rgba(0,0,0,0.5);
    z-index: 15;
    display: none;
  }
  .sidebar-backdrop.open { display: block; }
  .sidebar-header {
    display: flex; justify-content: space-between; align-items: center;
    padding: 14px 16px;
    border-bottom: 1px solid var(--panel-border);
    font-weight: 600;
  }
  .sidebar-header button {
    background: none; border: none; color: var(--text-dim);
    font-size: 20px; cursor: pointer;
  }
  #appSearch {
    margin: 10px 12px;
    padding: 8px 10px;
    border-radius: 8px;
    border: 1px solid var(--panel-border);
    background: var(--bg);
    color: var(--text);
  }
  .app-list { overflow-y: auto; flex: 1; padding: 4px 0; }
  .app-item {
    padding: 10px 16px;
    cursor: pointer;
    font-size: 13px;
    border-bottom: 1px solid rgba(255,255,255,0.03);
    word-break: break-all;
  }
  .app-item:hover { background: rgba(79,140,255,0.12); }
  .app-item:active { background: rgba(79,140,255,0.25); }

  /* --- main column --- */
  .main {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 14px 10px 24px;
  }
  .statusbar {
    width: 100%;
    max-width: 420px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 14px;
  }
  .statusbar button {
    background: var(--panel);
    border: 1px solid var(--panel-border);
    color: var(--text);
    padding: 8px 12px;
    border-radius: 8px;
    cursor: pointer;
    font-size: 13px;
  }
  .status-indicators {
    display: flex; align-items: center; gap: 10px;
    font-size: 13px; color: var(--text-dim);
  }
  .dot {
    width: 9px; height: 9px; border-radius: 50%;
    background: var(--text-dim); display: inline-block;
  }
  .dot.ok { background: var(--ok); }
  .dot.bad { background: var(--bad); }

  /* --- phone frame --- */
  .phone-frame {
    position: relative;
    width: min(92vw, 380px);
    background: #000;
    border-radius: 38px;
    padding: 14px;
    box-shadow: 0 0 0 2px #2a2f3a, 0 20px 50px rgba(0,0,0,0.6);
  }
  .phone-notch {
    position: absolute;
    top: 14px; left: 50%; transform: translateX(-50%);
    width: 90px; height: 18px;
    background: #000;
    border-radius: 0 0 14px 14px;
    z-index: 2;
  }
  .phone-screen-wrap {
    position: relative;
    width: 100%;
    aspect-ratio: 1080 / 2400;
    border-radius: 26px;
    overflow: hidden;
    background: #000;
  }
  .phone-screen-wrap img {
    width: 100%; height: 100%;
    object-fit: cover;
    display: block;
    touch-action: none;
    cursor: crosshair;
  }
  .loading-overlay {
    position: absolute; inset: 0;
    background: rgba(0,0,0,0);
    pointer-events: none;
    transition: background 0.15s ease;
  }
  .loading-overlay.active { background: rgba(0,0,0,0.12); }
  .loading-overlay.active::after {
    content: "";
    position: absolute; top: 10px; right: 10px;
    width: 14px; height: 14px;
    border: 2px solid rgba(255,255,255,0.4);
    border-top-color: #fff;
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  .side-btn {
    position: absolute;
    background: #1c1f27;
    border: 1px solid #2a2f3a;
    cursor: pointer;
  }
  .power-btn {
    right: -3px; top: 130px;
    width: 4px; height: 60px;
    border-radius: 0 4px 4px 0;
  }
  .vol-up-btn {
    left: -3px; top: 110px;
    width: 4px; height: 40px;
    border-radius: 4px 0 0 4px;
  }
  .vol-down-btn {
    left: -3px; top: 158px;
    width: 4px; height: 40px;
    border-radius: 4px 0 0 4px;
  }

  /* --- nav + text bars --- */
  .navbar {
    display: flex; gap: 26px;
    margin-top: 16px;
  }
  .nav-btn {
    background: var(--panel);
    border: 1px solid var(--panel-border);
    color: var(--text);
    width: 52px; height: 40px;
    border-radius: 10px;
    font-size: 16px;
    cursor: pointer;
  }
  .nav-btn:active { background: rgba(79,140,255,0.2); }

  .textbar {
    width: min(92vw, 380px);
    display: flex; gap: 8px;
    margin-top: 14px;
  }
  .textbar input {
    flex: 1;
    padding: 10px 12px;
    border-radius: 8px;
    border: 1px solid var(--panel-border);
    background: var(--panel);
    color: var(--text);
  }
  .textbar button {
    padding: 10px 16px;
    border-radius: 8px;
    border: none;
    background: var(--accent);
    color: white;
    cursor: pointer;
    font-weight: 600;
  }
</style>
</head>
<body>
  <div class="app">
    <div class="sidebar-backdrop" id="backdrop"></div>
    <aside class="sidebar" id="sidebar">
      <div class="sidebar-header">
        <span>Apps</span>
        <button id="closeSidebar">&times;</button>
      </div>
      <input id="appSearch" type="text" placeholder="Buscar app...">
      <div id="appList" class="app-list"></div>
    </aside>

    <main class="main">
      <div class="statusbar">
        <button id="toggleSidebar">&#9776; Apps</button>
        <div class="status-indicators">
          <span id="battery">&#128267; --%</span>
          <span id="connDot" class="dot"></span>
          <span id="connText">--</span>
        </div>
      </div>

      <div class="phone-frame">
        <div class="phone-notch"></div>
        <div class="phone-screen-wrap" id="screenWrap">
          <img id="screen" src="/screen">
          <div id="loadingOverlay" class="loading-overlay"></div>
        </div>
        <div class="side-btn power-btn" data-key="power" title="Power"></div>
        <div class="side-btn vol-up-btn" data-key="volume_up" title="Vol +"></div>
        <div class="side-btn vol-down-btn" data-key="volume_down" title="Vol -"></div>
      </div>

      <nav class="navbar">
        <button class="nav-btn" data-key="back" title="Atras">&#9664;</button>
        <button class="nav-btn" data-key="home" title="Home">&#9711;</button>
        <button class="nav-btn" data-key="recents" title="Recientes">&#9633;</button>
      </nav>

      <div class="textbar">
        <input id="txt" type="text" placeholder="Texto para escribir...">
        <button id="sendTxt">Enviar</button>
      </div>
    </main>
  </div>

<script>
const img = document.getElementById('screen');
const wrap = document.getElementById('screenWrap');
const overlay = document.getElementById('loadingOverlay');
let dragStart = null;
let inFlight = false;

async function postJSON(url, body) {
  return fetch(url, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  });
}

function setAspect(w, h) {
  if (w && h) wrap.style.aspectRatio = w + ' / ' + h;
}

function refreshScreen() {
  if (inFlight) return;
  inFlight = true;
  overlay.classList.add('active');
  const next = new Image();
  next.onload = () => {
    img.src = next.src;
    setAspect(next.naturalWidth, next.naturalHeight);
    overlay.classList.remove('active');
    inFlight = false;
  };
  next.onerror = () => { overlay.classList.remove('active'); inFlight = false; };
  next.src = '/screen?t=' + Date.now();
}

function toDeviceCoords(evt) {
  const rect = img.getBoundingClientRect();
  const scaleX = img.naturalWidth / rect.width;
  const scaleY = img.naturalHeight / rect.height;
  const x = Math.round((evt.clientX - rect.left) * scaleX);
  const y = Math.round((evt.clientY - rect.top) * scaleY);
  return [x, y];
}

img.addEventListener('pointerdown', (evt) => { dragStart = toDeviceCoords(evt); });

img.addEventListener('pointerup', async (evt) => {
  if (!dragStart) return;
  const [x1, y1] = dragStart;
  const [x2, y2] = toDeviceCoords(evt);
  dragStart = null;
  const dist = Math.hypot(x2 - x1, y2 - y1);
  if (dist < 15) {
    await postJSON('/tap', {x: x1, y: y1});
  } else {
    await postJSON('/swipe', {x1, y1, x2, y2, duration_ms: 300});
  }
  setTimeout(refreshScreen, 350);
});

document.querySelectorAll('[data-key]').forEach((el) => {
  el.addEventListener('click', async () => {
    await postJSON('/key', {key: el.dataset.key});
    setTimeout(refreshScreen, 350);
  });
});

async function sendText() {
  const el = document.getElementById('txt');
  const value = el.value;
  if (!value) return;
  await postJSON('/text', {text: value});
  el.value = '';
  setTimeout(refreshScreen, 350);
}
document.getElementById('sendTxt').addEventListener('click', sendText);
document.getElementById('txt').addEventListener('keydown', (evt) => {
  if (evt.key === 'Enter') sendText();
});

async function loadApps() {
  const res = await fetch('/apps');
  const apps = await res.json();
  const list = document.getElementById('appList');
  list.innerHTML = '';
  apps.forEach((pkg) => {
    const item = document.createElement('div');
    item.className = 'app-item';
    item.textContent = pkg;
    item.addEventListener('click', async () => {
      await postJSON('/open', {package: pkg});
      closeSidebar();
      setTimeout(refreshScreen, 600);
    });
    list.appendChild(item);
  });
}

document.getElementById('appSearch').addEventListener('input', (evt) => {
  const q = evt.target.value.toLowerCase();
  document.querySelectorAll('.app-item').forEach((el) => {
    el.style.display = el.textContent.toLowerCase().includes(q) ? '' : 'none';
  });
});

function openSidebar() {
  document.getElementById('sidebar').classList.add('open');
  document.getElementById('backdrop').classList.add('open');
}
function closeSidebar() {
  document.getElementById('sidebar').classList.remove('open');
  document.getElementById('backdrop').classList.remove('open');
}
document.getElementById('toggleSidebar').addEventListener('click', openSidebar);
document.getElementById('closeSidebar').addEventListener('click', closeSidebar);
document.getElementById('backdrop').addEventListener('click', closeSidebar);

async function pollStatus() {
  const dot = document.getElementById('connDot');
  const text = document.getElementById('connText');
  const battery = document.getElementById('battery');
  try {
    const res = await fetch('/status');
    const data = await res.json();
    dot.classList.toggle('ok', data.connected);
    dot.classList.toggle('bad', !data.connected);
    text.textContent = data.connected ? 'Conectado' : 'Sin conexion';
    if (data.battery && data.battery.level >= 0) {
      const bolt = data.battery.charging ? ' ⚡' : '';
      battery.textContent = '🔋 ' + data.battery.level + '%' + bolt;
    }
  } catch (e) {
    dot.classList.remove('ok');
    dot.classList.add('bad');
    text.textContent = 'Sin conexion';
  }
}

loadApps();
pollStatus();
setInterval(pollStatus, 8000);
setInterval(refreshScreen, 2000);
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return INDEX_HTML


@app.route("/screen")
def screen():
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        controller.screenshot(path)
        with open(path, "rb") as f:
            data = f.read()
    finally:
        os.remove(path)
    resp = Response(data, mimetype="image/png")
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/tap", methods=["POST"])
def tap():
    body = request.get_json(force=True)
    controller.tap(body["x"], body["y"])
    return jsonify({"ok": True})


@app.route("/swipe", methods=["POST"])
def swipe():
    body = request.get_json(force=True)
    controller.swipe(
        body["x1"], body["y1"], body["x2"], body["y2"], body.get("duration_ms", 300)
    )
    return jsonify({"ok": True})


@app.route("/text", methods=["POST"])
def text():
    body = request.get_json(force=True)
    controller.text(body["text"])
    return jsonify({"ok": True})


@app.route("/key", methods=["POST"])
def key():
    body = request.get_json(force=True)
    controller.named_key(body["key"])
    return jsonify({"ok": True})


@app.route("/apps")
def apps():
    return jsonify(controller.list_launchable_packages())


@app.route("/open", methods=["POST"])
def open_app():
    body = request.get_json(force=True)
    controller.open_app(body["package"])
    return jsonify({"ok": True})


@app.route("/status")
def status():
    try:
        battery = controller.battery_status()
        return jsonify({"connected": True, "battery": battery})
    except Exception:
        return jsonify({"connected": False, "battery": None})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
