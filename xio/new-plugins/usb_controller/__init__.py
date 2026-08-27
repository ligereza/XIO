"""
USB Controller – Control avanzado del modo USB.
MTP/PTP/Audio/MIDI, simular carga, bloquear datos, monitor.
"""

from plugins.base import PluginBase
import json


class USBControllerPlugin(PluginBase):
    plugin_id = "usb_controller"
    name = "USB Controller"
    version = "1.0.0"
    description = "Control avanzado de USB"
    author = "Arena Agent"
    icon = "system"
    category = "system"
    permissions = ["system"]

    USB_FUNCTIONS = {
        "none": "none",
        "mtp": "mtp",
        "ptp": "ptp",
        "rndis": "rndis",
        "rndis_mtp": "rndis,mtp",
        "audio_source": "audio_source",
        "midi": "midi",
        "mtp_adb": "mtp,adb",
        "ptp_adb": "ptp,adb",
    }

    def __init__(self, context):
        super().__init__(context)
        self._usb_log = []

    def on_load(self):
        self.register_route("/status", self._api_status, methods=["GET"])
        self.register_route("/set-function", self._api_set_function, methods=["POST"])
        self.register_route("/functions", self._api_list_functions, methods=["GET"])
        self.register_route("/data-toggle", self._api_data_toggle, methods=["POST"])
        self.register_route("/secure-mode", self._api_secure_mode, methods=["POST"])
        self.register_route("/charging-sim", self._api_charging_sim, methods=["POST"])
        self.register_route("/info", self._api_usb_info, methods=["GET"])
        self.register_route("/log", self._api_log, methods=["GET"])
        self.logger.info("USB Controller loaded")

    def _get_current_function(self):
        try:
            return self.controller._shell("getprop", "sys.usb.config").strip()
        except:
            return "unknown"

    def _set_function(self, func):
        try:
            self.controller._shell("svc", "usb", "setFunction", func)
            return True
        except Exception as e:
            self.logger.error(f"Error setting USB function: {e}")
            return False

    def _api_status(self):
        from flask import jsonify
        return jsonify({
            "current_function": self._get_current_function(),
            "usb_connected": self._is_usb_connected(),
            "data_enabled": self._is_data_enabled()
        })

    def _is_usb_connected(self):
        try:
            out = self.controller._shell("cat", "/sys/class/power_supply/usb/online")
            return out.strip() == "1"
        except:
            try:
                out = self.controller._shell("dumpsys", "usb")
                return "connected" in out.lower()
            except:
                return False

    def _is_data_enabled(self):
        try:
            func = self._get_current_function()
            return func not in ("none", "charging")
        except:
            return False

    def _api_set_function(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        func = data.get("function", "mtp")
        actual_func = self.USB_FUNCTIONS.get(func)
        if actual_func is None:
            return jsonify({"ok": False, "error": "unknown function"}), 400
        ok = self._set_function(actual_func)
        self._usb_log.append({"action": "set_function", "function": actual_func, "ok": ok})
        self._usb_log = self._usb_log[-100:]
        return jsonify({"ok": ok, "function": actual_func})

    def _api_list_functions(self):
        from flask import jsonify
        return jsonify(self.USB_FUNCTIONS)

    def _api_data_toggle(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        enabled = data.get("enabled", True)
        if enabled:
            ok = self._set_function("mtp")
        else:
            # Disable data, charging only
            try:
                self.controller._shell("setprop", "sys.usb.config", "none")
                ok = True
            except:
                ok = False
        self._usb_log.append({"action": "data_toggle", "enabled": enabled, "ok": ok})
        return jsonify({"ok": ok, "data_enabled": enabled})

    def _api_secure_mode(self):
        """Bloquea datos USB - solo carga."""
        from flask import jsonify
        try:
            self.controller._shell("settings", "put", "global", "adb_enabled", "0")
            self._set_function("none")
            self._usb_log.append({"action": "secure_mode", "ok": True})
            return jsonify({"ok": True, "message": "USB en modo solo carga (seguro)"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    def _api_charging_sim(self):
        """Simular estado de carga via USB."""
        from flask import request, jsonify
        data = request.get_json(force=True)
        state = data.get("state", "unplug")  # unplug, reset
        if state not in ("unplug", "reset"):
            return jsonify({"error": "invalid state"}), 400
        try:
            self.controller._shell("dumpsys", "battery", state)
            return jsonify({"ok": True, "state": state})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    def _api_usb_info(self):
        from flask import jsonify
        info = {
            "function": self._get_current_function(),
            "connected": self._is_usb_connected(),
        }
        try:
            out = self.controller._shell("dumpsys", "usb")
            info["raw"] = out[:2000]
        except:
            info["raw"] = ""
        try:
            speed = self.controller._shell("cat", "/sys/class/android_usb/android0/speed")
            info["speed"] = speed.strip()
        except:
            info["speed"] = "unknown"
        try:
            state = self.controller._shell("cat", "/sys/class/android_usb/android0/state")
            info["state"] = state.strip()
        except:
            pass
        return jsonify(info)

    def _api_log(self):
        from flask import jsonify
        return jsonify(self._usb_log[-50:])


plugin_class = USBControllerPlugin
