"""
Xiaomi ADB Controller – wraps adb commands for remote phone management.
Works over USB or WiFi (adb tcpip / adb connect).
"""

import subprocess
import json
import os
import shlex
import tempfile
import threading
import types
import xml.etree.ElementTree as ET
from pathlib import Path


class XiaomiController:
    """High-level ADB controller for Xiaomi Android devices."""

    def __init__(self, serial: str | None = None, adb_path: str = "adb"):
        self.adb = adb_path
        self.serial = serial
        self._screen_size_cache = None
        # Backend: "adb" = drive over USB from a PC; "rish" = run ON the phone
        # in Termux, using Shizuku's shell uid (2000) via the rish bridge.
        self.backend = os.environ.get("XIO_BACKEND", "adb").lower()
        self.rish = os.environ.get("RISH_PATH", os.path.expanduser("~/rish"))
        # rish's stdout pipe truncates large output; we redirect to a file on
        # shared storage and read it back locally. Serialize so concurrent
        # callers (poll thread + HTTP requests) don't clobber the file.
        self._rish_out = os.environ.get("RISH_OUT", "/sdcard/xio_termux/.rish_out")
        self._shell_lock = threading.Lock()

    # ── low-level ────────────────────────────────────────────────────
    def _run(self, *args, timeout=30) -> subprocess.CompletedProcess:
        cmd = [self.adb]
        if self.serial:
            cmd += ["-s", self.serial]
        cmd += list(args)
        return subprocess.run(
            cmd, capture_output=True, timeout=timeout, text=False
        )

    def _rish(self, cmdstr: str, timeout=30):
        """Run one shell command on-device as shell uid via Shizuku's rish.

        rish's stdout pipe truncates large output unreliably: even sequential
        `ip addr`/dumpsys calls come back as random partial chunks, because the
        app_process -> Shizuku -> client pipe is not fully drained before the
        process is reaped. To get COMPLETE output we redirect the command's
        stdout to a file on shared storage (shell uid 2000 has sdcard_rw) and
        read that file back directly from the local filesystem -- the on-device
        server can read /sdcard -- bypassing the rish pipe entirely. Serialized
        by a lock so concurrent callers don't clobber the shared file.

        Returns an object with `.stdout` (bytes) and `.returncode`, matching the
        CompletedProcess interface the callers rely on. Plugins that need stderr
        merge it inside their own command string (e.g. `... 2>&1`); the wrapper
        keeps stdout-only semantics (stderr dropped) to match the adb backend.

        `| cat` (2026-07-13): los comandos `cmd`-based (pm, appops, cmd, wm...)
        pasan su fd de stdout por Binder; redirigir ese fd a un archivo REGULAR
        (`> /sdcard/...`) rompe la transaccion con "cmd: Failure calling service
        ... Failed transaction (2147483646)". Interponer `| cat` hace que el
        comando escriba a un PIPE (fd que el Binder si acepta) y `cat` escribe al
        archivo -> desbloquea pm/appops/cmd/wm sin perder el fix de truncacion
        (seguimos leyendo del archivo). Transparente y binary-safe para los que ya
        andaban (cat/ls/dumpsys/ip/screencap). Empiricamente validado on-device.
        """
        wrapped = f"({cmdstr}) 2>/dev/null | cat > {self._rish_out}"
        with self._shell_lock:
            proc = subprocess.run(
                ["sh", self.rish, "-c", wrapped],
                capture_output=True, timeout=timeout, text=False,
            )
            try:
                with open(self._rish_out, "rb") as f:
                    data = f.read()
            except Exception:
                data = proc.stdout or b""   # fall back to the pipe if unreadable
        return types.SimpleNamespace(stdout=data, returncode=proc.returncode)

    def _shell(self, *args, timeout=30) -> str:
        if self.backend == "rish":
            r = self._rish(" ".join(str(a) for a in args), timeout=timeout)
        else:
            r = self._run("shell", *args, timeout=timeout)
        return r.stdout.decode("utf-8", errors="replace").strip()

    def _exec_out(self, *args, timeout=30) -> bytes:
        """Binary-safe command output (screenshots, raw file bytes)."""
        if self.backend == "rish":
            return self._rish(" ".join(str(a) for a in args), timeout=timeout).stdout
        return self._run("exec-out", *args, timeout=timeout).stdout

    def _check(self) -> None:
        if self.backend == "rish":
            if not self.is_connected():
                raise RuntimeError("Shizuku/rish not available (uid != 2000)")
            return
        r = self._run("get-state")
        state = r.stdout.decode().strip()
        if state != "device":
            raise RuntimeError(f"Device not available (state={state!r})")

    # ── device info ──────────────────────────────────────────────────
    def is_connected(self) -> bool:
        try:
            if self.backend == "rish":
                return b"uid=2000" in self._rish("id", timeout=5).stdout
            r = self._run("get-state", timeout=5)
            return r.stdout.decode().strip() == "device"
        except Exception:
            return False

    def connection_type(self) -> str:
        """Return 'usb'/'wifi' (adb) or 'on-device' (rish)."""
        if self.backend == "rish":
            return "on-device"
        if self.serial and (":" in self.serial):
            return "wifi"
        if self.serial:
            return "usb"
        # auto-detect from devices list
        r = self._run("devices", "-l", timeout=5)
        lines = r.stdout.decode().strip().split("\n")[1:]
        for line in lines:
            if "device" in line and "model:" in line:
                parts = line.split()
                if parts:
                    name = parts[0]
                    if ":" in name:
                        return "wifi"
                    return "usb"
        return "unknown"

    def device_info(self) -> dict:
        """Return model, android version, SDK, etc."""
        info = {}
        for key, prop in [
            ("model", "ro.product.model"),
            ("brand", "ro.product.brand"),
            ("android_version", "ro.build.version.release"),
            ("sdk", "ro.build.version.sdk"),
            ("build", "ro.build.display.id"),
        ]:
            info[key] = self._shell("getprop", prop)
        return info

    def screen_size(self) -> dict:
        if self._screen_size_cache:
            return self._screen_size_cache
        out = self._shell("wm", "size")
        # Physical size: 1080x2400
        for line in out.splitlines():
            if "size" in line.lower():
                parts = line.split(":")[-1].strip().split("x")
                if len(parts) == 2:
                    self._screen_size_cache = {
                        "width": int(parts[0]),
                        "height": int(parts[1]),
                    }
                    return self._screen_size_cache
        return {"width": 1080, "height": 2400}

    # ── input ────────────────────────────────────────────────────────
    _KEY_MAP = {
        "home": "KEYCODE_HOME",
        "back": "KEYCODE_BACK",
        "recents": "KEYCODE_APP_SWITCH",
        "power": "KEYCODE_POWER",
        "volume_up": "KEYCODE_VOLUME_UP",
        "volume_down": "KEYCODE_VOLUME_DOWN",
        "enter": "KEYCODE_ENTER",
        "delete": "KEYCODE_DEL",
        "tab": "KEYCODE_TAB",
        "escape": "KEYCODE_ESCAPE",
        "menu": "KEYCODE_MENU",
    }

    def tap(self, x: int, y: int):
        self._shell("input", "tap", str(x), str(y))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300):
        self._shell("input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms))

    def long_press(self, x: int, y: int, duration_ms: int = 1000):
        self._shell("input", "swipe", str(x), str(y), str(x), str(y), str(duration_ms))

    def text(self, s: str):
        # Escape special characters for adb shell
        escaped = s.replace(" ", "%s").replace("&", "\\&").replace("<", "\\<").replace(">", "\\>")
        self._shell("input", "text", escaped)

    def named_key(self, name: str):
        code = self._KEY_MAP.get(name.lower(), name.upper())
        if not code.startswith("KEYCODE_"):
            code = f"KEYCODE_{code}"
        self._shell("input", "keyevent", code)

    # ── screenshot ───────────────────────────────────────────────────
    def screenshot(self) -> bytes:
        """Capture screen and return PNG bytes."""
        remote = "/sdcard/__adb_screen.png"
        self._shell("screencap", "-p", remote)
        return self._exec_out("cat", remote)

    # ── apps ─────────────────────────────────────────────────────────
    def list_launchable_packages(self) -> list[dict]:
        """Return list of apps that have a launcher activity."""
        out = self._shell(
            "cmd", "package", "query-activities",
            "-a", "android.intent.action.MAIN",
            "-c", "android.intent.category.LAUNCHER",
            "--components"
        )
        apps = []
        seen = set()
        for line in out.splitlines():
            line = line.strip()
            if "/" in line:
                pkg = line.split("/")[0]
                if pkg not in seen:
                    seen.add(pkg)
                    label = self._shell("cmd", "package", "resolve-activity",
                                       "--brief", line).splitlines()[-1] if False else ""
                    apps.append({"package": pkg, "activity": line, "label": label})
        # Try to get labels
        for app in apps:
            try:
                label = self._shell(
                    "aapt", "dump", "badging", 
                    f"$(pm path {app['package']})"
                )
            except Exception:
                pass
            # Fallback: use dumpsys
            try:
                out2 = self._shell("dumpsys", "package", app["package"])
                for ln in out2.splitlines():
                    ln = ln.strip()
                    if "android.app.label=" in ln:
                        app["label"] = ln.split("=", 1)[1].strip("'\" ")
                        break
            except Exception:
                pass
            if not app.get("label"):
                app["label"] = app["package"].split(".")[-1]
        return sorted(apps, key=lambda a: a["label"].lower())

    def list_installed_packages(self) -> list[dict]:
        """Return all installed packages (including system)."""
        out = self._shell("pm", "list", "packages", "-f")
        pkgs = []
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("package:"):
                rest = line[8:]
                if "=" in rest:
                    path, pkg = rest.rsplit("=", 1)
                    pkgs.append({"package": pkg, "path": path})
        return pkgs

    def open_app(self, package: str):
        """Launch app by package name using monkey."""
        self._shell("monkey", "-p", package,
                     "-c", "android.intent.category.LAUNCHER", "1")

    def force_stop(self, package: str):
        self._shell("am", "force-stop", package)

    def uninstall(self, package: str) -> str:
        out = self._shell("pm", "uninstall", package)
        return out

    def clear_data(self, package: str) -> str:
        out = self._shell("pm", "clear", package)
        return out

    def get_app_icon(self, package: str) -> bytes | None:
        """Attempt to get app icon as PNG. Returns None if unavailable."""
        # Use the package's base APK to extract icon via aapt if available
        path_out = self._shell("pm", "path", package)
        if not path_out.startswith("package:"):
            return None
        apk_path = path_out[8:]
        # Get icon path from aapt
        try:
            dump = self._shell("aapt", "dump", "badging", apk_path)
            icon_name = None
            for line in dump.splitlines():
                if "application-icon-320:" in line or "application-icon-240:" in line:
                    icon_name = line.split("'")[1]
                    break
            if icon_name:
                # Extract icon from APK
                tmpdir = tempfile.mkdtemp()
                self._run("pull", apk_path, os.path.join(tmpdir, "app.apk"))
                # We won't extract zip here; return None for simplicity
                return None
        except Exception:
            pass
        return None

    # ── file management ──────────────────────────────────────────────
    def list_dir(self, remote_path: str = "/sdcard/") -> list[dict]:
        """List directory contents on device."""
        # Use ls -la for detailed info
        out = self._shell("ls", "-la", shlex.quote(remote_path))
        entries = []
        for line in out.splitlines():
            parts = line.split()
            if len(parts) < 6:
                continue
            # Skip . and ..
            name = parts[-1]
            if name in (".", ".."):
                continue
            is_dir = line.startswith("d")
            size = 0
            date = ""
            if not is_dir:
                try:
                    size = int(parts[4])
                except (ValueError, IndexError):
                    pass
            # Try to extract date (columns 5,6,7 in ls -la)
            try:
                date = " ".join(parts[5:8])
            except IndexError:
                pass
            entries.append({
                "name": name,
                "is_dir": is_dir,
                "size": size,
                "date": date,
                "path": f"{remote_path.rstrip('/')}/{name}",
            })
        return sorted(entries, key=lambda e: (not e["is_dir"], e["name"].lower()))

    def push(self, local_path: str, remote_path: str) -> str:
        if self.backend == "rish":
            import shutil
            try:
                shutil.copyfile(local_path, remote_path)   # Termux can write /sdcard directly
                return "copied"
            except Exception:
                self._rish(f"cp '{local_path}' '{remote_path}'")
                return "copied(rish)"
        r = self._run("push", local_path, remote_path)
        return r.stdout.decode().strip() + r.stderr.decode().strip()

    def push_bytes(self, data: bytes, remote_path: str) -> str:
        """Write bytes directly to a remote path via a temp file."""
        tmp = tempfile.NamedTemporaryFile(delete=False)
        try:
            tmp.write(data)
            tmp.flush()
            tmp.close()
            return self.push(tmp.name, remote_path)
        finally:
            os.unlink(tmp.name)

    def pull(self, remote_path: str, local_path: str) -> str:
        if self.backend == "rish":
            with open(local_path, "wb") as f:
                f.write(self.pull_bytes(remote_path))
            return "pulled"
        r = self._run("pull", remote_path, local_path)
        return r.stdout.decode().strip() + r.stderr.decode().strip()

    def pull_bytes(self, remote_path: str) -> bytes:
        """Read a file's raw bytes from the device."""
        return self._exec_out("cat", remote_path)

    def delete_file(self, remote_path: str) -> str:
        return self._shell("rm", "-rf", shlex.quote(remote_path))

    def mkdir(self, remote_path: str) -> str:
        return self._shell("mkdir", "-p", shlex.quote(remote_path))

    def rename(self, old_path: str, new_path: str) -> str:
        return self._shell("mv", shlex.quote(old_path), shlex.quote(new_path))

    # ── battery / status ─────────────────────────────────────────────
    def battery_status(self) -> dict:
        out = self._shell("dumpsys", "battery")
        result = {"level": 0, "charging": False, "status": "unknown", "temperature": 0}
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("level:"):
                try:
                    result["level"] = int(line.split(":")[1].strip())
                except ValueError:
                    pass
            elif line.startswith("status:"):
                try:
                    s = int(line.split(":")[1].strip())
                    result["charging"] = s == 2  # 2 = charging
                    result["status"] = {
                        1: "unknown", 2: "charging", 3: "discharging",
                        4: "not_charging", 5: "full"
                    }.get(s, "unknown")
                except ValueError:
                    pass
            elif line.startswith("temperature:"):
                try:
                    result["temperature"] = int(line.split(":")[1].strip()) / 10.0
                except ValueError:
                    pass
            elif line.startswith("AC powered:"):
                result["ac_power"] = "true" in line.lower()
            elif line.startswith("USB powered:"):
                result["usb_power"] = "true" in line.lower()
            elif line.startswith("Wireless powered:"):
                result["wireless_power"] = "true" in line.lower()
        return result

    def network_info(self) -> dict:
        """Get network info: wifi state, IP, signal strength."""
        info = {"wifi_enabled": False, "ip": "", "ssid": "", "signal": ""}
        # Wifi state
        out = self._shell("dumpsys", "wifi")
        for line in out.splitlines():
            if "mWifiInfo" in line or "Wi-Fi is" in line:
                if "Wi-Fi is disabled" in line:
                    info["wifi_enabled"] = False
                elif "Wi-Fi is enabled" in line:
                    info["wifi_enabled"] = True
            if "SSID:" in line and info["ssid"] == "":
                ssid = line.split("SSID:")[1].strip().split(",")[0].strip('"')
                if ssid != "<unknown ssid>":
                    info["ssid"] = ssid
            if "Link speed:" in line and info["signal"] == "":
                info["signal"] = line.split("Link speed:")[1].strip().split(",")[0]
        # IP address
        ip_out = self._shell("ip", "route")
        for line in ip_out.splitlines():
            if "wlan0" in line and "src" in line:
                parts = line.split()
                for i, p in enumerate(parts):
                    if p == "src" and i + 1 < len(parts):
                        info["ip"] = parts[i + 1]
                        break
        if not info["ip"]:
            ip_out2 = self._shell("ifconfig", "wlan0")
            for line in ip_out2.splitlines():
                if "inet " in line:
                    info["ip"] = line.split()[1].split(":")[-1]
                    break
        return info

    def full_status(self) -> dict:
        """Comprehensive device status."""
        status = {
            "connected": self.is_connected(),
            "connection_type": self.connection_type(),
        }
        if status["connected"]:
            status.update(self.battery_status())
            status["network"] = self.network_info()
            status["device"] = self.device_info()
            status["screen"] = self.screen_size()
            status["serial"] = self.serial
        return status

    # ── UI tree ──────────────────────────────────────────────────────
    def dump_ui(self) -> list[dict]:
        """Dump the UI hierarchy and return a flat list of interactive elements."""
        remote = "/sdcard/__adb_ui.xml"
        self._shell("uiautomator", "dump", remote)
        xml_data = self._shell("cat", remote)
        if not xml_data:
            return []

        elements = []
        try:
            root = ET.fromstring(xml_data)
            for node in root.iter("node"):
                bounds = node.get("bounds", "")
                text = node.get("text", "")
                content_desc = node.get("content-desc", "")
                class_name = node.get("class", "")
                resource_id = node.get("resource-id", "")
                clickable = node.get("clickable", "false") == "true"
                enabled = node.get("enabled", "true") == "true"
                scrollable = node.get("scrollable", "false") == "true"

                if not (text or content_desc or clickable):
                    continue

                # Parse bounds [x1,y1][x2,y2]
                try:
                    coords = bounds.replace("][", ",").strip("[]").split(",")
                    x1, y1, x2, y2 = int(coords[0]), int(coords[1]), int(coords[2]), int(coords[3])
                    center_x = (x1 + x2) // 2
                    center_y = (y1 + y2) // 2
                except (ValueError, IndexError):
                    continue

                elements.append({
                    "text": text,
                    "content_desc": content_desc,
                    "class": class_name,
                    "resource_id": resource_id,
                    "bounds": bounds,
                    "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                    "center_x": center_x,
                    "center_y": center_y,
                    "clickable": clickable,
                    "enabled": enabled,
                    "scrollable": scrollable,
                    "label": text or content_desc or resource_id.split("/")[-1] if resource_id else class_name.split(".")[-1],
                })
        except ET.ParseError:
            pass

        return elements

    # ── macros / automation ──────────────────────────────────────────
    def run_sequence(self, actions: list[dict], delay_ms: int = 500):
        """Run a sequence of actions. Each action is a dict with 'type' and params."""
        import time
        for action in actions:
            t = action.get("type", "")
            if t == "tap":
                self.tap(action["x"], action["y"])
            elif t == "swipe":
                self.swipe(action["x1"], action["y1"], action["x2"], action["y2"],
                          action.get("duration", 300))
            elif t == "text":
                self.text(action["value"])
            elif t == "key":
                self.named_key(action["value"])
            elif t == "long_press":
                self.long_press(action["x"], action["y"], action.get("duration", 1000))
            elif t == "open_app":
                self.open_app(action["package"])
            elif t == "wait":
                time.sleep(action.get("ms", 1000) / 1000.0)
                continue
            elif t == "screenshot":
                pass  # handled by frontend
            if delay_ms > 0 and t != "wait":
                time.sleep(delay_ms / 1000.0)

    def tap_element(self, element: dict):
        """Tap on a UI element by its center coordinates."""
        cx = element.get("center_x")
        cy = element.get("center_y")
        if cx is not None and cy is not None:
            self.tap(cx, cy)
