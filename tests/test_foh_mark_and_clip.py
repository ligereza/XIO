# -*- coding: utf-8 -*-
"""The two things the FOH surface gained so it can read a show without timecode.

* `clip_trigger`: el address OSC de Resolume ya se parseaba y solo servia para
  prender el tile VISUAL. Su contenido -- capa y clip, lo unico que dice QUE se
  vio -- no se guardaba en ninguna parte.
* `POST /mark`: la distincion entre un tramo sin timecode que es CONTENIDO y
  uno que es FALLA no se puede reconstruir despues, y el 2026-07-24 hubo que
  aportarla de memoria tras el show.

Estas pruebas no levantan el server ni abren sockets: arman el plugin contra un
contexto de mentira, igual que `test_foh_monitor.py`.
"""

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "xio" / "new"))
sys.path.insert(0, str(ROOT / "xio" / "new-plugins"))

from foh_monitor import MARK_CLASSES, FohMonitorPlugin  # noqa: E402


def _osc_message(address, value="1"):
    address_bytes = address.encode() + b"\0"
    address_bytes += b"\0" * ((4 - len(address_bytes) % 4) % 4)
    tags = b",s\0\0"
    value_bytes = value.encode() + b"\0"
    value_bytes += b"\0" * ((4 - len(value_bytes) % 4) % 4)
    return address_bytes + tags + value_bytes


def _osc_bundle(*messages):
    return b"#bundle\0" + (b"\0" * 8) + b"".join(
        struct.pack(">I", len(message)) + message for message in messages)


def _plugin():
    plugin = FohMonitorPlugin.__new__(FohMonitorPlugin)
    plugin._cfg = lambda key: "/timecode" if key == "tc_address" else 30
    plugin._tc = {"value": None, "last_seen": 0.0, "last_change": 0.0, "total": 0}
    plugin._tc_buckets = {}
    plugin._auto_setlist_por_tc = lambda value: None
    plugin._clip_last = None
    plugin.logged = []
    plugin._log_event = lambda tipo, detalle, event_key=None: plugin.logged.append(
        (tipo, detalle))
    return plugin


def test_a_clip_trigger_is_recorded_with_its_layer_and_clip():
    plugin = _plugin()
    plugin._parse_osc_pkt(_osc_bundle(
        _osc_message("/composition/layers/2/clips/7/connect")))
    assert plugin.logged == [("clip_trigger", {
        "layer": 2, "clip": 7,
        "address": "/composition/layers/2/clips/7/connect"})]


def test_the_same_clip_repeated_is_logged_once():
    # Resolume manda muchos mensajes por segundo: si cada paquete escribiera una
    # linea, el registro del show seria ilegible y el JSONL enorme.
    plugin = _plugin()
    packet = _osc_bundle(_osc_message("/composition/layers/1/clips/1/connect"))
    for _ in range(50):
        plugin._parse_osc_pkt(packet)
    assert len(plugin.logged) == 1
    plugin._parse_osc_pkt(_osc_bundle(
        _osc_message("/composition/layers/1/clips/2/connect")))
    assert len(plugin.logged) == 2
    # Volver al clip anterior SI es un disparo nuevo.
    plugin._parse_osc_pkt(packet)
    assert len(plugin.logged) == 3


def test_an_osc_address_that_is_not_a_clip_trigger_records_nothing():
    plugin = _plugin()
    for address in ("/composition/layers/1/clips/1/name",
                    "/composition/master",
                    "/live/song/beat",
                    "/composition/layers/x/clips/y/connect"):
        plugin._parse_osc_pkt(_osc_bundle(_osc_message(address)))
    assert plugin.logged == []


def test_timecode_is_not_a_clip_trigger():
    # El canal de timecode tiene su propio camino y no debe ensuciar el registro
    # de clips (ni contar como actividad visual).
    plugin = _plugin()
    assert plugin._parse_osc_pkt(_osc_bundle(
        _osc_message("/timecode", "01:30:00:00"))) is False
    assert plugin.logged == []


def test_the_mark_classes_are_the_three_the_operator_can_tell_apart():
    assert MARK_CLASSES == ("contenido", "falla", "nota")


# ── de que maquina llega cada canal ──────────────────────────────────────


def _channel():
    from foh_monitor import _Channel
    return _Channel("osc")


