"""ADB subprocess wrapper for controlling a Xiaomi phone over USB or WiFi."""

import re
import subprocess
import time


KEYCODES = {
    "home": 3,
    "back": 4,
    "recents": 187,
    "power": 26,
    "volume_up": 24,
    "volume_down": 25,
}


class XiaomiController:
    def __init__(self, adb_path="adb", serial=None):
        self.adb_path = adb_path
        self.serial = serial

    def _base_cmd(self):
        cmd = [self.adb_path]
        if self.serial:
            cmd += ["-s", self.serial]
        return cmd

    def _run(self, args, timeout=15):
        result = subprocess.run(
            self._base_cmd() + args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.stdout.strip()

    def _shell(self, args, timeout=15):
        return self._run(["shell"] + args, timeout=timeout)

    def devices(self):
        out = self._run(["devices"])
        lines = out.splitlines()[1:]
        return [line.split("\t") for line in lines if line.strip()]

    def _get_wlan_ip(self):
        out = self._shell(["ip", "addr", "show", "wlan0"])
        match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", out)
        if match:
            return match.group(1)

        # wlan0 can be down while another wlan* interface (e.g. a hotspot
        # AP interface) holds the real LAN address, so scan all of them
        # before falling back to the default route (which may point at
        # mobile data instead of WiFi).
        out = self._shell(["ip", "-4", "addr"])
        for block in re.split(r"\n(?=\d+: )", out):
            if re.match(r"\d+: wlan", block) and "inet " in block:
                match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", block)
                if match:
                    return match.group(1)

        out = self._shell(["ip", "route"])
        match = re.search(r"src (\d+\.\d+\.\d+\.\d+)", out)
        if match:
            return match.group(1)

        return None

    def connect_wifi(self, port=5555, wait_seconds=2):
        self._run(["tcpip", str(port)])
        time.sleep(wait_seconds)

        ip = self._get_wlan_ip()
        if not ip:
            raise RuntimeError("Could not determine phone IP on wlan0")

        target = f"{ip}:{port}"
        result = self._run(["connect", target])
        return target, result

    def tap(self, x, y):
        return self._shell(["input", "tap", str(x), str(y)])

    def swipe(self, x1, y1, x2, y2, duration_ms=300):
        return self._shell(
            ["input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms)]
        )

    def text(self, value):
        escaped = value.replace(" ", "%s")
        return self._shell(["input", "text", escaped])

    def keyevent(self, code):
        return self._shell(["input", "keyevent", str(code)])

    def named_key(self, name):
        code = KEYCODES.get(name)
        if code is None:
            raise ValueError(f"Unknown key: {name}")
        return self.keyevent(code)

    def screen_size(self):
        out = self._shell(["wm", "size"])
        match = re.search(r"(\d+)x(\d+)", out)
        if not match:
            return None
        return int(match.group(1)), int(match.group(2))

    def screenshot(self, local_path):
        result = subprocess.run(
            self._base_cmd() + ["exec-out", "screencap", "-p"],
            capture_output=True,
            timeout=15,
        )
        with open(local_path, "wb") as f:
            f.write(result.stdout)
        return local_path

    def list_packages(self):
        out = self._shell(["pm", "list", "packages"])
        return [line.replace("package:", "") for line in out.splitlines() if line.strip()]

    def list_launchable_packages(self):
        out = self._shell(
            [
                "cmd", "package", "query-activities", "--components",
                "-a", "android.intent.action.MAIN",
                "-c", "android.intent.category.LAUNCHER",
            ]
        )
        packages = set()
        for line in out.splitlines():
            line = line.strip()
            if "/" in line:
                packages.add(line.split("/", 1)[0])
        return sorted(packages)

    def open_app(self, package):
        return self._shell(
            ["monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"]
        )

    def force_stop(self, package):
        return self._shell(["am", "force-stop", package])

    def push(self, local_path, remote_path):
        return self._run(["push", local_path, remote_path])

    def pull(self, remote_path, local_path):
        return self._run(["pull", remote_path, local_path])

    def battery(self):
        out = self._shell(["dumpsys", "battery"])
        info = {}
        for line in out.splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                info[key.strip()] = value.strip()
        return info

    def battery_status(self):
        info = self.battery()
        try:
            level = int(info.get("level", -1))
        except ValueError:
            level = -1
        charging = info.get("AC powered") == "true" or info.get("USB powered") == "true" or info.get("Wireless powered") == "true"
        return {"level": level, "charging": charging}

    def dump_ui(self):
        self._shell(["uiautomator", "dump", "/sdcard/window_dump.xml"])
        return self._shell(["cat", "/sdcard/window_dump.xml"])
