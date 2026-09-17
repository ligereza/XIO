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
