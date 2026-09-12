"""Read-only verifier for the prepared XIO field runtime bundle.

The bundle is extracted directly under ``/sdcard/xio_termux`` by a later,
explicit deployment step. This verifier does not extract it, touch ADB, or
inspect/modify any database.

Usage:
    python tests/check_xio_runtime_bundle.py path/to/xio-field-runtime.zip
"""

from __future__ import annotations

import argparse
import sys
import zipfile


REQUIRED_FILES = (
    "new/server.py",
    "new/run_server.sh",
    "new/requirements.txt",
    "new/plugins/base.py",
    "new/plugins/__init__.py",
    "new-plugins/connectivity_supervisor/__init__.py",
    "new-plugins/foh_monitor/__init__.py",
    "new-plugins/foh_monitor/foh_vj_context.json",
    "new-plugins/foh_monitor/static/mapping.html",
    "new-plugins/foh_monitor/static/raider.html",
    "new-plugins/rd_field/__init__.py",
    "new-plugins/rd_field/bridge.py",
    "new-plugins/rd_field/static/index.html",
    "new-plugins/rd_field/static/raider.html",
    "new-plugins/rd_field/static/app.js",
    "new-plugins/rd_field/static/manifest.webmanifest",
    "new-plugins/rd_field/static/styles.css",
    "new-plugins/rd_field/static/sw.js",
)
EXPECTED_PLUGIN_DIRS = {
    "connectivity_supervisor",
    "foh_monitor",
    "rd_field",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle")
    args = parser.parse_args()

    errors: list[str] = []
    try:
        archive = zipfile.ZipFile(args.bundle)
        names = {
            name.replace("\\", "/").lstrip("./")
            for name in archive.namelist()
            if not name.endswith("/")
        }
        missing = [name for name in REQUIRED_FILES if name not in names]
        errors.extend(f"required file absent: {name}" for name in missing)

        forbidden = [
            name for name in names
            if "__pycache__/" in name or name.endswith(".pyc")
        ]
        errors.extend(f"cache included: {name}" for name in forbidden)
        accidental_data = [
            name for name in names
            if name.endswith((".db", ".sqlite", ".sqlite3"))
        ]
        errors.extend(f"database included in runtime bundle: {name}" for name in accidental_data)

        plugin_dirs = {
            name.split("/", 2)[1]
            for name in names
            if name.startswith("new-plugins/") and name.count("/") >= 2
        }
        if plugin_dirs != EXPECTED_PLUGIN_DIRS:
            errors.append(
                "new-plugins mismatch: expected "
                f"{sorted(EXPECTED_PLUGIN_DIRS)}, got {sorted(plugin_dirs)}"
            )

        def read(name: str) -> str:
            return archive.read(name).decode("utf-8")

        server = read("new/server.py")
        for marker in (
            "XIO_DATA_DIR",
            "PLUGINS_DIR",
            "XIO_BIND_HOST",
            'os.environ.get("XIO_PORT", "5000")',
        ):
            if marker not in server:
                errors.append(f"server marker absent: {marker}")

        launcher = read("new/run_server.sh")
        for marker in (
            "/sdcard/xio_termux/new-plugins/.",
            "XIO_DATA_DIR",
            "XIO_RD_PERSIST",
            "XIO_FOH_LOG_DIR",
            'XIO_HOST_DOMAIN="${XIO_HOST_DOMAIN:-rd}"',
            "python server.py",
        ):
            if marker not in launcher:
                errors.append(f"launcher marker absent: {marker}")

        connectivity = read("new-plugins/connectivity_supervisor/__init__.py")
        for marker in (
            '"ap_iface": "wlan1"',
            '"ap_prefix": ""',
            "def _hotspot_details(self)",
            '"hotspot_broadcast"',
        ):
            if marker not in connectivity:
                errors.append(f"connectivity marker absent: {marker}")

        foh = read("new-plugins/foh_monitor/__init__.py")
        for marker in (
            'register_route("/context/data"',
            'context_actual.json',
            '"domain": "vj_foh"',
            'register_route("/mapping"',
            'register_route("/raider"',
        ):
            if marker not in foh:
                errors.append(f"FOH context marker absent: {marker}")

        rd = read("new-plugins/rd_field/__init__.py")
        for marker in ('register_route("/events/sync"', 'register_route("/raider"', 'client_event_id'):
            if marker not in rd:
                errors.append(f"RD field marker absent: {marker}")
    except (OSError, zipfile.BadZipFile, KeyError, UnicodeDecodeError) as exc:
        errors.append(f"bundle unreadable: {exc}")

    if errors:
        for error in errors:
            print(f"[NO-GO] {error}")
        return 1
    print(
        "RUNTIME_BUNDLE=PASS server=5000 overlay=RD+FOH+CONNECTIVITY "
        "persistent-host-state=no-db/no-cache"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
