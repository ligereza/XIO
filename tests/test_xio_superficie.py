# -*- coding: utf-8 -*-
"""VCD-01 en xio: que se cerro, y que se dejo abierto A PROPOSITO.

El diagnostico de seguridad del 2026-07-27 pide autenticacion global en xio, y
su propio resumen condiciona la severidad: "CRITICO cuando XIO esta activo en
una red con clientes no totalmente confiables".

Decision del usuario ese mismo dia, y manda sobre la recomendacion generica:
NO hay token. El hotspot tiene clave, la red de casa es suya, y en show tampoco
lo deja abierto. Un token seria friccion en el unico momento en que este
controlador tiene que responder sin pensarlo.

Lo que si quedo cerrado es lo que la clave del hotspot NO cubre, y esa es la
distincion que importa:

- CORS: ahi el atacante no es un cliente de la red sino cualquier PAGINA WEB
  abierta en un dispositivo ya conectado. Una clave de wifi no filtra
  navegadores.
- Instalar plugins: es ejecutar codigo en este proceso, y el vector puede ser un
  ZIP que el propio usuario baje.

Estos tests miran el ARCHIVO, no levantan el server: xio corre en Termux y sus
dependencias no estan en CI. Es mas debil que un test de integracion y por eso
se dice.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
SERVER = _REPO / "xio" / "new" / "server.py"

pytestmark = pytest.mark.skipif(not SERVER.is_file(), reason="xio/new/server.py no esta")


def _src() -> str:
    return SERVER.read_text(encoding="utf-8", errors="replace")


def test_no_hay_cors_abierto():
    """El caso que la clave del hotspot no cubre: una pagina cualquiera."""
    s = _src()
    assert '"Access-Control-Allow-Origin", "*"' not in s, (
        "CORS * deja que cualquier pagina abierta en un dispositivo YA conectado "
        "maneje el telefono; la clave del wifi no filtra navegadores")
    assert "XIO_ORIGENES" in s


def test_instalar_plugins_esta_apagado_por_defecto():
    """Instalar un plugin es ejecutar su codigo: el registry hace exec_module."""
    s = _src()
    i = s.index("def api_plugin_install")
    cuerpo = s[i:i + 700]
    assert "XIO_PERMITIR_INSTALAR_PLUGINS" in cuerpo
    assert "403" in cuerpo


def test_la_decision_de_no_poner_token_esta_escrita_con_su_causa():
    """Una ausencia deliberada que no se explica se lee como un olvido, y el
    proximo que audite el repo la va a 'arreglar' otra vez."""
    s = _src()
    assert "VCD-01" in s
    assert "hotspot tiene clave" in s
    # y con condicion de retiro, como pide la meta-regla del repo
    assert "Retiro de esta nota" in s


def test_la_denylist_de_ips_sigue_ahi():
    """Es la defensa que ya existia y que el usuario si usa."""
    assert "_DENY_IPS" in _src() and "XIO_DENY_IPS" in _src()
