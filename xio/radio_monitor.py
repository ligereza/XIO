"""Lectura de telemetría de XIO desde el equipo Windows.

El monitor correlaciona tres superficies sin cambiar ninguna configuración:

* radio celular del Xiaomi mediante ``adb dumpsys telephony.registry``;
* enlace Wi-Fi Windows↔XIO mediante ``netsh wlan show interfaces``;
* camino local y camino móvil mediante ping al gateway y a Internet.

No ejecuta escaneos activos, no cambia la red preferida, no inicia una prueba
de velocidad y no guarda la salida cruda de ADB. Su objetivo es producir una
serie temporal pequeña que permita atribuir una caída a radio celular, enlace
Wi-Fi o ruta móvil, en vez de llamar "throttling" a cualquier síntoma.

Uso rápido en Windows::

    python xio/radio_monitor.py --once
    python xio/radio_monitor.py --interval 30

Los archivos persistentes se escriben en ``xio/data/radio_monitor`` por
defecto; esa carpeta está excluida del repositorio.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable


INVALID_ANDROID_METRICS = {2147483647, -2147483648}


def _first_match(pattern: str, text: str, flags: int = re.I | re.S) -> str | None:
    match = re.search(pattern, text, flags)
    return match.group(1).strip() if match else None


def _int_value(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return None if number in INVALID_ANDROID_METRICS else number


def _float_value(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value.replace(",", "."))
    except (TypeError, ValueError):
        return None


def _bool_value(value: str | None) -> bool | None:
    if value is None:
        return None
    return value.lower() == "true"


def _phone_zero_body(text: str) -> str:
    """Return the active Phone Id=0 block, ignoring the registry history."""

    match = re.search(
        r"^[ \t]*Phone Id=0[ \t]*\r?\n(?P<body>.*?)(?=^[ \t]*Phone Id=1[ \t]*$|^[ \t]*mPhoneCapability=)",
        text,
        re.I | re.M | re.S,
    )
    return match.group("body") if match else text


def _parse_service_state(body: str) -> dict[str, Any]:
    service = _first_match(
        r"mServiceState=\{(?P<state>.*?)(?=\r?\n[ \t]*mVoiceActivationState=)",
        body,
    ) or ""

    rat_match = re.search(
        r"getRilDataRadioTechnology=(\d+)\(([^)]+)\)", service, re.I
    )
    voice_rat_match = re.search(
        r"getRilVoiceRadioTechnology=(\d+)\(([^)]+)\)", service, re.I
    )
    bandwidths_raw = _first_match(r"mCellBandwidths=\[([^\]]*)\]", service)
    bandwidths_khz = []
    if bandwidths_raw:
        for raw in bandwidths_raw.split(","):
            value = _int_value(raw.strip())
            if value is not None:
                bandwidths_khz.append(value)

    registration = re.search(
        r"DataSpecificRegistrationInfo\s*:\s*\{(?P<info>.*?)\}", service,
        re.I | re.S,
    )
    registration_info = registration.group("info") if registration else ""

    return {
        "operator": _first_match(r"mOperatorAlphaLong=([^,}]*)", service),
        "channel": _int_value(_first_match(r"mChannelNumber=(-?\d+)", service)),
        "data_rat": rat_match.group(2) if rat_match else None,
        "data_rat_code": _int_value(rat_match.group(1)) if rat_match else None,
        "voice_rat": voice_rat_match.group(2) if voice_rat_match else None,
        "manual_network_selection": _bool_value(
            _first_match(r"isManualNetworkSelection=(true|false)", service)
        ),
        "roaming": _bool_value(
            _first_match(r"mIsDataRoamingFromRegistration=(true|false)", service)
        ),
        "carrier_aggregation": _bool_value(
            _first_match(r"isUsingCarrierAggregation=(true|false)", service)
        ),
        "bandwidths_khz": bandwidths_khz,
        "bandwidths_mhz": [round(value / 1000, 1) for value in bandwidths_khz],
        "nr_frequency_range": _int_value(
            _first_match(r"mNrFrequencyRange=(-?\d+)", service)
        ),
        "nr_available": _bool_value(
            _first_match(r"isNrAvailable\s*=\s*(true|false)", registration_info)
        ),
        "en_dc_available": _bool_value(
            _first_match(r"isEnDcAvailable\s*=\s*(true|false)", registration_info)
        ),
    }


def _parse_signal_strength(body: str) -> dict[str, Any]:
    signal = _first_match(
        r"mSignalStrength=SignalStrength:\{(?P<signal>.*?)(?=\r?\n[ \t]*mMessageWaiting=)",
        body,
    ) or ""
    lte = re.search(
        r"mLte=CellSignalStrengthLte:.*?\brsrp=(-?\d+).*?\brsrq=(-?\d+).*?\brssnr=(-?\d+)",
        signal,
        re.I | re.S,
    )
    nr = re.search(
        r"mNr=CellSignalStrengthNr:\{.*?csiRsrp\s*=\s*(-?\d+).*?"
        r"csiRsrq\s*=\s*(-?\d+).*?ssRsrp\s*=\s*(-?\d+).*?"
        r"ssRsrq\s*=\s*(-?\d+).*?ssSinr\s*=\s*(-?\d+)",
        signal,
        re.I | re.S,
    )
    return {
        "lte_rsrp_dbm": _int_value(lte.group(1)) if lte else None,
        "lte_rsrq_db": _int_value(lte.group(2)) if lte else None,
        "lte_snr_db": _int_value(lte.group(3)) if lte else None,
        "nr_csi_rsrp_dbm": _int_value(nr.group(1)) if nr else None,
        "nr_csi_rsrq_db": _int_value(nr.group(2)) if nr else None,
        "nr_ss_rsrp_dbm": _int_value(nr.group(3)) if nr else None,
        "nr_ss_rsrq_db": _int_value(nr.group(4)) if nr else None,
        "nr_ss_sinr_db": _int_value(nr.group(5)) if nr else None,
    }


def parse_telephony_registry(text: str) -> dict[str, Any]:
    """Parse the current cellular state from ``dumpsys telephony.registry``.

    Android prints a long event history after the current state. This function
    deliberately reads only the active ``Phone Id=0`` block, so an old 5G/CA
    event cannot be mistaken for the current connection.
    """

    body = _phone_zero_body(text)
    service = _parse_service_state(body)
    signal = _parse_signal_strength(body)

    # The config contains nested ``mContextIds=[...]``; matching the whole
    # bracketed object would stop too early. Read the scalar fields directly.
    physical_cell = _int_value(_first_match(r"mPhysicalCellId=(-?\d+)", body))
    physical_bandwidth = _int_value(
        _first_match(r"mCellBandwidthDownlinkKhz=(-?\d+)", body)
    )
    capacity = _first_match(r"mLinkCapacityEstimateList=\[(.*?)\]", body) or ""
    downlink = _int_value(_first_match(r"mDownlinkCapacityKbps=(-?\d+)", capacity))
    uplink = _int_value(_first_match(r"mUplinkCapacityKbps=(-?\d+)", capacity))

    result = {
        **service,
        **signal,
        "physical_cell_id": physical_cell,
        "physical_bandwidth_downlink_khz": physical_bandwidth,
        "estimated_downlink_kbps": downlink,
        "estimated_uplink_kbps": uplink,
    }
    result["registered_rat"] = result.get("data_rat")
    result["is_nr_registered"] = result.get("data_rat") in {"NR", "NR_NSA"}
    return result


def _label_value(patterns: Iterable[str], text: str) -> str | None:
    for pattern in patterns:
        value = _first_match(pattern, text, re.I | re.M)
        if value is not None:
            return value
    return None


def parse_wifi_interfaces(text: str) -> dict[str, Any]:
    """Parse the connected Windows Wi-Fi interface in Spanish or English."""

    signal = _int_value(
        _label_value([r"^[ \t]*Señal\s*:\s*(\d+)", r"^[ \t]*Signal\s*:\s*(\d+)"], text)
    )
    rssi = _int_value(
        _label_value([r"^[ \t]*Rssi\s*:\s*(-?\d+)", r"^[ \t]*RSSI\s*:\s*(-?\d+)"], text)
    )
    rx = _float_value(
        _label_value(
            [
                r"Velocidad de recepción \(Mbps\)\s*:\s*([\d.,]+)",
                r"Receive rate \(Mbps\)\s*:\s*([\d.,]+)",
            ],
            text,
        )
    )
    tx = _float_value(
        _label_value(
            [
                r"Velocidad de transmisión \(Mbps\)\s*:\s*([\d.,]+)",
                r"Transmit rate \(Mbps\)\s*:\s*([\d.,]+)",
            ],
            text,
        )
    )
    return {
        "ssid": _label_value([r"^[ \t]*SSID\s*:\s*(.*?)\s*$"], text),
        "bssid": _label_value(
            [r"^[ \t]*(?:AP )?BSSID\s*:\s*(\S+)", r"^[ \t]*BSSID\s*:\s*(\S+)"], text
        ),
        "band": _label_value([r"^[ \t]*Banda\s*:\s*(.*?)\s*$", r"^[ \t]*Band\s*:\s*(.*?)\s*$"], text),
        "channel": _int_value(
            _label_value([r"^[ \t]*Canal\s*:\s*(\d+)", r"^[ \t]*Channel\s*:\s*(\d+)"], text)
        ),
        "radio_type": _label_value(
            [r"^[ \t]*Tipo de radio\s*:\s*(.*?)\s*$", r"^[ \t]*Radio type\s*:\s*(.*?)\s*$"], text
        ),
        "signal_percent": signal,
        "rssi_dbm": rssi,
        "receive_mbps": rx,
        "transmit_mbps": tx,
    }


def parse_ping_output(text: str) -> dict[str, Any]:
    """Parse packet loss and average latency from Windows ping output."""

    loss_match = re.search(r"\((\d+)%\s*(?:perdidos|lost|loss)\)", text, re.I)
    if loss_match is None:
        loss_match = re.search(r"(\d+)%[^\n]*(?:perdidos|lost|loss)", text, re.I)
    loss = loss_match.group(1) if loss_match else None
    average = _first_match(
        r"(?:Media|Average|Promedio)\s*=\s*(\d+)\s*ms", text, re.I | re.M
    )
    return {
        "packet_loss_percent": _int_value(loss),
        "rtt_avg_ms": _int_value(average),
        "reachable": average is not None or (loss is not None and int(loss) < 100),
    }


def parse_adapter_stats(text: str) -> list[dict[str, Any]]:
    """Parse ``Get-NetAdapterStatistics | ConvertTo-Json`` output."""

    if not text.strip():
        return []
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        return []
    rows = raw if isinstance(raw, list) else [raw]
    result = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("Name"):
            continue
        result.append(
            {
                "name": str(row["Name"]),
                "received_bytes": int(row.get("ReceivedBytes", 0) or 0),
                "sent_bytes": int(row.get("SentBytes", 0) or 0),
            }
        )
    return result


def classify_delta(previous: dict[str, Any] | None, current: dict[str, Any]) -> list[str]:
    """Return conservative event labels; never infer throttling from one sample."""

    if previous is None:
        return ["baseline"]
    events = []
    old_cell = previous.get("cellular", {})
    new_cell = current.get("cellular", {})
    old_wifi = previous.get("wifi", {})
    new_wifi = current.get("wifi", {})

    if any(old_cell.get(key) != new_cell.get(key) for key in (
        "operator", "data_rat", "channel", "physical_cell_id", "bandwidths_khz"
    )):
        events.append("cell_identity_or_rat_changed")
    if old_cell.get("carrier_aggregation") != new_cell.get("carrier_aggregation"):
        events.append("cell_aggregation_changed")
    if any(old_wifi.get(key) != new_wifi.get(key) for key in ("bssid", "channel", "band")):
        events.append("hotspot_wifi_identity_changed")

    old_rsrp = old_cell.get("lte_rsrp_dbm")
    new_rsrp = new_cell.get("lte_rsrp_dbm")
    if old_rsrp is not None and new_rsrp is not None and abs(new_rsrp - old_rsrp) >= 8:
        events.append("cell_signal_step_changed")
    old_rssi = old_wifi.get("rssi_dbm")
    new_rssi = new_wifi.get("rssi_dbm")
    if old_rssi is not None and new_rssi is not None and abs(new_rssi - old_rssi) >= 8:
        events.append("hotspot_wifi_signal_step_changed")
    return events or ["sample"]


def run_command(command: list[str], timeout: float = 10) -> str:
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    return completed.stdout if completed.stdout else completed.stderr


def discover_default_gateway(command_runner: Callable[[list[str], float], str] = run_command) -> str | None:
    """Find the current IPv4 default gateway without assuming a Wi-Fi subnet."""

    try:
        output = command_runner(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                "(Get-NetRoute -DestinationPrefix '0.0.0.0/0' | Sort-Object RouteMetric | Select-Object -First 1 -ExpandProperty NextHop)",
            ],
            5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    candidate = output.strip().splitlines()[0] if output.strip() else ""
    try:
        socket.inet_aton(candidate)
    except OSError:
        return None
    return candidate


def collect_snapshot(
    adb_path: str,
    serial: str | None,
    gateway: str | None,
    internet_target: str,
    command_runner: Callable[[list[str], float], str] = run_command,
) -> dict[str, Any]:
    """Collect one low-impact snapshot from the phone and Windows host."""

    adb_command = [adb_path]
    if serial:
        adb_command += ["-s", serial]
    adb_command += ["shell", "dumpsys", "telephony.registry"]
    try:
        cellular_raw = command_runner(adb_command, 12)
        cellular = parse_telephony_registry(cellular_raw)
        cellular_error = None
    except (OSError, subprocess.SubprocessError) as exc:
        cellular = {}
        cellular_error = str(exc)

    try:
        wifi_raw = command_runner(["netsh", "wlan", "show", "interfaces"], 8)
        wifi = parse_wifi_interfaces(wifi_raw)
        wifi_error = None
    except (OSError, subprocess.SubprocessError) as exc:
        wifi = {}
        wifi_error = str(exc)

    paths: dict[str, Any] = {}
    if gateway:
        try:
            paths["gateway"] = parse_ping_output(
                command_runner(["ping.exe", "-n", "4", gateway], 10)
            )
        except (OSError, subprocess.SubprocessError) as exc:
            paths["gateway"] = {"error": str(exc)}
    try:
        paths["internet"] = parse_ping_output(
            command_runner(["ping.exe", "-n", "4", internet_target], 10)
        )
    except (OSError, subprocess.SubprocessError) as exc:
        paths["internet"] = {"error": str(exc)}

    try:
        adapter_raw = command_runner(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                "Get-NetAdapterStatistics | Select-Object Name,ReceivedBytes,SentBytes | ConvertTo-Json -Compress",
            ],
            8,
        )
        adapters = parse_adapter_stats(adapter_raw)
        adapter_error = None
    except (OSError, subprocess.SubprocessError) as exc:
        adapters = []
        adapter_error = str(exc)

    result: dict[str, Any] = {
        "schema": "xio.radio_monitor.v1",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "host": {"hostname": socket.gethostname()},
        "cellular": cellular,
        "wifi": wifi,
        "paths": paths,
        "adapters": adapters,
    }
    errors = {}
    if cellular_error:
        errors["cellular"] = cellular_error
    if wifi_error:
        errors["wifi"] = wifi_error
    if adapter_error:
        errors["adapters"] = adapter_error
    if errors:
        result["errors"] = errors
    return result


def resolve_adb_path(explicit: str | None = None) -> str:
    """Resolve ADB without baking a machine-specific path into the project."""

    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    env_path = os.environ.get("XIO_ADB")
    if env_path:
        candidates.append(Path(env_path))
    candidates.extend(
        [
            Path(__file__).parent / "actual" / "platform-tools" / "adb.exe",
            Path(__file__).resolve().parents[2] / "flujo" / "xio" / "actual" / "platform-tools" / "adb.exe",
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return explicit or env_path or "adb"


CSV_FIELDS = [
    "timestamp_utc", "event", "gateway", "cell_operator", "cell_rat", "cell_channel",
    "cell_physical_id", "cell_bandwidths_mhz", "cell_ca", "cell_rsrp_dbm", "cell_rsrq_db",
    "cell_snr_db", "cell_nr_available", "cell_en_dc_available", "cell_nr_registered",
    "cell_estimated_downlink_kbps", "wifi_bssid", "wifi_band", "wifi_channel", "wifi_rssi_dbm",
    "wifi_signal_percent", "wifi_receive_mbps", "wifi_transmit_mbps", "gateway_loss_percent",
    "gateway_rtt_avg_ms", "internet_loss_percent", "internet_rtt_avg_ms", "adapter_rates",
]


def flatten_snapshot(snapshot: dict[str, Any], event: str, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    cell = snapshot.get("cellular", {})
    wifi = snapshot.get("wifi", {})
    paths = snapshot.get("paths", {})
    gateway = paths.get("gateway", {})
    internet = paths.get("internet", {})
    adapter_rates = {}
    if previous:
        elapsed = max(
            0.001,
            _timestamp_seconds(snapshot.get("timestamp_utc"))
            - _timestamp_seconds(previous.get("timestamp_utc")),
        )
        old_by_name = {row["name"]: row for row in previous.get("adapters", [])}
        for row in snapshot.get("adapters", []):
            old = old_by_name.get(row["name"])
            if old:
                adapter_rates[row["name"]] = {
                    "received_bps": round((row["received_bytes"] - old["received_bytes"]) / elapsed, 1),
                    "sent_bps": round((row["sent_bytes"] - old["sent_bytes"]) / elapsed, 1),
                }
    return {
        "timestamp_utc": snapshot.get("timestamp_utc"),
        "event": event,
        "gateway": paths.get("gateway_host"),
        "cell_operator": cell.get("operator"),
        "cell_rat": cell.get("data_rat"),
        "cell_channel": cell.get("channel"),
        "cell_physical_id": cell.get("physical_cell_id"),
        "cell_bandwidths_mhz": json.dumps(cell.get("bandwidths_mhz", []), ensure_ascii=False),
        "cell_ca": cell.get("carrier_aggregation"),
        "cell_rsrp_dbm": cell.get("lte_rsrp_dbm"),
        "cell_rsrq_db": cell.get("lte_rsrq_db"),
        "cell_snr_db": cell.get("lte_snr_db"),
        "cell_nr_available": cell.get("nr_available"),
        "cell_en_dc_available": cell.get("en_dc_available"),
        "cell_nr_registered": cell.get("is_nr_registered"),
        "cell_estimated_downlink_kbps": cell.get("estimated_downlink_kbps"),
        "wifi_bssid": wifi.get("bssid"),
        "wifi_band": wifi.get("band"),
        "wifi_channel": wifi.get("channel"),
        "wifi_rssi_dbm": wifi.get("rssi_dbm"),
        "wifi_signal_percent": wifi.get("signal_percent"),
        "wifi_receive_mbps": wifi.get("receive_mbps"),
        "wifi_transmit_mbps": wifi.get("transmit_mbps"),
        "gateway_loss_percent": gateway.get("packet_loss_percent"),
        "gateway_rtt_avg_ms": gateway.get("rtt_avg_ms"),
        "internet_loss_percent": internet.get("packet_loss_percent"),
        "internet_rtt_avg_ms": internet.get("rtt_avg_ms"),
        "adapter_rates": json.dumps(adapter_rates, ensure_ascii=False, sort_keys=True),
    }


def _timestamp_seconds(value: str | None) -> float:
    if not value:
        return time.time()
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return time.time()


def append_record(output_dir: Path, snapshot: dict[str, Any], event: str, previous: dict[str, Any] | None) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    day = datetime.now().strftime("%Y%m%d")
    jsonl_path = output_dir / f"xio-radio-{day}.jsonl"
    csv_path = output_dir / f"xio-radio-{day}.csv"
    record = {**snapshot, "event": event}
    with jsonl_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    row = flatten_snapshot(snapshot, event, previous)
    has_header = csv_path.exists() and csv_path.stat().st_size > 0
    with csv_path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        if not has_header:
            writer.writeheader()
        writer.writerow(row)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Monitor de radio celular, Wi-Fi y camino móvil de XIO")
    parser.add_argument("--adb-path", default=None, help="Ruta al ejecutable adb")
    parser.add_argument("--serial", default=None, help="Serial ADB si hay más de un dispositivo")
    parser.add_argument("--gateway", default=None, help="Gateway local; si se omite se descubre")
    parser.add_argument("--internet-target", default="1.1.1.1")
    parser.add_argument("--interval", type=float, default=30.0, help="Segundos entre muestras (mínimo 10)")
    parser.add_argument("--output-dir", type=Path, default=Path("xio/data/radio_monitor"))
    parser.add_argument("--once", action="store_true", help="Captura una sola muestra y termina")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    adb_path = resolve_adb_path(args.adb_path)
    gateway = args.gateway or discover_default_gateway()
    previous = None
    first = True
    while True:
        snapshot = collect_snapshot(adb_path, args.serial, gateway, args.internet_target)
        snapshot["paths"]["gateway_host"] = gateway
        events = classify_delta(previous, snapshot)
        event = "+".join(events)
        append_record(args.output_dir, snapshot, event, previous)
        print(json.dumps({"event": event, **snapshot}, ensure_ascii=False, indent=2))
        previous = snapshot
        if args.once:
            return 0
        if first and args.interval < 10:
            print("--interval menor a 10 no se usa; se ajusta a 10 segundos", file=sys.stderr)
            args.interval = 10
        first = False
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
