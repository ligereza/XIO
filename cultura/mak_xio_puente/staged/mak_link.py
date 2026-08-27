#!/usr/bin/env python3
"""mak_link.py -- plugin STAGED para el servidor xio del telefono.

*** NO ESTA DESPLEGADO. Lo instala el USUARIO cuando quiera: ***
  1. Copiar este archivo a /sdcard/xio_termux/new-plugins/ (o la carpeta
     de plugins que use run_server.sh).
  2. Relanzar el servidor COMPLETO con run_server.sh (regla del repo:
     nunca hot-reload de un plugin con rutas nuevas).
  3. Verificar: GET http://TELEFONO:5000/mak_link/ping -> {"ok": true}

Que hace: invierte la direccion del puente. En vez de que MAK pregunte,
el TELEFONO reporta su estado a MAK cada 5 minutos (POST al hub de MAK).
Ventaja: sobrevive cambios de subred del hotspot y NAT; MAK nunca necesita
tocar el telefono.

Nota para hub.py v2 de MAK (no implementado aun, a proposito): agregar un
handler POST /api/xio_push que valide Content-Type json, tamano < 64KB, y
escriba /home/mak/xio_puente/estado.json con el mismo formato del monitor
(campos ts, ts_epoch, alcanzable=True, resumen). Mientras no exista, este
plugin solo loguea el fallo y no molesta.
"""
import json
import threading
import time
import urllib.request

from flask import Blueprint, jsonify

bp = Blueprint("mak_link", __name__, url_prefix="/mak_link")

MAK_HUB = "http://192.168.95.85:8900/api/xio_push"  # IP wifi de MAK
INTERVALO = 300


@bp.route("/ping", methods=["GET"])
def ping():
    return jsonify({"ok": True, "plugin": "mak_link", "destino": MAK_HUB})


def _reportar():
    while True:
        try:
            propio = urllib.request.urlopen(
                "http://127.0.0.1:5000/status", timeout=5).read()
            req = urllib.request.Request(
                MAK_HUB, data=propio,
                headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=6).read()
        except Exception as e:  # noqa: BLE001 - best-effort, no tumba el server
            print("[mak_link] push fallo (normal si MAK duerme): %s" % e)
        time.sleep(INTERVALO)


def iniciar_push():
    """Llamar desde el registro de plugins si se quiere el push activo."""
    t = threading.Thread(target=_reportar, daemon=True)
    t.start()
    return t
