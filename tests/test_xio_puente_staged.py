"""Offline tests for the two STAGED xio plugins rescued on 2026-07-30:
cultura/mak_xio_puente/staged/mak_link.py and staged/wake_mak.py.

Neither is deployed (the user installs them on the phone by hand), so the
tests cover the pure logic that must be right BEFORE that day: the magic
packet bytes, the fail-loud behavior when MAC_WIFI_MAK is absent (a packet
sent to a filler MAC dies silently in the broadcast, which is the worst way
to break), and the read-only surface of each blueprint. Sockets are faked;
Flask serves via its test client only.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

pytest.importorskip("flask")  # xio plugin dep, not a core flujo dependency
from flask import Flask  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
STAGED = RAIZ / "cultura" / "mak_xio_puente" / "staged"


def _cargar(nombre):
    spec = importlib.util.spec_from_file_location(
        nombre + "_bajo_prueba", STAGED / (nombre + ".py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


wake_mak = _cargar("wake_mak")
mak_link = _cargar("mak_link")


def _app(bp):
    app = Flask(__name__)
    app.register_blueprint(bp)
    return app.test_client()


# ------------------------------------------------------------------- _magic

def test_magic_packet_es_ff6_mas_mac_16_veces():
    mac = "aa:bb:cc:dd:ee:ff"
    paquete = wake_mak._magic(mac)
    assert len(paquete) == 102
    assert paquete[:6] == b"\xff" * 6
    assert paquete[6:] == bytes.fromhex("aabbccddeeff") * 16


def test_magic_acepta_guiones_y_rechaza_macs_invalidas():
    con_guiones = wake_mak._magic("AA-BB-CC-DD-EE-FF")
    con_puntos = wake_mak._magic("AA:BB:CC:DD:EE:FF")
    assert con_guiones == con_puntos
    for mala in ("aa:bb:cc", "", "aa:bb:cc:dd:ee:ff:00"):
        with pytest.raises(ValueError):
            wake_mak._magic(mala)
    with pytest.raises(ValueError):
        wake_mak._magic("zz:bb:cc:dd:ee:ff")  # non-hex


# ---------------------------------------------------------------- despertar

class FakeSocket:
    enviados = []
    opciones = []
    cerrado = False

    def __init__(self, *a, **k):
        pass

    def setsockopt(self, *a):
        FakeSocket.opciones.append(a)

    def sendto(self, datos, destino):
        FakeSocket.enviados.append((datos, destino))

    def close(self):
        FakeSocket.cerrado = True


def test_despertar_sin_mac_falla_ruidoso_no_silencioso(monkeypatch):
    """The rescue's own comment: a magic packet to a filler MAC 'se pierde en
    el broadcast, que es la peor forma de romperse'. Absent env -> ValueError
    with the reason, never a packet to nowhere."""
    monkeypatch.setattr(wake_mak, "MAC_WIFI_MAK", "")
    monkeypatch.setattr(wake_mak.socket, "socket",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("no socket without a MAC")))
    with pytest.raises(ValueError, match="MAC_WIFI_MAK"):
        wake_mak.despertar()


def test_despertar_manda_broadcast_a_los_puertos_9_y_7(monkeypatch):
    FakeSocket.enviados, FakeSocket.opciones = [], []
    FakeSocket.cerrado = False
    monkeypatch.setattr(wake_mak.socket, "socket", FakeSocket)
    n = wake_mak.despertar("aa:bb:cc:dd:ee:ff")
    assert n == 2
    destinos = [d for _, d in FakeSocket.enviados]
    assert destinos == [("255.255.255.255", 9), ("255.255.255.255", 7)]
    assert all(datos == wake_mak._magic("aa:bb:cc:dd:ee:ff")
               for datos, _ in FakeSocket.enviados)
    assert FakeSocket.cerrado, "the socket is closed even on success"
    assert any(o[-1] == 1 for o in FakeSocket.opciones), "SO_BROADCAST is set"


def test_ruta_wake_reporta_el_error_como_500_json(monkeypatch):
    monkeypatch.setattr(wake_mak, "MAC_WIFI_MAK", "")
    cliente = _app(wake_mak.bp)
    r = cliente.get("/wake_mak/wake")
    assert r.status_code == 500
    cuerpo = r.get_json()
    assert cuerpo["ok"] is False and "MAC_WIFI_MAK" in cuerpo["error"]


def test_ruta_status_es_solo_informativa(monkeypatch):
    """GET /status must not send anything: it reports the plan, not executes it."""
    monkeypatch.setattr(wake_mak.socket, "socket",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("status must not open sockets")))
    r = _app(wake_mak.bp).get("/wake_mak/status")
    assert r.status_code == 200
    assert r.get_json()["plugin"] == "wake_mak"


# ----------------------------------------------------------------- mak_link

def test_mak_link_ping_responde_ok_y_declara_su_destino():
    r = _app(mak_link.bp).get("/mak_link/ping")
    assert r.status_code == 200
    cuerpo = r.get_json()
    assert cuerpo["ok"] is True
    assert cuerpo["destino"] == mak_link.MAK_HUB


def test_mak_link_no_expone_rutas_de_escritura():
    """The phone-facing surface is GET /ping and nothing else; the push runs
    the other way (phone -> MAK) in a thread the user starts on purpose."""
    reglas = [r for r in _app(mak_link.bp).application.url_map.iter_rules()
              if r.rule.startswith("/mak_link")]
    assert [r.rule for r in reglas] == ["/mak_link/ping"]
    metodos = set().union(*(r.methods for r in reglas)) - {"HEAD", "OPTIONS"}
    assert metodos == {"GET"}


def test_mak_link_push_es_opt_in_no_arranca_al_importar():
    """Importing the plugin must not start the reporting thread: the docstring
    says iniciar_push() is called from the plugin registry 'si se quiere'."""
    import threading
    activos = [t.name for t in threading.enumerate()]
    assert not any("_reportar" in n for n in activos)
    # And the thread it would start is a daemon: it cannot pin the server open.
    creado = {}
    monkeypatched = threading.Thread

    class FakeThread(monkeypatched):
        def start(self):  # record instead of running the infinite loop
            creado["daemon"] = self.daemon

    mak_link.threading.Thread, original = FakeThread, mak_link.threading.Thread
    try:
        mak_link.iniciar_push()
    finally:
        mak_link.threading.Thread = original
    assert creado == {"daemon": True}
