#!/usr/bin/env python3
"""monitor.py -- ojo de SOLO LECTURA sobre el telefono xio (router de MAK).

El telefono es el unico internet de MAK: este monitor JAMAS hace POST ni
toca endpoints de red/hotspot/carga. Poll cada 60s a una allowlist dura
de rutas GET; historia en historia.jsonl, ultimo estado en estado.json,
alertas ntfy con antispam.

    python3 monitor.py            # daemon
    python3 monitor.py --una-vez  # un poll (pruebas)
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, "/home/mak/research")
from research_lib import load_env, ntfy_publish  # noqa: E402

BASE_DIR = "/home/mak/xio_puente"
XIO_BASE = os.environ.get("XIO_BASE", "http://192.168.95.203:5000")
RUTAS_LECTURA = ("/status", "/obs", "/battery/status", "/connectivity/status")
HISTORIA = os.path.join(BASE_DIR, "historia.jsonl")
ESTADO = os.path.join(BASE_DIR, "estado.json")
ALERTAS = os.path.join(BASE_DIR, "alertas.json")
INTERVALO = 60
ANTISPAM_S = 1800


def _get(ruta):
    url = XIO_BASE.rstrip("/") + ruta
    headers = {"User-Agent": "mak-xio-puente/1.0"}
    token = os.environ.get("XIO_TOKEN")
    if token:
        headers["X-Token"] = token
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=6) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return e.code, None
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return 0, None


def _alerta(clave, mensaje):
    """ntfy con antispam de 30 min por clave."""
    try:
        with open(ALERTAS, encoding="utf-8") as f:
            estado = json.load(f)
    except (OSError, json.JSONDecodeError):
        estado = {}
    ahora = time.time()
    if ahora - estado.get(clave, 0) < ANTISPAM_S:
        return
    estado[clave] = ahora
    try:
        with open(ALERTAS, "w", encoding="utf-8") as f:
            json.dump(estado, f)
    except OSError:
        pass
    ntfy_publish(os.environ.get("NTFY_TOPIC_OUT", ""), mensaje,
                 title="xio puente")


def _resumen(rutas):
    """Extraccion defensiva de lo que mas importa."""
    res = {}
    bat = rutas.get("/battery/status") or {}
    st = rutas.get("/status") or {}
    if isinstance(bat, dict):
        for k in ("level", "battery", "pct", "percentage"):
            v = bat.get(k)
            if isinstance(v, (int, float)):
                res["bateria_pct"] = int(v)
                break
        for k in ("charging", "cargando", "plugged"):
            if k in bat:
                res["cargando"] = bool(bat.get(k))
                break
    conn = rutas.get("/connectivity/status") or {}
    if isinstance(conn, dict):
        for k in ("clients", "clientes", "tethered_clients", "n_clients"):
            v = conn.get(k)
            if isinstance(v, list):
                res["clientes_hotspot"] = len(v)
                break
            if isinstance(v, (int, float)):
                res["clientes_hotspot"] = int(v)
                break
    if isinstance(st, dict) and "plugins" in st:
        try:
            res["plugins"] = len(st["plugins"])
        except TypeError:
            pass
    return res


def poll(fallos_previos=0):
    rutas, http_max, bloqueado = {}, 0, False
    for ruta in RUTAS_LECTURA:
        code, data = _get(ruta)
        http_max = max(http_max, code)
        if code == 403:
            bloqueado = True
            break  # gate de deny: no insistir en las demas rutas
        if code == 200 and data is not None:
            rutas[ruta] = data
    alcanzable = http_max >= 200
    estado = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "ts_epoch": time.time(),
        "base": XIO_BASE,
        "alcanzable": alcanzable,
        "bloqueado": bloqueado,
        "http": http_max,
        "resumen": _resumen(rutas),
        "rutas_ok": sorted(rutas.keys()),
    }
    tmp = ESTADO + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False)
    os.replace(tmp, ESTADO)
    try:
        if os.path.exists(HISTORIA) and os.path.getsize(HISTORIA) > 5 << 20:
            os.replace(HISTORIA, HISTORIA + ".1")
        with open(HISTORIA, "a", encoding="utf-8") as f:
            f.write(json.dumps(estado, ensure_ascii=False) + "\n")
    except OSError:
        pass

    fallos = 0 if alcanzable else fallos_previos + 1
    if bloqueado:
        _alerta("bloqueado", "el telefono devuelve 403: la IP de MAK esta en "
                             "XIO_DENY_IPS. Decision del usuario abrirla.")
    elif fallos == 3:
        _alerta("caido", "servidor xio inalcanzable hace 3 minutos (%s). "
                         "Probable: relanzar run_server.sh en el telefono."
                         % XIO_BASE)
    elif alcanzable and fallos_previos >= 3:
        _alerta("recuperado", "servidor xio DE VUELTA en linea (%s)." % XIO_BASE)
    bat = estado["resumen"].get("bateria_pct")
    if (bat is not None and bat < 20
            and not estado["resumen"].get("cargando", False)):
        _alerta("bateria", "bateria del telefono-router en %d%% y "
                           "descargando." % bat)
    return estado, fallos


def main():
    os.makedirs(BASE_DIR, exist_ok=True)
    load_env()
    if "--una-vez" in sys.argv:
        estado, _ = poll()
        print(json.dumps(estado, ensure_ascii=False, indent=1))
        return 0
    print("[xio_puente] monitor GET-only sobre %s cada %ds"
          % (XIO_BASE, INTERVALO), flush=True)
    fallos = 0
    while True:
        try:
            _, fallos = poll(fallos)
        except Exception as e:  # noqa: BLE001 - el daemon no muere por un poll
            print("[xio_puente] poll error: %s" % e, file=sys.stderr,
                  flush=True)
        time.sleep(INTERVALO)


if __name__ == "__main__":
    sys.exit(main())
