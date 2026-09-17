"""
NOTA DE PRIVACIDAD (2026-07-27, hallazgo VCD-08 del diagnostico de seguridad):
este fixture tenia BSSID y SSID de un escaneo REAL -- redes de vecinos, en un
repo publico. Un BSSID se resuelve a coordenadas en bases publicas de
wardriving, asi que eso ubicaba la casa del usuario y exponia datos de terceros
que nunca dieron permiso.

Ahora son ficticios y se nota que lo son: las MAC empiezan con 02:, el bit de
"localmente administrada", que no se asigna a hardware real. El test mide el
PARSEO del formato columnar, asi que los valores no importan; que sean reales,
si.
"""
"""
Off-device tests for xio/new-plugins/wifi_intelligence/__init__.py (pieza
MANIFIESTO #5 -- "WiFi Intelligence", registered previously as "parcial:
plugin sin tests").

This plugin normally runs inside the xio server on an Android/Termux device
(it shells out to `dumpsys wifi`, `cmd wifi ...`, `ip route`, `svc wifi ...`).
These tests never touch a device: the shared PluginContext/controller are
faked, following the same offline pattern already used by
tests/test_showcontrol_token.py -- boot the real plugin against a stub
PluginContext, wire its routes into a throwaway Flask app via
plugin.get_routes(), and drive it with Flask's test client. `controller._shell`
is replaced by a FakeController that returns canned text keyed by the leading
args, so every parsing/branching path exercised here is pure-Python logic the
plugin itself defines (regexes, signal math, history bookkeeping, request
validation) -- never a guess about real `dumpsys`/`cmd wifi` output shapes
beyond what the plugin's own regexes already assume.

    py -m pytest tests/test_wifi_intelligence_plugin.py -q

Device-only (NOT covered here, cannot be covered without real hardware):
    - Whether `dumpsys wifi` / `cmd wifi list-scan-results` / `ip route` on a
      real Android/Termux target actually produce lines matching the
      plugin's regexes (the plugin's own scan-result parsing looks for
      "SSID:" and "signal:" on the SAME line, which is unverified against a
      real device -- flagged, not fixed, per task instructions).
    - `shlex.quote()` behavior feeding into a real shell via `controller._shell`.
    - The background scheduler thread (`context.schedule`) actually firing
      `_background_poll` on a timer; here `_background_poll` is called
      directly, not through the scheduler.
"""

