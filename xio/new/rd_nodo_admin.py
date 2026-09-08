#!/usr/bin/env python3
"""Local CLI for the RD NODO public state.

Run this on XIO/Termux.  It never accepts attendee data and never exposes a
write endpoint on the hotspot.
"""

import argparse
import json
import os
import tempfile
import time
from pathlib import Path


STATUSES = ("disponible", "espera", "pausa")
ZONES = {
    "info": "Información",
    "test": "Testeo",
    "care": "Pausa / acompañamiento",
}
NOTICES = {
    "normal": "Estamos aquí para escucharte.",
    "info": "Hay información importante disponible en el stand.",
    "care": "El espacio tranquilo está disponible.",
    "all_clear": "Puedes acercarte cuando quieras.",
}


def default_state():
    return {
        "schema_version": 1,
        "notice": "normal",
        "updated_at": None,
        "zones": {
            zone_id: {"label": label, "status": "disponible"}
            for zone_id, label in ZONES.items()
        },
    }


def load_state(path):
    try:
        raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except (OSError, ValueError, TypeError):
        raw = None
    state = default_state()
    if not isinstance(raw, dict):
        return state
    if raw.get("notice") in NOTICES:
        state["notice"] = raw["notice"]
    if isinstance(raw.get("updated_at"), (int, float)) and not isinstance(raw.get("updated_at"), bool):
        state["updated_at"] = raw["updated_at"]
    for zone_id, label in ZONES.items():
        zone = raw.get("zones", {}).get(zone_id, {}) if isinstance(raw.get("zones"), dict) else {}
        if isinstance(zone, dict) and zone.get("status") in STATUSES:
            state["zones"][zone_id]["status"] = zone["status"]
        state["zones"][zone_id]["label"] = label
    return state


def save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix="rd_nodo_", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def main(argv=None):
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Manage RD NODO public state locally")
    parser.add_argument("--state-file", default=os.environ.get("RD_NODO_STATE_FILE", str(here / "rd_nodo_state.json")))
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="show current public state")
    zone = sub.add_parser("zone", help="change one public zone")
    zone.add_argument("zone", choices=tuple(ZONES))
    zone.add_argument("status", choices=STATUSES)
    notice = sub.add_parser("notice", help="change the approved public notice")
    notice.add_argument("notice", choices=tuple(NOTICES))

    args = parser.parse_args(argv)
    path = Path(args.state_file)
    state = load_state(path)
    if args.command == "status":
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return 0
    if args.command == "zone":
        state["zones"][args.zone]["status"] = args.status
    elif args.command == "notice":
        state["notice"] = args.notice
    state["updated_at"] = time.time()
    save_state(path, state)
    print(json.dumps(state, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
