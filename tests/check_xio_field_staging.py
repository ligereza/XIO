"""Read-only preflight for the XIO-RD/XIO-FOH field overlay.

This gate checks the prepared plugin assets and a selected host RD database.
It never creates tables, writes a database, touches ADB, or changes a runtime.
Usage:
    python tests/check_xio_field_staging.py --rd-db /path/to/rd.db
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path


REQUIRED_ASSETS = (
    # Existing support plugin included in the field overlay so the live
    # hotspot subnet is derived at runtime instead of using a stale prefix.
    "connectivity_supervisor/__init__.py",
    "foh_monitor/__init__.py",
    "foh_monitor/foh_vj_context.json",
    "foh_monitor/static/mapping.html",
    "foh_monitor/static/resumen.html",
    "rd_field/__init__.py",
    "rd_field/bridge.py",
    "rd_field/static/index.html",
    "rd_field/static/app.js",
    "rd_field/static/manifest.webmanifest",
    "rd_field/static/styles.css",
    "rd_field/static/sw.js",
)
REQUIRED_TABLES = (
    "rd_entidades_candidatas",
    "testeo_eventos_fuente",
    "evento_productoras",
    "evento_venues",
    "mesas_testeo",
    "muestras",
    "muestra_resultados",
    "xio_eventos",
    "xio_signal_events",
)


def fail(message: str) -> None:
    print(f"[NO-GO] {message}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plugin-root", type=Path, default=Path("xio/new-plugins")
    )
    parser.add_argument("--rd-db", type=Path, required=True)
    args = parser.parse_args()

    errors: list[str] = []
    root = args.plugin_root
    for relative in REQUIRED_ASSETS:
        if not (root / relative).is_file():
            errors.append(f"asset absent: {root / relative}")

    connectivity = root / "connectivity_supervisor" / "__init__.py"
    if connectivity.is_file():
        try:
            source = connectivity.read_text(encoding="utf-8")
            for marker in (
                '"ap_iface": "wlan1"',
                '"ap_prefix": ""',
                "def _hotspot_details(self)",
                '"hotspot_broadcast"',
            ):
                if marker not in source:
                    errors.append(f"connectivity support marker absent: {marker}")
        except OSError as exc:
            errors.append(f"connectivity support unreadable: {exc}")

    foh = root / "foh_monitor" / "__init__.py"
    if foh.is_file():
        try:
            source = foh.read_text(encoding="utf-8")
            for marker in (
                'register_route("/context/data"',
                'context_actual.json',
                '"domain": "vj_foh"',
                'register_route("/mapping"',
                'register_route("/resumen"',
            ):
                if marker not in source:
                    errors.append(f"FOH context marker absent: {marker}")
        except OSError as exc:
            errors.append(f"FOH plugin unreadable: {exc}")

    catalog = root / "foh_monitor" / "foh_vj_context.json"
    if catalog.is_file():
        try:
            payload = json.loads(catalog.read_text(encoding="utf-8"))
            if payload.get("schema") != "xio-foh-vj-context-v1":
                errors.append("FOH catalog schema invalido")
            if not isinstance(payload.get("events"), list) or not payload["events"]:
                errors.append("FOH catalog has no events")
        except (OSError, ValueError, TypeError) as exc:
            errors.append(f"FOH catalog unreadable: {exc}")

    db = args.rd_db
    if not db.is_file():
        errors.append(f"RD host database absent: {db}")
    else:
        conn = None
        try:
            conn = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            missing = [name for name in REQUIRED_TABLES if name not in tables]
            if missing:
                errors.append("RD tables absent: " + ", ".join(missing))
            event_count = (
                conn.execute("SELECT COUNT(*) FROM testeo_eventos_fuente").fetchone()[0]
                if "testeo_eventos_fuente" in tables
                else 0
            )
            if event_count == 0:
                errors.append("RD host database has no event references")
            print(f"RD_DB_READONLY tables={len(tables)} events={event_count}")
        except (OSError, sqlite3.Error) as exc:
            errors.append(f"RD host database cannot be read-only inspected: {exc}")
        finally:
            if conn is not None:
                conn.close()

    if errors:
        for message in errors:
            fail(message)
        return 1
    print(
        "FIELD_STAGING=PASS assets=RD+FOH+CONNECTIVITY database=host-read-only "
        "mode=overlay/no-phone-write"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