import logging
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_XIO_NEW = _REPO_ROOT / "xio" / "new"                    # importable `plugins` package
_XIO_NEW_PLUGINS = _REPO_ROOT / "xio" / "new-plugins"     # importable `wifi_intelligence` package
for _p in (str(_XIO_NEW), str(_XIO_NEW_PLUGINS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

pytest.importorskip("flask")  # xio/new/requirements.txt, not a core flujo dependency

from flask import Flask  # noqa: E402
from plugins.base import PluginContext  # noqa: E402
import wifi_intelligence  # noqa: E402


class FakeController:
    """Stand-in for XiaomiController._shell. Returns canned text keyed by
    the leading positional args (prefix match), records every call made."""

    def __init__(self, responses=None, raises_on=None):
        self.responses = responses or {}
        self.raises_on = raises_on or {}
        self.calls = []

    def _shell(self, *args):
        self.calls.append(args)
        for prefix, exc in self.raises_on.items():
            if args[: len(prefix)] == prefix:
                raise exc
        for prefix, text in self.responses.items():
            if args[: len(prefix)] == prefix:
                return text
        return ""


DUMPSYS_WIFI_CONNECTED = """\
Wi-Fi is enabled
mNetworkInfo SSID: "HomeNet", BSSID: aa:bb:cc:dd:ee:ff
RSSI: -55
Link speed: 130
Frequency: 5180
"""

IP_ROUTE_WITH_SRC = """\
default via 192.168.1.1 dev wlan0
192.168.1.0/24 dev wlan0 proto kernel scope link src 192.168.1.50
"""

SCAN_RESULTS_TEXT = """\
SSID: "NetworkA" signal: -40 freq: 5180
garbage line no match
SSID: "NetworkB" signal: -70 freq: 2412
SSID: "NetworkC"
"""

# Salida REAL de `cmd wifi list-scan-results` capturada en vivo del Xiaomi
# (HyperOS, 2026-07-18) -- formato columnar, NO el legado "SSID:"/"signal:".
SCAN_RESULTS_COLUMNAR = """\
    BSSID              Frequency      RSSI           Age(sec)     SSID                                 Flags
  02:00:00:00:00:01       2432    -84(0:-88/1:-86)     1.919    RED-EAP-EJEMPLO                   [WPA2-EAP/SHA1-CCMP][RSN-EAP/SHA1-CCMP][ESS][MFPC]
  02:00:00:00:00:02       2412    -77(0:-84/1:-78)     8.504    RED-VECINA-1                      [WPA2-PSK-CCMP][RSN-PSK-CCMP][ESS][WPS]
  02:00:00:00:00:03       2432    -68(0:-71/1:-71)     1.878    RED-VECINA-2                      [WPA2-PSK-CCMP][RSN-PSK-CCMP][ESS][WPS]
  02:00:00:00:00:04       2437    -76(0:-85/1:-77)     7.832    RED-VECINA-3                      [WPA2-PSK-CCMP][RSN-PSK-CCMP][ESS][WPS]
"""


def make_plugin(tmp_path, controller=None, monkeypatch=None):
    ctx = PluginContext(
        controller=controller if controller is not None else FakeController(),
        logger=logging.getLogger("test-wifi-intelligence"),
        data_dir=tmp_path / "data",
    )
    # on_load() calls context.schedule("wifi_poll", self._background_poll,
    # interval_seconds=60) -- the real PluginContext.schedule spawns a daemon
    # thread that fires _background_poll IMMEDIATELY (loop body runs once
    # before its first sleep). That races with every assertion these tests
    # make about _known_networks/_signal_history/networks.json. We test
    # _background_poll directly and deterministically instead, so the
    # scheduler itself is stubbed to a no-op recorder -- this is the only way
    # to make on_load() side-effect-free without a real device/timer.
    scheduled = []
    ctx.schedule = lambda name, func, interval_seconds: scheduled.append(
        (name, func, interval_seconds)
    )
    plugin = wifi_intelligence.WiFiIntelligencePlugin(ctx)
    plugin._scheduled_calls = scheduled  # exposed for tests that care
    if monkeypatch is not None:
        # never actually sleep 3s during _api_scan (the plugin does a local
        # `import time` inside _api_scan, which resolves to the same
        # sys.modules['time'] object -- patching the global works either way)
        monkeypatch.setattr("time.sleep", lambda s: None)
    plugin.on_load()
    return plugin


@pytest.fixture
def flask_app(tmp_path, monkeypatch):
    controller = FakeController(
        responses={
            ("dumpsys", "wifi"): DUMPSYS_WIFI_CONNECTED,
            ("ip", "route"): IP_ROUTE_WITH_SRC,
            ("cmd", "wifi", "list-scan-results"): SCAN_RESULTS_TEXT,
        }
    )
    plugin = make_plugin(tmp_path, controller=controller, monkeypatch=monkeypatch)
    app = Flask(__name__)
    for route in plugin.get_routes():
        app.add_url_rule(
            route["rule"],
            endpoint=route["endpoint"],
            view_func=route["view_func"],
            methods=route["methods"],
        )
    app.config["plugin"] = plugin
    app.config["controller"] = controller
    try:
        yield app
    finally:
        plugin.on_unload()


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


# ── Metadata / registration ──────────────────────────────────────────────

def test_plugin_metadata():
    assert wifi_intelligence.WiFiIntelligencePlugin.plugin_id == "wifi_intelligence"
    assert wifi_intelligence.WiFiIntelligencePlugin.name == "WiFi Intelligence"
    assert wifi_intelligence.WiFiIntelligencePlugin.category == "network"
    assert wifi_intelligence.WiFiIntelligencePlugin.permissions == ["network", "system"]
    assert wifi_intelligence.plugin_class is wifi_intelligence.WiFiIntelligencePlugin


def test_on_load_registers_expected_routes(tmp_path, monkeypatch):
    plugin = make_plugin(tmp_path, monkeypatch=monkeypatch)
    rules = {r["rule"] for r in plugin.get_routes()}
    assert rules == {
        "/api/plugins/wifi_intelligence/status",
        "/api/plugins/wifi_intelligence/scan",
        "/api/plugins/wifi_intelligence/known",
        "/api/plugins/wifi_intelligence/signal",
        "/api/plugins/wifi_intelligence/security",
        "/api/plugins/wifi_intelligence/toggle",
        "/api/plugins/wifi_intelligence/connect",
        "/api/plugins/wifi_intelligence/forget",
    }
    plugin.on_unload()


def test_on_load_schedules_background_poll(tmp_path, monkeypatch):
    plugin = make_plugin(tmp_path, monkeypatch=monkeypatch)
    assert len(plugin._scheduled_calls) == 1
    name, func, interval = plugin._scheduled_calls[0]
    assert name == "wifi_poll"
    assert func == plugin._background_poll
    assert interval == 60
    plugin.on_unload()


def test_to_manifest_reports_metadata(tmp_path, monkeypatch):
    plugin = make_plugin(tmp_path, monkeypatch=monkeypatch)
    manifest = plugin.to_manifest()
    assert manifest["id"] == "wifi_intelligence"
    assert manifest["category"] == "network"
    assert len(manifest["routes"]) == 8
    plugin.on_unload()


# ── _signal_quality (pure function) ──────────────────────────────────────

@pytest.mark.parametrize(
    "dbm,expected",
    [
        (-40, 100),   # above ceiling -> clamped 100
        (-50, 100),   # exactly ceiling
        (-100, 0),    # exactly floor
        (-120, 0),    # below floor -> clamped 0
        (-75, 50),    # midpoint: 2 * (-75 + 100) = 50
        (-90, 20),
    ],
)
def test_signal_quality(tmp_path, monkeypatch, dbm, expected):
    plugin = make_plugin(tmp_path, monkeypatch=monkeypatch)
    assert plugin._signal_quality(dbm) == expected
    plugin.on_unload()


# ── _get_wifi_info parsing ────────────────────────────────────────────────

def test_get_wifi_info_parses_dumpsys_and_route(tmp_path, monkeypatch):
    controller = FakeController(
        responses={
            ("dumpsys", "wifi"): DUMPSYS_WIFI_CONNECTED,
            ("ip", "route"): IP_ROUTE_WITH_SRC,
        }
    )
    plugin = make_plugin(tmp_path, controller=controller, monkeypatch=monkeypatch)
    info = plugin._get_wifi_info()
    assert info["enabled"] is True
    assert info["connected"] is True
    assert info["ssid"] == "HomeNet"
    assert info["signal_dbm"] == -55
    assert info["link_speed"] == 130
    assert info["frequency"] == 5180
    assert info["ip"] == "192.168.1.50"
    plugin.on_unload()


def test_get_wifi_info_disabled_no_ssid(tmp_path, monkeypatch):
    controller = FakeController(
        responses={
            ("dumpsys", "wifi"): "Wi-Fi is disabled\n",
            ("ip", "route"): "",
        }
    )
    plugin = make_plugin(tmp_path, controller=controller, monkeypatch=monkeypatch)
    info = plugin._get_wifi_info()
    assert info["enabled"] is False
    assert info["connected"] is False
    assert info["ssid"] == ""
    assert info["ip"] == ""
    plugin.on_unload()


def test_get_wifi_info_ip_route_exception_is_swallowed(tmp_path, monkeypatch):
    controller = FakeController(
        responses={("dumpsys", "wifi"): DUMPSYS_WIFI_CONNECTED},
        raises_on={("ip", "route"): RuntimeError("no route cmd")},
    )
    plugin = make_plugin(tmp_path, controller=controller, monkeypatch=monkeypatch)
    info = plugin._get_wifi_info()
    # ssid parsing still succeeded, ip stays empty instead of crashing
    assert info["ssid"] == "HomeNet"
    assert info["ip"] == ""
    plugin.on_unload()


def test_get_wifi_info_shell_exception_returns_empty_dict(tmp_path, monkeypatch):
    controller = FakeController(raises_on={("dumpsys", "wifi"): RuntimeError("adb gone")})
    plugin = make_plugin(tmp_path, controller=controller, monkeypatch=monkeypatch)
    assert plugin._get_wifi_info() == {}
    plugin.on_unload()


# ── _background_poll (history + known networks bookkeeping) ─────────────

def test_background_poll_adds_new_known_network_and_history(tmp_path, monkeypatch):
    controller = FakeController(
        responses={
            ("dumpsys", "wifi"): DUMPSYS_WIFI_CONNECTED,
            ("ip", "route"): IP_ROUTE_WITH_SRC,
        }
    )
    plugin = make_plugin(tmp_path, controller=controller, monkeypatch=monkeypatch)
    assert plugin._known_networks == []
    assert plugin._signal_history == []

    plugin._background_poll()

    assert len(plugin._signal_history) == 1
    assert plugin._signal_history[0]["ssid"] == "HomeNet"
    assert plugin._signal_history[0]["signal_dbm"] == -55

    assert len(plugin._known_networks) == 1
    net = plugin._known_networks[0]
    assert net["ssid"] == "HomeNet"
    assert net["connections"] == 1
    assert net["first_seen"] == net["last_seen"]

    # persisted to disk
    saved = (plugin.data_dir / "networks.json")
    assert saved.exists()
    plugin.on_unload()


def test_background_poll_existing_network_increments_connections(tmp_path, monkeypatch):
    controller = FakeController(
        responses={
            ("dumpsys", "wifi"): DUMPSYS_WIFI_CONNECTED,
            ("ip", "route"): IP_ROUTE_WITH_SRC,
        }
    )
    plugin = make_plugin(tmp_path, controller=controller, monkeypatch=monkeypatch)
    plugin._background_poll()
    plugin._background_poll()
    plugin._background_poll()

    assert len(plugin._known_networks) == 1  # still one distinct SSID
    assert plugin._known_networks[0]["connections"] == 3
    assert len(plugin._signal_history) == 3
    plugin.on_unload()


def test_background_poll_not_connected_is_noop(tmp_path, monkeypatch):
    controller = FakeController(
        responses={
            ("dumpsys", "wifi"): "Wi-Fi is enabled\n",  # no SSID line -> not connected
            ("ip", "route"): "",
        }
    )
    plugin = make_plugin(tmp_path, controller=controller, monkeypatch=monkeypatch)
    plugin._background_poll()
    assert plugin._known_networks == []
    assert plugin._signal_history == []
    plugin.on_unload()


def test_background_poll_history_capped_at_1440(tmp_path, monkeypatch):
    controller = FakeController(
        responses={
            ("dumpsys", "wifi"): DUMPSYS_WIFI_CONNECTED,
            ("ip", "route"): IP_ROUTE_WITH_SRC,
        }
    )
    plugin = make_plugin(tmp_path, controller=controller, monkeypatch=monkeypatch)
    plugin._signal_history = [{"timestamp": "t", "ssid": "old", "signal_dbm": -1}] * 1440
    plugin._background_poll()
    assert len(plugin._signal_history) == 1440
    assert plugin._signal_history[-1]["ssid"] == "HomeNet"  # newest entry kept
    plugin.on_unload()


def test_background_poll_swallows_get_wifi_info_exception(tmp_path, monkeypatch):
    controller = FakeController(raises_on={("dumpsys", "wifi"): RuntimeError("boom")})
    plugin = make_plugin(tmp_path, controller=controller, monkeypatch=monkeypatch)
    plugin._background_poll()  # must not raise
    assert plugin._known_networks == []
    plugin.on_unload()


def test_load_data_survives_corrupt_networks_json(tmp_path, monkeypatch):
    controller = FakeController()
    ctx = PluginContext(
        controller=controller,
        logger=logging.getLogger("test-wifi-intelligence"),
        data_dir=tmp_path / "data",
    )
    plugin = wifi_intelligence.WiFiIntelligencePlugin(ctx)
    monkeypatch.setattr("time.sleep", lambda s: None)
    plugin.data_dir.mkdir(parents=True, exist_ok=True)
    (plugin.data_dir / "networks.json").write_text("{not valid json")
    plugin.on_load()  # calls _load_data(); must not raise
    assert plugin._known_networks == []
    plugin.on_unload()


# ── /status ────────────────────────────────────────────────────────────

def test_api_status_connected_includes_quality(client):
    r = client.get("/api/plugins/wifi_intelligence/status")
    assert r.status_code == 200
    body = r.get_json()
    assert body["ssid"] == "HomeNet"
    assert body["quality"] == 90  # 2 * (-55 + 100)


def test_api_status_no_signal_omits_quality(tmp_path, monkeypatch):
    controller = FakeController(
        responses={("dumpsys", "wifi"): "Wi-Fi is enabled\n", ("ip", "route"): ""}
    )
    plugin = make_plugin(tmp_path, controller=controller, monkeypatch=monkeypatch)
    app = Flask(__name__)
    for route in plugin.get_routes():
        app.add_url_rule(route["rule"], endpoint=route["endpoint"],
                          view_func=route["view_func"], methods=route["methods"])
    client = app.test_client()
    r = client.get("/api/plugins/wifi_intelligence/status")
    assert r.status_code == 200
    assert "quality" not in r.get_json()
    plugin.on_unload()


# ── /scan ──────────────────────────────────────────────────────────────

def test_api_scan_parses_ssid_and_signal(client):
    r = client.get("/api/plugins/wifi_intelligence/scan")
    assert r.status_code == 200
    body = r.get_json()
    ssids = {n["ssid"]: n.get("signal") for n in body}
    assert ssids["NetworkA"] == -40
    assert ssids["NetworkB"] == -70
    assert ssids["NetworkC"] is None  # matched SSID, no signal on that line
    assert len(body) == 3  # garbage line produced no entry


def test_parse_scan_results_columnar_real_device():
    """Fixture = salida literal del Xiaomi (2026-07-18). El formato columnar
    es el REAL; el legado SSID:/signal: se conserva como fallback."""
    nets = wifi_intelligence.parse_scan_results(SCAN_RESULTS_COLUMNAR)
    assert len(nets) == 4  # header no produce entrada
    por_ssid = {n["ssid"]: n for n in nets}
    assert por_ssid["RED-VECINA-1"]["signal"] == -77
    assert por_ssid["RED-VECINA-1"]["frequency"] == 2412
    assert por_ssid["RED-VECINA-1"]["bssid"] == "02:00:00:00:00:02"
    assert por_ssid["RED-VECINA-3"]["signal"] == -76
    assert "[WPA2-PSK-CCMP]" in por_ssid["RED-VECINA-2"]["flags"]
    # el SSID largo tipo hash tambien parsea entero
    assert "RED-EAP-EJEMPLO" in por_ssid


def test_parse_scan_results_legacy_still_supported():
    nets = wifi_intelligence.parse_scan_results(SCAN_RESULTS_TEXT)
    assert {n["ssid"] for n in nets} == {"NetworkA", "NetworkB", "NetworkC"}


def test_api_scan_columnar_via_route(tmp_path, monkeypatch):
    controller = FakeController(responses={
        ("cmd", "wifi", "start-scan"): "",
        ("cmd", "wifi", "list-scan-results"): SCAN_RESULTS_COLUMNAR,
    })
    plugin = make_plugin(tmp_path, controller=controller, monkeypatch=monkeypatch)
    app = Flask(__name__)
    for route in plugin.get_routes():
        app.add_url_rule(route["rule"], endpoint=route["endpoint"],
                          view_func=route["view_func"], methods=route["methods"])
    client = app.test_client()
    r = client.get("/api/plugins/wifi_intelligence/scan")
    assert r.status_code == 200
    body = r.get_json()
    assert len(body) == 4
    assert {n["ssid"] for n in body} >= {"RED-VECINA-1", "RED-VECINA-2", "RED-VECINA-3"}
    plugin.on_unload()


def test_api_scan_shell_exception_returns_error_payload(tmp_path, monkeypatch):
    controller = FakeController(raises_on={("cmd", "wifi", "start-scan"): RuntimeError("no wifi cmd")})
    plugin = make_plugin(tmp_path, controller=controller, monkeypatch=monkeypatch)
    app = Flask(__name__)
    for route in plugin.get_routes():
        app.add_url_rule(route["rule"], endpoint=route["endpoint"],
                          view_func=route["view_func"], methods=route["methods"])
    client = app.test_client()
    r = client.get("/api/plugins/wifi_intelligence/scan")
    assert r.status_code == 200
    assert "error" in r.get_json()
    plugin.on_unload()


# ── /known ─────────────────────────────────────────────────────────────

def test_api_known_reflects_state(client, flask_app):
    plugin = flask_app.config["plugin"]
    plugin._known_networks = [{"ssid": "X", "connections": 5}]
    r = client.get("/api/plugins/wifi_intelligence/known")
    assert r.status_code == 200
    assert r.get_json() == [{"ssid": "X", "connections": 5}]


# ── /signal ────────────────────────────────────────────────────────────

def test_api_signal_empty_history_defaults(client):
    r = client.get("/api/plugins/wifi_intelligence/signal")
    assert r.status_code == 200
    body = r.get_json()
    assert body["history"] == []
    assert body["current_signal"] == 0
    assert body["avg_signal"] == 0
    assert body["band"] == "2.4GHz"


def test_api_signal_with_history_computes_avg_and_band(client, flask_app):
    plugin = flask_app.config["plugin"]
    plugin._signal_history = [
        {"timestamp": "t1", "ssid": "A", "signal_dbm": -40, "frequency": 5180},
        {"timestamp": "t2", "ssid": "A", "signal_dbm": -60, "frequency": 5180},
    ]
    r = client.get("/api/plugins/wifi_intelligence/signal?minutes=60")
    body = r.get_json()
    assert body["current_signal"] == -60
    assert body["avg_signal"] == -50
    assert body["band"] == "5GHz"


def test_api_signal_minutes_param_limits_window(client, flask_app):
    plugin = flask_app.config["plugin"]
    plugin._signal_history = [
        {"timestamp": f"t{i}", "ssid": "A", "signal_dbm": -50 - i, "frequency": 2400}
        for i in range(5)
    ]
    r = client.get("/api/plugins/wifi_intelligence/signal?minutes=2")
    body = r.get_json()
    assert len(body["history"]) == 2
    assert body["history"] == plugin._signal_history[-2:]


# ── /security ──────────────────────────────────────────────────────────

def test_api_security_audit_not_connected(tmp_path, monkeypatch):
    controller = FakeController(
        responses={("dumpsys", "wifi"): "Wi-Fi is enabled\n", ("ip", "route"): ""}
    )
    plugin = make_plugin(tmp_path, controller=controller, monkeypatch=monkeypatch)
    app = Flask(__name__)
    for route in plugin.get_routes():
        app.add_url_rule(route["rule"], endpoint=route["endpoint"],
                          view_func=route["view_func"], methods=route["methods"])
    client = app.test_client()
    r = client.get("/api/plugins/wifi_intelligence/security")
    assert r.status_code == 200
    assert r.get_json() == {"connected": False, "issues": []}
    plugin.on_unload()


def test_api_security_audit_weak_signal_and_2ghz(tmp_path, monkeypatch):
    dumpsys = """\
Wi-Fi is enabled
SSID: "WeakNet"
RSSI: -85
Frequency: 2437
"""
    controller = FakeController(responses={("dumpsys", "wifi"): dumpsys, ("ip", "route"): ""})
    plugin = make_plugin(tmp_path, controller=controller, monkeypatch=monkeypatch)
    app = Flask(__name__)
    for route in plugin.get_routes():
        app.add_url_rule(route["rule"], endpoint=route["endpoint"],
                          view_func=route["view_func"], methods=route["methods"])
    client = app.test_client()
    r = client.get("/api/plugins/wifi_intelligence/security")
    body = r.get_json()
    assert body["connected"] is True
    types = {i["type"] for i in body["issues"]}
    assert types == {"weak_signal", "2ghz_band"}
    assert body["score"] == 50  # 100 - 2*25
    plugin.on_unload()


def test_api_security_audit_good_connection_no_issues(client):
    r = client.get("/api/plugins/wifi_intelligence/security")
    body = r.get_json()
    assert body["connected"] is True
    assert body["issues"] == []
    assert body["score"] == 100


# ── /toggle ────────────────────────────────────────────────────────────

def test_api_toggle_on_calls_svc_enable(client, flask_app):
    controller = flask_app.config["controller"]
    r = client.post("/api/plugins/wifi_intelligence/toggle", json={"state": "on"})
    assert r.status_code == 200
    assert r.get_json() == {"ok": True}
    assert ("svc", "wifi", "enable") in controller.calls


def test_api_toggle_off_calls_svc_disable(client, flask_app):
    controller = flask_app.config["controller"]
    r = client.post("/api/plugins/wifi_intelligence/toggle", json={"state": False})
    assert r.status_code == 200
    assert ("svc", "wifi", "disable") in controller.calls


def test_api_toggle_missing_state_no_shell_call(client, flask_app):
    controller = flask_app.config["controller"]
    before = len(controller.calls)
    r = client.post("/api/plugins/wifi_intelligence/toggle", json={})
    assert r.status_code == 200
    assert r.get_json() == {"ok": True}
    assert len(controller.calls) == before


# ── /connect ───────────────────────────────────────────────────────────

def test_api_connect_valid_ssid(client, flask_app):
    controller = flask_app.config["controller"]
    r = client.post("/api/plugins/wifi_intelligence/connect", json={"ssid": "HomeNet"})
    assert r.status_code == 200
    assert r.get_json() == {"ok": True}
    assert any(c[:2] == ("cmd", "wifi") and c[2] == "connect-network" for c in controller.calls)


def test_api_connect_missing_ssid_rejected(client):
    r = client.post("/api/plugins/wifi_intelligence/connect", json={"ssid": ""})
    assert r.status_code == 400
    assert r.get_json()["ok"] is False


def test_api_connect_ssid_too_long_rejected(client):
    long_ssid = "x" * 33  # over the 32-byte SSID limit
    r = client.post("/api/plugins/wifi_intelligence/connect", json={"ssid": long_ssid})
    assert r.status_code == 400


def test_api_connect_non_string_ssid_rejected(client):
    r = client.post("/api/plugins/wifi_intelligence/connect", json={"ssid": 12345})
    assert r.status_code == 400


# ── /forget ────────────────────────────────────────────────────────────

def test_api_forget_valid_ssid(client, flask_app):
    controller = flask_app.config["controller"]
    r = client.post("/api/plugins/wifi_intelligence/forget", json={"ssid": "HomeNet"})
    assert r.status_code == 200
    assert r.get_json() == {"ok": True}
    assert any(c[:2] == ("cmd", "wifi") and c[2] == "forget-network" for c in controller.calls)


def test_api_forget_missing_ssid_rejected(client):
    r = client.post("/api/plugins/wifi_intelligence/forget", json={})
    assert r.status_code == 400
