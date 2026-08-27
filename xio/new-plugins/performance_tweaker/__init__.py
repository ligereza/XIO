"""
Performance Tweaker Pro – Tweaks de rendimiento para HyperOS/MIUI.
Fixed Performance Mode, touch latency zero, GPU vsync, multicore scheduler.
"""

from plugins.base import PluginBase
import json


class PerformanceTweakerPlugin(PluginBase):
    plugin_id = "performance_tweaker"
    name = "Performance Tweaker Pro"
    version = "1.0.0"
    description = "Tweaks de rendimiento avanzados"
    author = "Arena Agent"
    icon = "cpu"
    category = "system"
    permissions = ["system"]

    TWEAKS = {
        "fixed_perf_mode": {
            "cmd": "cmd power set-fixed-performance-mode-enabled {val}",
            "values": {"on": "true", "off": "false"},
            "description": "Modo rendimiento fijo (overclock sostenido)"
        },
        "long_press_timeout": {
            "scope": "secure", "key": "long_press_timeout",
            "values": {"fast": "150", "normal": "300", "slow": "500"},
            "description": "Tiempo de long press"
        },
        "multi_press_timeout": {
            "scope": "secure", "key": "multi_press_timeout",
            "values": {"fast": "150", "normal": "250", "slow": "500"},
            "description": "Timeout multi-press"
        },
        "tap_duration_threshold": {
            "scope": "secure", "key": "tap_duration_threshold",
            "values": {"zero": "0.0", "low": "0.1", "normal": "0.3"},
            "description": "Umbral de duracion de tap"
        },
        "touch_blocking_period": {
            "scope": "secure", "key": "touch_blocking_period",
            "values": {"zero": "0.0", "low": "100.0", "normal": "300.0"},
            "description": "Periodo de bloqueo de touch"
        },
        "force_opengl": {
            "type": "setprop", "key": "debug.force-opengl",
            "values": {"on": "1", "off": "0"},
            "description": "Forzar OpenGL rendering"
        },
        "gpu_vsync": {
            "type": "setprop", "key": "debug.hwc.force_gpu_vsync",
            "values": {"on": "1", "off": "0"},
            "description": "Forzar GPU vsync"
        },
        "ram_expand": {
            "scope": "global", "key": "ram_expand_size",
            "values": {"off": "0", "2gb": "2", "4gb": "4", "8gb": "8"},
            "description": "RAM expansion (memory extension)"
        },
        "multicore_scheduler": {
            "scope": "system", "key": "multicore_packet_scheduler",
            "values": {"on": "1", "off": "0"},
            "description": "Multicore packet scheduler"
        },
        "intelligent_sleep": {
            "scope": "system", "key": "intelligent_sleep_mode",
            "values": {"on": "1", "off": "0"},
            "description": "Adaptive sleep (desactivar = mas responsive)"
        },
        "adaptive_sleep": {
            "scope": "secure", "key": "adaptive_sleep",
            "values": {"on": "1", "off": "0"},
            "description": "Adaptive sleep (atencion a pantalla)"
        },
        "app_restriction": {
            "scope": "global", "key": "app_restriction_enabled",
            "values": {"on": "true", "off": "false"},
            "description": "Restriccion de apps"
        },
        "adaptive_battery": {
            "scope": "global", "key": "adaptive_battery_management_enabled",
            "values": {"on": "1", "off": "0"},
            "description": "Battery adaptativo (desactivar = mas responsive)"
        },
        "enhanced_cpu": {
            "scope": "global", "key": "sem_enhanced_cpu_responsiveness",
            "values": {"on": "1", "off": "0"},
            "description": "CPU responsiveness mejorada"
        },
        "refresh_rate_peak": {
            "scope": "system", "key": "peak_refresh_rate",
            "values": {"60": "60.0", "90": "90.0", "120": "120.0"},
            "description": "Refresh rate maximo"
        },
        "refresh_rate_min": {
            "scope": "system", "key": "min_refresh_rate",
            "values": {"60": "60.0", "90": "90.0", "120": "120.0"},
            "description": "Refresh rate minimo (lock)"
        },
        "window_blurs": {
            "scope": "global", "key": "disable_window_blurs",
            "values": {"on": "1", "off": "0"},
            "description": "Desactivar blurs (mejora rendimiento)"
        },
        "reduce_transparency": {
            "scope": "global", "key": "accessibility_reduce_transparency",
            "values": {"on": "1", "off": "0"},
            "description": "Reducir transparencia"
        },
        "activity_logging": {
            "scope": "global", "key": "activity_starts_logging_enabled",
            "values": {"on": "1", "off": "0"},
            "description": "Logging de activity starts"
        },
        "security_reports": {
            "scope": "system", "key": "send_security_reports",
            "values": {"on": "1", "off": "0"},
            "description": "Reportes de seguridad"
        },
    }

    PRESETS = {
        "gaming": {
            "name": "🎮 Gaming",
            "fixed_perf_mode": "true",
            "tap_duration_threshold": "0.0",
            "touch_blocking_period": "0.0",
            "multicore_scheduler": "1",
            "enhanced_cpu": "1",
            "refresh_rate_peak": "120.0",
            "refresh_rate_min": "120.0",
            "intelligent_sleep": "0",
            "adaptive_battery": "0",
            "ram_expand": "0"
        },
        "battery_saver": {
            "name": "🔋 Battery Saver",
            "fixed_perf_mode": "false",
            "refresh_rate_peak": "60.0",
            "refresh_rate_min": "60.0",
            "window_blurs": "1",
            "reduce_transparency": "1",
            "activity_logging": "0",
            "security_reports": "0",
            "adaptive_battery": "1",
            "intelligent_sleep": "1"
        },
        "responsive": {
            "name": "⚡ Ultra Responsive",
            "fixed_perf_mode": "true",
            "long_press_timeout": "150",
            "multi_press_timeout": "150",
            "tap_duration_threshold": "0.0",
            "touch_blocking_period": "0.0",
            "multicore_scheduler": "1",
            "enhanced_cpu": "1",
            "intelligent_sleep": "0",
            "adaptive_battery": "0",
            "adaptive_sleep": "0",
            "ram_expand": "0"
        },
        "normal": {
            "name": "⚙️ Normal",
            "fixed_perf_mode": "false",
            "long_press_timeout": "300",
            "multi_press_timeout": "250",
            "tap_duration_threshold": "0.3",
            "touch_blocking_period": "300.0",
            "refresh_rate_peak": "120.0",
            "refresh_rate_min": "60.0",
            "ram_expand": "4"
        }
    }

    def on_load(self):
        self.register_route("/tweaks", self._api_list_tweaks, methods=["GET"])
        self.register_route("/set", self._api_set_tweak, methods=["POST"])
        self.register_route("/presets", self._api_list_presets, methods=["GET"])
        self.register_route("/preset/apply", self._api_apply_preset, methods=["POST"])
        self.register_route("/status", self._api_status, methods=["GET"])
        self.register_route("/trim-cache", self._api_trim_cache, methods=["POST"])
        self.logger.info("Performance Tweaker loaded")

    def _set_tweak(self, name, value):
        if name not in self.TWEAKS:
            return False, "Unknown tweak"
        info = self.TWEAKS[name]
        try:
            if name == "fixed_perf_mode":
                self.controller._shell("cmd", "power", "set-fixed-performance-mode-enabled", value)
            elif info.get("type") == "setprop":
                self.controller._shell("setprop", info["key"], value)
            else:
                self.controller._shell("settings", "put", info["scope"], info["key"], str(value))
            return True, "OK"
        except Exception as e:
            return False, str(e)

    def _get_tweak(self, name):
        if name not in self.TWEAKS:
            return None
        info = self.TWEAKS[name]
        try:
            if name == "fixed_perf_mode":
                return None
            elif info.get("type") == "setprop":
                return self.controller._shell("getprop", info["key"]).strip()
            else:
                return self.controller._shell("settings", "get", info["scope"], info["key"]).strip()
        except:
            return None

    def _api_list_tweaks(self):
        from flask import jsonify
        return jsonify({k: {"description": v["description"], "values": v["values"]} for k, v in self.TWEAKS.items()})

    def _api_set_tweak(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        name = data.get("name", "")
        value = data.get("value", "")
        if name not in self.TWEAKS:
            return jsonify({"error": "Unknown tweak"}), 400
        allowed = set(str(x) for x in self.TWEAKS[name]["values"].values())
        if str(value) not in allowed:
            return jsonify({"error": "invalid value"}), 400
        ok, msg = self._set_tweak(name, value)
        return jsonify({"ok": ok, "message": msg})

    def _api_list_presets(self):
        from flask import jsonify
        return jsonify(self.PRESETS)

    def _api_apply_preset(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        preset = data.get("preset", "")
        if preset not in self.PRESETS:
            return jsonify({"error": "Unknown preset"}), 400
        results = {}
        for name, value in self.PRESETS[preset].items():
            if name in ("name",):
                continue
            ok, msg = self._set_tweak(name, value)
            results[name] = {"ok": ok, "value": value}
        return jsonify({"ok": True, "preset": preset, "results": results})

    def _get_all_tweaks(self):
        """Lee TODOS los tweaks en 1 shell call (era 1 getprop/settings por tweak)."""
        parts = []
        for name, info in self.TWEAKS.items():
            if name == "fixed_perf_mode":
                continue  # _get_tweak devuelve None para este
            if info.get("type") == "setprop":
                parts.append('echo "%s|$(getprop %s 2>/dev/null)"' % (name, info["key"]))
            else:
                parts.append('echo "%s|$(settings get %s %s 2>/dev/null)"'
                             % (name, info["scope"], info["key"]))
        result = {}
        try:
            out = self.controller._shell("; ".join(parts))
            for line in out.splitlines():
                if "|" in line:
                    k, _, v = line.partition("|")
                    result[k.strip()] = v.strip()
        except Exception as e:
            self.logger.error(f"batched tweaks read error: {e}")
        return result

    def _api_status(self):
        from flask import jsonify
        vals = self._get_all_tweaks()
        status = {name: (None if name == "fixed_perf_mode" else vals.get(name))
                  for name in self.TWEAKS}
        return jsonify(status)

    def _api_trim_cache(self):
        from flask import jsonify
        try:
            self.controller._shell("pm", "trim-caches", "4096G")
            self.controller._shell("pm", "art", "cleanup")
            self.controller._shell("sm", "fstrim")
            return jsonify({"ok": True, "message": "Cache trimmed, ART cleaned, fstrim done"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500


plugin_class = PerformanceTweakerPlugin
