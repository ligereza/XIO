"""Gates para evitar que la IP cambiante del hotspot vuelva a entrar al kit."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "xio" / "show_kit"))
import discover_xio as D  # noqa: E402


def assert_true(value, message):
    if not value:
        raise AssertionError(message)


def walk_remote_hosts(value, found):
    if isinstance(value, dict):
        if value.get("controlAddress") == "/remoteHost" and "value" in value:
            found.append(value["value"])
        for key, item in value.items():
            if key == "remoteHost":
                found.append(item)
            walk_remote_hosts(item, found)
    elif isinstance(value, list):
        for item in value:
            walk_remote_hosts(item, found)


def main():
    route_text = """
===========================================================================
IPv4 Route Table
Network Destination        Netmask          Gateway       Interface  Metric
          0.0.0.0          0.0.0.0    10.248.64.39    10.248.64.20     25
          0.0.0.0          0.0.0.0    192.168.1.1     192.168.1.50    500
"""
    routes = D.parse_route_print(route_text)
    assert_true([x[0] for x in routes] == ["10.248.64.39", "192.168.1.1"],
                "parseo de gateways Windows incorrecto")
    linux = D.parse_ip_route("default via 10.248.64.39 dev wlan0 proto dhcp\n")
    assert_true(linux[0][:2] == ("10.248.64.39", "wlan0"),
                "parseo de gateway Linux incorrecto")

    old_probe = D.probe
    old_routes = D.route_candidates
    old_env = os.environ.get("XIO_HOST")
    try:
        os.environ["XIO_HOST"] = "10.9.9.9"  # stale value must not block discovery
        D.route_candidates = lambda: [
            ("10.248.64.39", "Wi-Fi", "test"),
            ("192.168.1.1", "Ethernet", "test"),
        ]
        D.probe = lambda host, **kwargs: (
            {"host": host, "port": 5000, "plugins": ["foh_monitor"]}
            if host == "10.248.64.39" else None
        )
        host, evidence = D.resolve_host()
        assert_true(host == "10.248.64.39", "no se eligio el gateway XIO actual")
        assert_true(evidence["source"] == "test", "se perdio evidencia de descubrimiento")
        assert_true(evidence["tried"] == ["10.9.9.9", "10.248.64.39"],
                    "no se registro la recuperacion desde XIO_HOST obsoleto")
    finally:
        D.probe = old_probe
        D.route_candidates = old_routes
        if old_env is not None:
            os.environ["XIO_HOST"] = old_env

    for name in ("festival_sentir.noisette", "dref_chocolate.noisette"):
        data = json.loads((ROOT / "xio" / "show_kit" / name).read_text(encoding="utf-8"))
        hosts = []
        walk_remote_hosts(data, hosts)
        assert_true(hosts, f"{name}: no se encontro remoteHost")
        assert_true(set(hosts) == {"255.255.255.255"},
                    f"{name}: remoteHost dejo de ser broadcast: {hosts}")

    private_ip = re.compile(r"\b(?:10|172|192)\.(?:\d{1,3}\.){2}\d{1,3}\b")
    for name in ("discover_xio.py", "check_show.py", "check_show.bat",
                 "cargar_setlist.bat", "relay_luces.bat", "artnet_relay.py"):
        raw = (ROOT / "xio" / "show_kit" / name).read_text(encoding="utf-8")
        assert_true(not private_ip.search(raw),
                    f"{name}: contiene una IP privada fija en codigo operativo")
    check_show = (ROOT / "xio" / "show_kit" / "check_show.py").read_text(encoding="utf-8")
    setlist = (ROOT / "xio" / "show_kit" / "cargar_setlist.bat").read_text(encoding="utf-8")
    assert_true("ProxyHandler({})" in check_show and "LOCAL_OPENER.open" in check_show,
                "check_show podria sacar el trafico local por un proxy")
    assert_true("ProxyHandler({})" in setlist,
                "cargar_setlist podria sacar el POST local por un proxy")

    faces = (ROOT / "xio" / "FACES.md").read_text(encoding="utf-8")
    for marker in (
        "CURRENT FIELD SURFACE CONTRACT",
        "FLUJO Hub | MAK `:8765`",
        "XIO field host",
        "XIO-RD",
        "XIO-FOH",
        "Art-Net `:6454`",
        "sACN `:5568`",
        "OSC/timecode `:7000`",
        "`127.0.0.1:8765`",
        "session state",
    ):
        assert_true(marker in faces, f"FACES.md: falta contrato vigente: {marker}")

    print("OK: discovery XIO por gateway y presets UDP sin IP fija")


if __name__ == "__main__":
    main()
