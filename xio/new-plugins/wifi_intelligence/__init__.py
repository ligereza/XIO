"""
WiFi Intelligence – Gestion inteligente de WiFi.
"""

from plugins.base import PluginBase
import json, re, shlex
from datetime import datetime

# Formato REAL de `cmd wifi list-scan-results` (HyperOS/Android 13+, verificado
# en vivo 2026-07-18 sobre el Xiaomi):
#     BSSID              Frequency      RSSI           Age(sec)     SSID    Flags
#   02:00:00:00:00:02       2412    -77(0:-84/1:-78)     8.504    RED-EJEMPLO  [WPA2-PSK-CCMP][ESS]
# (el ejemplo era una red de un vecino, con su BSSID real, en un repo
#  publico: un BSSID se resuelve a coordenadas en bases de wardriving.
#  Ahora es ficticio -- 02: es el bit de "localmente administrada" y no
#  se asigna a hardware real. VCD-08, 2026-07-27.)
_SCAN_COLUMNAR = re.compile(
    r"^\s*([0-9a-fA-F:]{17})\s+(\d+)\s+(-?\d+)(?:\([^)]*\))?\s+([\d.]+)\s+(.*?)\s*(\[.*\])?\s*$"
)


def parse_scan_results(out):
    """Parsea la salida de `cmd wifi list-scan-results` en ambos formatos:
    columnar (dispositivos reales HyperOS/Android 13+) y legado `SSID:`/`signal:`.
    Devuelve [{ssid, signal, frequency, bssid, flags}] (claves extra solo si hay dato)."""
    networks = []
    for line in out.splitlines():
        if "SSID:" in line:  # formato legado
            m = re.search(r'SSID: "?([^"]+)"?', line)
            if m:
                net = {"ssid": m.group(1).strip().rstrip(",")}
                rm = re.search(r"signal: (-?\d+)", line)
                if rm:
                    net["signal"] = int(rm.group(1))
                networks.append(net)
            continue
        m = _SCAN_COLUMNAR.match(line)
        if m:
            bssid, freq, rssi, _age, ssid, flags = m.groups()
            ssid = ssid.strip()
            if not ssid:  # red oculta: sin nombre util
                continue
            net = {
                "ssid": ssid,
                "signal": int(rssi),
                "frequency": int(freq),
                "bssid": bssid.lower(),
            }
            if flags:
                net["flags"] = flags
            networks.append(net)
    return networks