def test_a_channel_remembers_which_machine_sends_it():
    channel = _channel()
    channel.hit("/composition/1/clip", "192.168.43.20")
    channel.hit("/composition/1/clip", "192.168.43.20")
    snapshot = channel.snapshot(5)
    assert snapshot["source"] == "192.168.43.20"
    assert snapshot["sources"] == {"192.168.43.20": 2}
    assert snapshot["source_changes"] == 0


def test_a_source_change_is_counted_because_it_breaks_a_show():
    # El 2026-07-24 el venue cambio la IP del telefono por DHCP. El mismo
    # fenomeno del otro lado -- el notebook toma IP nueva -- deja a Chataigne
    # mandando a una direccion que ya no existe.
    channel = _channel()
    channel.hit("x", "192.168.43.20")
    channel.hit("x", "192.168.43.77")
    snapshot = channel.snapshot(5)
    assert snapshot["source"] == "192.168.43.77"
    assert snapshot["source_changes"] == 1
    assert set(snapshot["sources"]) == {"192.168.43.20", "192.168.43.77"}


def test_a_channel_with_no_source_yet_reports_none_not_empty_text():
    snapshot = _channel().snapshot(5)
    assert snapshot["source"] is None
    assert snapshot["sources"] is None


# ── por que enlace se une a los grupos sACN ──────────────────────────────


def _plugin_with_interfaces(names, wanted=""):
    """Simula un aparato donde SOLO existen `names`, preguntando por nombre.

    Android no deja enumerar interfaces (`if_nameindex` levanta PermissionError
    desde Android 11) pero si deja resolver un nombre, asi que el codigo
    pregunta y esta prueba responde igual que el sistema.
    """
    import socket as _socket

    plugin = FohMonitorPlugin.__new__(FohMonitorPlugin)
    plugin._cfg = lambda key: wanted if key == "sacn_interface" else 30
    original_index = _socket.if_nametoindex
    original_list = getattr(_socket, "if_nameindex", None)

    def fake_index(name):
        if name in names:
            return names.index(name) + 1
        raise OSError("no such device")

    def fake_list():
        raise PermissionError(13, "Permission denied")

    _socket.if_nametoindex = fake_index
    _socket.if_nameindex = fake_list
    try:
        return plugin._multicast_interface()
    finally:
        _socket.if_nametoindex = original_index
        if original_list is None:
            del _socket.if_nameindex
        else:
            _socket.if_nameindex = original_list


def test_the_join_prefers_the_hotspot_link_over_the_default_route():
    # El defecto medido el 2026-09-17: unirse por la ruta por omision manda el
    # join a la red celular (rmnet_data2), donde no llega ningun sACN. Por la
    # ruta por omision, 12 paquetes multicast dieron cero; por wlan1, 12 de 12.
    assert _plugin_with_interfaces(["lo", "rmnet_data2", "wlan1"]) == "wlan1"


def test_the_link_is_asked_for_by_name_because_android_forbids_enumerating():
    # Con la enumeracion prohibida, preguntar por nombre sigue funcionando.
    assert _plugin_with_interfaces(["lo", "wlan1"]) == "wlan1"


def test_other_vendors_hotspot_names_are_tried_too():
    assert _plugin_with_interfaces(["lo", "rmnet_data2", "ap0"]) == "ap0"
    assert _plugin_with_interfaces(["lo", "swlan0"]) == "swlan0"


def test_the_client_wifi_is_the_last_resort_not_the_first():
    # wlan0 sirve, pero wlan1 (el AP) manda cuando los dos existen.
    assert _plugin_with_interfaces(["lo", "wlan0", "wlan1"]) == "wlan1"
    assert _plugin_with_interfaces(["lo", "wlan0"]) == "wlan0"


def test_without_a_wifi_link_it_returns_none_instead_of_guessing():
    assert _plugin_with_interfaces(["lo", "rmnet_data2"]) is None


def test_an_explicit_interface_is_honored_and_a_wrong_one_is_refused():
    assert _plugin_with_interfaces(["lo", "wlan1", "eth0"], wanted="eth0") == "eth0"
    # Pedir un enlace que no existe no cae de vuelta en otro cualquiera.
    assert _plugin_with_interfaces(["lo", "wlan1"], wanted="eth7") is None
