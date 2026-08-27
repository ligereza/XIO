# -*- coding: utf-8 -*-
"""Chequeo pre-show de un comando: GO/NO-GO contra el xio (foh_monitor).

Uso (Windows):
    py xio/show_kit/check_show.py                 # IP hotspot por defecto
    py xio/show_kit/check_show.py 10.195.40.198   # otra IP (LAN de casa)
o doble click en check_show.bat.

Solo stdlib. Cada item imprime [GO] verde o [NO-GO] rojo con el detalle real.
"""
import json
import sys
import urllib.request

HOST = sys.argv[1] if len(sys.argv) > 1 else "192.168.127.125"
BASE = f"http://{HOST}:5000"
FOH = f"{BASE}/api/plugins/foh_monitor"

G, R, Y, N = "\033[92m", "\033[91m", "\033[93m", "\033[0m"
try:
    import os
    os.system("")  # habilita ANSI en la consola de Windows
except Exception:
    pass

results = []


def item(name, ok, detail="", warn=False):
    tag = f"{Y}[AVISO]{N}" if warn else (f"{G}[GO]   {N}" if ok else f"{R}[NO-GO]{N}")
    print(f" {tag} {name}" + (f" -- {detail}" if detail else ""))
    results.append(ok or warn)


def get(url, timeout=6):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, r.read()


def get_json(url):
    status, body = get(url)
    return status, json.loads(body)


print(f"\n== CHEQUEO PRE-SHOW xio @ {HOST} ==\n")

# 1. server responde
try:
    status, plugins = get_json(f"{BASE}/api/plugins")
    item("Server xio responde", status == 200, f"{len(plugins)} plugins cargados")
except Exception as e:
    item("Server xio responde", False, f"{e} -- el telefono esta prendido y en esta red?")
    print(f"\n{R}== NO-GO: sin server no hay mas chequeos =={N}\n")
    sys.exit(1)

# 2. foh_monitor cargado
ids = [p.get("id") for p in plugins]
item("Plugin foh_monitor cargado", "foh_monitor" in ids)

# 3. panel HTTP 200
try:
    status, body = get(f"{FOH}/panel")
    item("Panel FOH sirve", status == 200 and len(body) > 1000, f"HTTP {status}, {len(body)} bytes")
except Exception as e:
    item("Panel FOH sirve", False, str(e))

# 4. status: listeners, TC, bateria
try:
    status, st = get_json(f"{FOH}/status")
except Exception as e:
    item("Status foh_monitor", False, str(e))
    sys.exit(1)

for canal, label in (("artnet", "Listener Art-Net :6454"),
                     ("sacn", "Listener sACN :5568"),
                     ("osc", "Listener OSC :7000")):
    ch = st["channels"][canal]
    if ch.get("error"):
        item(label, False, ch["error"])
    else:
        seen = ch.get("last_seen") or "aun sin paquetes (normal antes de conectar)"
        item(label, True, f"bound OK; ultimo paquete: {seen}")

tc = st.get("timecode") or {}
tc_state = tc.get("state", "sin_senal")
if tc_state == "corriendo":
    item("Timecode", True, f"{tc.get('value')} corriendo ({tc.get('pps')} pps)")
elif tc_state == "sin_senal" or (tc_state == "caido" and (tc.get("age") or 0) > 120):
    item("Timecode", True, "sin senal reciente -- arranca cuando Chataigne emita /timecode", warn=True)
else:
    item("Timecode", False, f"{tc_state} en {tc.get('value')} (hace {tc.get('age')}s)")

audio = st.get("audio") or {}
if audio.get("available"):
    item("Audio (mic)", True, f"nivel {audio.get('level_db')} dBFS")
else:
    item("Audio (mic)", True, f"N/D: {audio.get('reason', '')} -- esperado, no bloquea", warn=True)

bat = st.get("battery") or {}
lvl, chg = bat.get("level"), bat.get("charging")
item("Bateria del telefono", lvl is not None and (lvl >= 60 or chg),
     f"{lvl}% {'cargando' if chg else 'SIN cargar'}")

sl = st.get("setlist") or {}
if sl.get("total"):
    item("Setlist cargada", True, f"{sl['total']} temas, actual: {sl.get('current')}")
else:
    item("Setlist cargada", True, "vacia -- usa cargar_setlist.bat", warn=True)

item("Registro JSONL", bool(st.get("log_file")), st.get("log_file", ""))

# IP pa las consolas
hotspot = HOST.startswith("192.168.")
print(f"\n IP pa consolas/Chataigne/Resolume: {G}{HOST}{N}"
      + ("" if hotspot else f" {Y}(OJO: no parece IP de hotspot; en show debe ser 192.168.x.x){N}"))
print(f"   Art-Net -> {HOST}:6454 | sACN unicast -> {HOST}:5568 | OSC/TC -> {HOST}:7000")
print(f"   Panel FOH: http://{HOST}:5000/api/plugins/foh_monitor/panel")

ok = all(results)
print(f"\n== {'%sTODO GO%s' % (G, N) if ok else '%sHAY NO-GO ARRIBA%s' % (R, N)} ==\n")
sys.exit(0 if ok else 1)
