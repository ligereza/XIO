#!/usr/bin/env python3
"""wake_mak.py -- plugin STAGED para el servidor xio del telefono Xiaomi.

*** NO DESPLEGADO. Lo instala el USUARIO: ***
  1. Copiar a la carpeta de plugins del xio (p.ej. /sdcard/xio_termux/new-plugins/).
  2. Relanzar el servidor con run_server.sh (regla del repo: nunca hot-reload
     con rutas nuevas).
  3. Registrar el blueprint `bp` en el app factory del xio.
  4. Probar: GET http://TELEFONO:5000/wake_mak/status

Qué hace: despierta a MAK (Debian) enviando un magic packet Wake-on-WiFi a
la MAC de su tarjeta wifi, por el broadcast del hotspot. Direccion segura:
el TELEFONO -> MAK (no al reves). No requiere que MAK este alcanzable; el
magic packet es un frame de broadcast.

Prerequisito en MAK: WoWLAN armado antes de suspender (hook
/lib/systemd/system-sleep/00-wowlan-mak) y MAK en suspend (S3). Desde
apagado total (S5) la wifi no escucha; ahi solo despierta por ethernet
(desde el PC Windows).
"""
import os
import socket

from flask import Blueprint, jsonify

bp = Blueprint("wake_mak", __name__, url_prefix="/wake_mak")

# La MAC real NO viaja en un repo publico: se lee del entorno. Este archivo esta
# en `staged/`, o sea que se DESPLIEGA AL TELEFONO, y alli la variable tiene que
# existir igual -- por eso la ausencia no cae a un valor de ejemplo: sin
# `MAC_WIFI_MAK` el endpoint responde el motivo. Un paquete magico enviado a una
# MAC de relleno no despierta nada y no falla: se pierde en el broadcast, que es
# la peor forma de romperse.
MAC_WIFI_MAK = os.environ.get("MAC_WIFI_MAK", "")
BROADCAST = "255.255.255.255"
PUERTOS = (9, 7)


def _magic(mac):
    limpia = mac.replace(":", "").replace("-", "")
    if len(limpia) != 12:
        raise ValueError("MAC invalida: %s" % mac)
    return b"\xff" * 6 + bytes.fromhex(limpia) * 16


def despertar(mac=None):
    mac = mac or MAC_WIFI_MAK
    if not mac:
        raise ValueError(
            "falta MAC_WIFI_MAK en el entorno: sin la MAC de destino no hay "
            "paquete magico que enviar")
    paquete = _magic(mac)
    enviados = 0
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        for p in PUERTOS:
            s.sendto(paquete, (BROADCAST, p))
            enviados += 1
    finally:
        s.close()
    return enviados


@bp.route("/wake", methods=["GET", "POST"])
def wake():
    try:
        n = despertar()
        return jsonify({"ok": True, "mac": MAC_WIFI_MAK, "paquetes": n,
                        "nota": "MAK debe estar en suspend con WoWLAN armado"})
    except (OSError, ValueError) as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/status", methods=["GET"])
def status():
    return jsonify({"plugin": "wake_mak", "objetivo_mac": MAC_WIFI_MAK,
                    "metodo": "magic packet UDP broadcast puertos 9/7",
                    "direccion": "telefono -> MAK (segura)"})