class WiFiIntelligencePlugin(PluginBase):
    plugin_id = "wifi_intelligence"
    name = "WiFi Intelligence"
    version = "1.0.0"
    description = "Gestion inteligente de WiFi"
    author = "Arena Agent"
    icon = "network"
    category = "network"
    permissions = ["network", "system"]

    def __init__(self, context):
        super().__init__(context)
        self._known_networks = []
        self._signal_history = []

    def on_load(self):
        self._load_data()
        self.register_route("/status", self._api_status, methods=["GET"])
        self.register_route("/scan", self._api_scan, methods=["GET"])
        self.register_route("/known", self._api_known, methods=["GET"])
        self.register_route("/signal", self._api_signal, methods=["GET"])
        self.register_route("/security", self._api_security_audit, methods=["GET"])
        self.register_route("/toggle", self._api_toggle, methods=["POST"])
        self.register_route("/connect", self._api_connect, methods=["POST"])
        self.register_route("/forget", self._api_forget, methods=["POST"])
        self.context.schedule("wifi_poll", self._background_poll, interval_seconds=60)
        self.logger.info("WiFi Intelligence loaded")

    def _load_data(self):
        f = self.data_dir / "networks.json"
        if f.exists():
            try:
                self._known_networks = json.loads(f.read_text())
            except:
                pass

    def _save_data(self):
        (self.data_dir / "networks.json").write_text(json.dumps(self._known_networks, indent=2))

    def _get_wifi_info(self):
        try:
            out = self.controller._shell("dumpsys", "wifi")
            info = {"enabled": False, "connected": False, "ssid": "", "signal_dbm": 0, "link_speed": 0, "frequency": 0, "ip": ""}
            for line in out.splitlines():
                if "Wi-Fi is enabled" in line:
                    info["enabled"] = True
                if "SSID:" in line:
                    m = re.search(r'SSID: "?([^",]+)"?', line)
                    if m:
                        info["ssid"] = m.group(1).strip('"')
                        info["connected"] = True
                if "RSSI:" in line:
                    m = re.search(r'RSSI: (-?\d+)', line)
                    if m:
                        info["signal_dbm"] = int(m.group(1))
                if "Link speed:" in line:
                    m = re.search(r'Link speed: (\d+)', line)
                    if m:
                        info["link_speed"] = int(m.group(1))
                if "Frequency:" in line:
                    m = re.search(r'Frequency: (\d+)', line)
                    if m:
                        info["frequency"] = int(m.group(1))
            try:
                ip_out = self.controller._shell("ip", "route")
                for line in ip_out.splitlines():
                    if "wlan0" in line and "src" in line:
                        parts = line.split()
                        for i, p in enumerate(parts):
                            if p == "src" and i + 1 < len(parts):
                                info["ip"] = parts[i + 1]
            except:
                pass
            return info
        except Exception as e:
            self.logger.error(f"WiFi info error: {e}")
            return {}

    def _signal_quality(self, dbm):
        if dbm >= -50: return 100
        if dbm <= -100: return 0
        return 2 * (dbm + 100)

    def _background_poll(self):
        try:
            info = self._get_wifi_info()
            if info.get("connected") and info.get("ssid"):
                entry = {"timestamp": datetime.now().isoformat(), "ssid": info["ssid"], "signal_dbm": info.get("signal_dbm", 0), "link_speed": info.get("link_speed", 0), "frequency": info.get("frequency", 0)}
                self._signal_history.append(entry)
                if len(self._signal_history) > 1440:
                    self._signal_history = self._signal_history[-1440:]
                found = False
                for net in self._known_networks:
                    if net.get("ssid") == info["ssid"]:
                        net["last_seen"] = entry["timestamp"]
                        net["connections"] = net.get("connections", 0) + 1
                        found = True
                        break
                if not found:
                    self._known_networks.append({"ssid": info["ssid"], "first_seen": entry["timestamp"], "last_seen": entry["timestamp"], "connections": 1})
                self._save_data()
        except Exception as e:
            self.logger.error(f"WiFi poll error: {e}")

    def _api_status(self):
        from flask import jsonify
        info = self._get_wifi_info()
        if info.get("signal_dbm"):
            info["quality"] = self._signal_quality(info["signal_dbm"])
        return jsonify(info)

    def _api_scan(self):
        from flask import jsonify
        try:
            self.controller._shell("cmd", "wifi", "start-scan")
            import time; time.sleep(3)
            out = self.controller._shell("cmd", "wifi", "list-scan-results")
            return jsonify(parse_scan_results(out))
        except Exception as e:
            return jsonify({"error": str(e)})

    def _api_known(self):
        from flask import jsonify
        return jsonify(self._known_networks)

    def _api_signal(self):
        from flask import request, jsonify
        minutes = int(request.args.get("minutes", 60))
        cutoff = max(0, len(self._signal_history) - minutes)
        data = self._signal_history[cutoff:]
        return jsonify({
            "history": data,
            "current_signal": data[-1]["signal_dbm"] if data else 0,
            "avg_signal": sum(d["signal_dbm"] for d in data) / len(data) if data else 0,
            "band": "5GHz" if data and data[-1].get("frequency", 0) > 5000 else "2.4GHz"
        })

    def _api_security_audit(self):
        from flask import jsonify
        info = self._get_wifi_info()
        issues = []
        if not info.get("ssid"):
            return jsonify({"connected": False, "issues": []})
        sig = info.get("signal_dbm", 0)
        if sig < -80:
            issues.append({"type": "weak_signal", "severity": "warning", "message": f"Senal debil: {sig} dBm"})
        freq = info.get("frequency", 0)
        if freq and freq < 5000:
            issues.append({"type": "2ghz_band", "severity": "info", "message": "Banda 2.4GHz"})
        return jsonify({"connected": True, "ssid": info.get("ssid"), "issues": issues, "score": max(0, 100 - len(issues) * 25)})

    def _api_toggle(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        state = data.get("state")
        if state is not None:
            val = "enable" if state in ["on", True] else "disable"
            self.controller._shell("svc", "wifi", val)
        return jsonify({"ok": True})

    def _api_connect(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        ssid = data.get("ssid", "")
        if not isinstance(ssid, str) or not ssid or len(ssid.encode("utf-8")) > 32:
            return jsonify({"ok": False, "error": "invalid ssid"}), 400
        self.controller._shell("cmd", "wifi", "connect-network", shlex.quote(ssid))
        return jsonify({"ok": True})

    def _api_forget(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        ssid = data.get("ssid", "")
        if not isinstance(ssid, str) or not ssid or len(ssid.encode("utf-8")) > 32:
            return jsonify({"ok": False, "error": "invalid ssid"}), 400
        self.controller._shell("cmd", "wifi", "forget-network", shlex.quote(ssid))
        return jsonify({"ok": True})


plugin_class = WiFiIntelligencePlugin
