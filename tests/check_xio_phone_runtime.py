"""Read-only preflight for the actual XIO phone runtime.

This gate deliberately performs no ``adb push``, install, reboot, Termux input,
or HTTP write. It discovers the current hotspot address from ``wlan1`` instead
of accepting a committed subnet. A strict pass requires the deployed XIO
runtime, the durable RD database, the listener on port 5000, and a reachable
namespaced API response.

Usage:
    python tests/check_xio_phone_runtime.py
    python tests/check_xio_phone_runtime.py --skip-http  # file/port preflight only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_ADB = os.environ.get(
    "ADB_PATH", r"C:\XPEDR\XiaomiServer\platform-tools\adb.exe"
)
DEFAULT_SERIAL = os.environ.get("XIO_DEVICE_SERIAL", "8299e66f")
PHONE_ROOT = "/sdcard/xio_termux"
REQUIRED_FILES = (
    "new/server.py",
    "new/run_server.sh",
    "new-plugins/rd_field/__init__.py",
    "new-plugins/rd_field/static/index.html",
    "new-plugins/foh_monitor/__init__.py",
    "new-plugins/foh_monitor/foh_vj_context.json",
    "new-plugins/foh_monitor/static/mapping.html",
    "new-plugins/connectivity_supervisor/__init__.py",
)
SYNC_FILES = (
    "new/server.py",
    "new/run_server.sh",
    "new-plugins/foh_monitor/__init__.py",
    "new-plugins/connectivity_supervisor/__init__.py",
)


class Adb:
    def __init__(self, path: str, serial: str):
        self.path = path
        self.serial = serial

    def run(self, *args: str, timeout: float = 8.0) -> tuple[int, str, str]:
        try:
            result = subprocess.run(
                [self.path, "-s", self.serial, *args],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return 255, "", str(exc)
        return result.returncode, result.stdout.strip(), result.stderr.strip()

    def shell(self, command: str) -> tuple[int, str, str]:
        # The command strings below are fixed read-only probes, not user input.
        return self.run("shell", command)


def fail(errors: list[str], message: str) -> None:
    errors.append(message)
    print(f"[NO-GO] {message}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", default=DEFAULT_ADB)
    parser.add_argument("--serial", default=DEFAULT_SERIAL)
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--skip-http", action="store_true")
    args = parser.parse_args()

    errors: list[str] = []
    adb = Adb(args.adb, args.serial)

    rc, state, detail = adb.run("get-state")
    if rc != 0 or state != "device":
        fail(errors, f"ADB device not ready: state={state or detail or rc}")
        return 1
    print(f"DEVICE=PASS serial={args.serial}")

    rc, net, detail = adb.shell("ip -o -4 addr show wlan1 2>/dev/null")
    match = re.search(r"\binet\s+(\d+\.\d+\.\d+\.\d+)/(\d+)", net)
    if rc != 0 or not match:
        fail(errors, f"hotspot wlan1 IPv4 unavailable: {detail or net or rc}")
        return 1
    phone_ip, prefix = match.groups()
    print(f"HOTSPOT=PASS address={phone_ip}/{prefix}")

    missing: list[str] = []
    for relative in REQUIRED_FILES:
        rc, _, _ = adb.shell(f"test -f {PHONE_ROOT}/{relative}")
        if rc != 0:
            missing.append(relative)
    if missing:
        fail(errors, "deployed XIO files absent: " + ", ".join(missing))
    else:
        print(f"FILES=PASS count={len(REQUIRED_FILES)}")

    # A previous XIO deployment may leave the same filenames on the phone
    # while still carrying obsolete behavior. Compare only the current source
    # files; this remains a read-only check and never repairs the phone.
    source_root = Path(__file__).resolve().parents[1]
    stale: list[str] = []
    for relative in SYNC_FILES:
        local = source_root / "xio" / relative
        if not local.is_file():
            fail(errors, f"canonical source absent for hash comparison: {local}")
            continue
        rc, remote_hash, detail = adb.shell(
            f"sha256sum {PHONE_ROOT}/{relative} 2>/dev/null"
        )
        remote_digest = (remote_hash.split() or [""])[0].lower()
        expected = sha256_file(local)
        if rc != 0 or len(remote_digest) != 64:
            # The missing-file result is already reported above; keep this
            # second message focused on the stronger reason: no sync proof.
            fail(errors, f"hash unavailable for deployed {relative}")
        elif remote_digest != expected:
            stale.append(
                f"{relative} (phone={remote_digest[:12]}, current={expected[:12]})"
            )
    if stale:
        fail(errors, "deployed XIO runtime is stale/mismatched: " + ", ".join(stale))
    elif not any("hash unavailable" in item for item in errors):
        print(f"SOURCE_SYNC=PASS files={len(SYNC_FILES)}")

    rc, _, _ = adb.shell(f"test -f {PHONE_ROOT}/rd_field/rd.db")
    if rc != 0:
        fail(errors, "persistent RD host snapshot absent: /sdcard/xio_termux/rd_field/rd.db")
    else:
        print("RD_PERSISTENCE=PASS rd.db-present")

    rc, listeners, detail = adb.shell("ss -ltn 2>/dev/null")
    port_pattern = re.compile(rf"(?:\*|0\.0\.0\.0|127\.0\.0\.1):{args.port}\b")
    if rc != 0 or not port_pattern.search(listeners):
        fail(errors, f"XIO listener not found on port {args.port}: {detail or listeners or rc}")
    else:
        print(f"LISTENER=PASS port={args.port}")

    if not args.skip_http:
        url = f"http://{phone_ip}:{args.port}/api/plugins"
        try:
            with urllib.request.urlopen(url, timeout=4) as response:
                body = response.read(8192).decode("utf-8", "replace")
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = None
            if response.status != 200 or not isinstance(payload, (dict, list)):
                fail(errors, f"XIO HTTP response invalid: {url} status={response.status}")
            else:
                print(f"HTTP=PASS url={url} status={response.status}")
        except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            fail(errors, f"XIO HTTP unreachable: {url}: {exc}")
    else:
        print("HTTP=SKIP requested")

    if errors:
        print("PHONE_RUNTIME=NO-GO")
        return 1
    print("PHONE_RUNTIME=PASS read-only")
    return 0


if __name__ == "__main__":
    sys.exit(main())
