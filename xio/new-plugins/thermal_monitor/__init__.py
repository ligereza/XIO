"""
Thermal Monitor Pro – Monitoreo de temperatura por zonas.
"""

from plugins.base import PluginBase
import json
from datetime import datetime


class ThermalMonitorPlugin(PluginBase):
    plugin_id = "thermal_monitor"
    name = "Thermal Monitor Pro"
    version = "1.0.0"
    description = "Monitoreo termico por zonas"
    author = "Arena Agent"
    icon = "battery"
    category = "battery"
    permissions = ["system", "battery"]

    def __init__(self, context):
        super().__init__(context)
        self._history = []
        self._alerts = []
        self._max_history = 2880
        self._throttle_cache = None  # poblado por _read_thermal_zones (mismo batch)

    def on_load(self):
        self._load_history()
        self.register_route("/temperatures", self._api_temperatures, methods=["GET"])
        self.register_route("/history", self._api_history, methods=["GET"])
        self.register_route("/alerts", self._api_alerts, methods=["GET"])
        self.register_route("/zones", self._api_zones, methods=["GET"])
        self.register_route("/config", self._api_get_config, methods=["GET"])
        self.register_route("/config", self._api_set_config, methods=["POST"])
        self.context.schedule("thermal_poll", self._poll_temperatures, interval_seconds=30)
        self.logger.info("Thermal Monitor Pro loaded")

    def _load_history(self):
        f = self.data_dir / "thermal_history.json"
        if f.exists():
            try:
                self._history = json.loads(f.read_text())
            except:
                self._history = []

    def _save_history(self):
        f = self.data_dir / "thermal_history.json"
        f.write_text(json.dumps(self._history[-self._max_history:], indent=2))

    def _read_thermal_zones(self):
        zones = {}
        try:
            # ONE batched on-device shell call for every zone's path|type|temp
            # (+ throttle_state), en vez de ls + 2 cats por zona (~179 rish calls
            # seriados -> 1). Cada rish call se serializa en _shell_lock + hace el
            # file-redirect, asi que colapsarlas baja el poll de ~11s a ~4s. El
            # throttle viaja en el mismo batch y se cachea para _check_throttling
            # (siempre llamado justo despues). Semantica de claves preservada:
            # type si existe, si no zone{num}.
            cmd = ('for z in /sys/class/thermal/thermal_zone*; do '
                   'echo "Z|$z|$(cat $z/type 2>/dev/null)|$(cat $z/temp 2>/dev/null)"; done; '
                   'echo "T|$(cat /sys/class/thermal/thermal_zone0/throttle_state 2>/dev/null)"')
            out = self.controller._shell(cmd)
            self._throttle_cache = None
            for line in out.splitlines():
                if line.startswith("T|"):
                    tv = line[2:].strip()
                    self._throttle_cache = int(tv) if tv.isdigit() else None
                    continue
                if not line.startswith("Z|"):
                    continue
                parts = line[2:].split("|")
                if len(parts) < 3:
                    continue
                zpath, ztype, temp_raw = parts[0], parts[1].strip(), parts[2].strip()
                num = zpath.rsplit("thermal_zone", 1)[-1]
                if temp_raw and temp_raw.lstrip('-').isdigit():
                    temp_c = int(temp_raw) / 1000.0
                    zones[ztype or f"zone{num}"] = round(temp_c, 1)
        except Exception as e:
            self.logger.error(f"Error reading thermal zones: {e}")
        try:
            bat = self.controller.battery_status()
            if "temperature" in bat:
                zones["battery"] = bat["temperature"]
        except:
            pass
        return zones

    def _check_throttling(self):
        # Servido desde el cache poblado por _read_thermal_zones (mismo batch),
        # que siempre se llama justo antes -> 0 rish calls extra.
        return self._throttle_cache

    def _poll_temperatures(self):
        try:
            temps = self._read_thermal_zones()
            throttle = self._check_throttling()
            entry = {"timestamp": datetime.now().isoformat(), "temperatures": temps, "throttle_state": throttle}
            self._history.append(entry)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]
            self._save_history()
            threshold = self.get_config("alert_threshold", 40.0)
            for zone, temp in temps.items():
                if temp > threshold:
                    if not self._alerts or self._alerts[-1].get("zone") != zone:
                        self._alerts.append({"zone": zone, "temperature": temp, "threshold": threshold, "timestamp": entry["timestamp"]})
                        self._alerts = self._alerts[-50:]
        except Exception as e:
            self.logger.error(f"Thermal poll error: {e}")

    def _api_temperatures(self):
        from flask import jsonify
        return jsonify({"temperatures": self._read_thermal_zones(), "throttle_state": self._check_throttling(), "timestamp": datetime.now().isoformat()})

    def _api_history(self):
        from flask import request, jsonify
        minutes = int(request.args.get("minutes", 30))
        idx = max(0, len(self._history) - (minutes * 2))
        return jsonify(self._history[idx:])

    def _api_alerts(self):
        from flask import jsonify
        return jsonify(self._alerts[-20:])

    def _api_zones(self):
        from flask import jsonify
        try:
            # 1 batched shell call (was ls + 1 cat/type per zone).
            cmd = ('for z in /sys/class/thermal/thermal_zone*; do '
                   'echo "$(basename $z)|$(cat $z/type 2>/dev/null)"; done')
            out = self.controller._shell(cmd)
            zones = []
            for line in out.splitlines():
                name, _, zt = line.partition("|")
                name = name.strip()
                if name.startswith("thermal_zone"):
                    zones.append({"name": name, "type": zt.strip()})
            return jsonify(zones)
        except Exception as e:
            return jsonify({"error": str(e)})

    def _api_get_config(self):
        from flask import jsonify
        return jsonify({"alert_threshold": self.get_config("alert_threshold", 40.0)})

    def _api_set_config(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        if "alert_threshold" in data:
            self.set_config("alert_threshold", float(data["alert_threshold"]))
        return jsonify({"ok": True})


plugin_class = ThermalMonitorPlugin
