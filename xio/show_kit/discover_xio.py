# -*- coding: utf-8 -*-
"""Descubre el host HTTP actual de XIO sin guardar una IP del hotspot.

El Xiaomi es el gateway de la red que crea. Android puede cambiar la subred y
la IP en cada sesion, por eso este modulo prueba solo los gateways que el
equipo local conoce ahora y valida la respuesta real de XIO en :5000.

No hace un escaneo de la red, no cambia configuracion y no abre ningun puerto.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import platform
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_PORT = 5000
XIO_MARKERS = {"foh_monitor", "rd_field", "connectivity_supervisor"}


class DiscoveryError(RuntimeError):
    """La red local no expuso un XIO HTTP utilizable."""


def _run(command):
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3,
            check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _valid_gateway(value):
    try:
        addr = ipaddress.ip_address(value)
    except ValueError:
        return False
    return addr.version == 4 and not addr.is_unspecified and not addr.is_loopback


def _unique(items):
    seen = set()
    result = []
    for item in items:
        if not item or item[0] in seen:
            continue
        seen.add(item[0])
        result.append(item)
    return result


def parse_route_print(text):
    """Parsea las rutas por defecto de `route print -4` (Windows)."""
    result = []
    for line in text.splitlines():
        fields = line.split()
        # Network Destination, Netmask, Gateway, Interface, Metric
        if len(fields) < 4 or fields[0] != "0.0.0.0" or fields[1] != "0.0.0.0":
            continue
        gateway, interface = fields[2], fields[3]
        if _valid_gateway(gateway):
            result.append((gateway, interface, "route print"))
    return _unique(result)


def parse_ip_route(text):
    """Parsea `ip -4 route` (Linux/Termux y tambien sirve para diagnostico)."""
    result = []
    for line in text.splitlines():
        fields = line.split()
        if not fields or fields[0] != "default":
            continue
        gateway = ""
        interface = ""
        if "via" in fields:
            i = fields.index("via")
            if i + 1 < len(fields):
                gateway = fields[i + 1]
        if "dev" in fields:
            i = fields.index("dev")
            if i + 1 < len(fields):
                interface = fields[i + 1]
        if _valid_gateway(gateway):
            result.append((gateway, interface, "ip route"))
    return _unique(result)


def route_candidates():
    """Devuelve gateways actuales, en el orden que entrega el sistema."""
    candidates = []
    env_gateway = os.environ.get("XIO_GATEWAY", "").strip()
    if _valid_gateway(env_gateway):
        candidates.append((env_gateway, "", "XIO_GATEWAY"))

    if platform.system().lower().startswith("win"):
        candidates.extend(parse_route_print(_run(["route", "print", "-4"])))
    else:
        candidates.extend(parse_ip_route(_run(["ip", "-4", "route", "show"])))
        # Fallback diagnostico si `ip` no esta disponible.
        candidates.extend(parse_route_print(_run(["route", "-n"])))
    return _unique(candidates)


def _host_from_value(value):
    value = str(value or "").strip()
    if not value:
        return ""
    if "://" in value:
        parsed = urllib.parse.urlparse(value)
        value = parsed.hostname or ""
    value = value.split("/", 1)[0].strip()
    if ":" in value and value.count(":") == 1:
        value = value.rsplit(":", 1)[0]
    return value


def probe(host, port=DEFAULT_PORT, timeout=1.25):
    """Valida que host:port sea el server XIO actual."""
    host = _host_from_value(host)
    if not host:
        return None
    url = f"http://{host}:{int(port)}/api/plugins"
    request = urllib.request.Request(url, headers={"Connection": "close"})
    # La red del hotspot es local; un proxy del sistema no debe desviar la
    # prueba hacia internet.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=timeout) as response:
            if response.status != 200:
                return None
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError):
        return None
    if not isinstance(payload, list):
        return None
    ids = {str(item.get("id")) for item in payload if isinstance(item, dict)}
    if not ids.intersection(XIO_MARKERS):
        return None
    return {"host": host, "port": int(port), "plugins": sorted(ids)}


def resolve_host(requested=None):
    """Resuelve `(host, evidencia)` usando argumento/env o gateways actuales."""
    cli_host = _host_from_value(requested)
    if cli_host:
        result = probe(cli_host)
        if result:
            return result["host"], {**result, "source": "explicit"}
        raise DiscoveryError(f"XIO no responde o no tiene plugins esperados en {cli_host}:5000")

    tried = []
    env_host = _host_from_value(os.environ.get("XIO_HOST", ""))
    if env_host:
        tried.append(env_host)
        result = probe(env_host)
        if result:
            return result["host"], {**result, "source": "XIO_HOST", "tried": tried}
        # XIO_HOST is a convenience override, not durable session state. If it
        # is stale, continue with the gateways advertised by this session.
    for gateway, interface, source in route_candidates():
        if gateway in tried:
            continue
        tried.append(gateway)
        result = probe(gateway)
        if result:
            return result["host"], {
                **result,
                "source": source,
                "interface": interface,
                "tried": tried,
            }
    detail = ", ".join(tried) if tried else "ningun gateway por defecto"
    raise DiscoveryError(
        "no encontre XIO en los gateways actuales ("
        + detail
        + "); conecta este equipo al hotspot y vuelve a probar"
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host", nargs="?", help="host actual; omitir para descubrirlo")
    parser.add_argument("--print-host", action="store_true", help="imprime solo el host descubierto")
    parser.add_argument("--json", action="store_true", help="imprime evidencia JSON")
    args = parser.parse_args(argv)
    try:
        host, evidence = resolve_host(args.host)
    except DiscoveryError as exc:
        print(f"XIO_DISCOVERY_ERROR: {exc}", file=sys.stderr)
        return 2
    if args.print_host:
        print(host)
    elif args.json:
        print(json.dumps(evidence, ensure_ascii=True))
    else:
        print(f"XIO_HOST={host} source={evidence.get('source')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
