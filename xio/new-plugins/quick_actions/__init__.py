"""
Quick Actions Hub – Toggles rápidos vía ADB.
Flashlight, auto-rotate, DND, data, hotspot, timeout, night mode, media, clipboard, airplane.
"""

from plugins.base import PluginBase


class QuickActionsPlugin(PluginBase):
    plugin_id = "quick_actions"
    name = "Quick Actions Hub"
    version = "1.0.0"
    description = "Toggles rápidos sin root"
    author = "Arena Agent"
    icon = "automation"
    category = "system"
    permissions = ["system", "input"]

    def on_load(self):
        self.register_route("/actions", self._api_list_actions, methods=["GET"])
        self.register_route("/flashlight", self._api_flashlight, methods=["POST"])
        self.register_route("/rotate", self._api_rotate, methods=["POST"])
        self.register_route("/dnd", self._api_dnd, methods=["POST"])
        self.register_route("/data", self._api_data, methods=["POST"])
        self.register_route("/hotspot", self._api_hotspot, methods=["POST"])
        self.register_route("/timeout", self._api_timeout, methods=["POST"])
        self.register_route("/night-mode", self._api_night_mode, methods=["POST"])
        self.register_route("/media", self._api_media, methods=["POST"])
        self.register_route("/clipboard/clear", self._api_clear_clipboard, methods=["POST"])
        self.register_route("/airplane", self._api_airplane, methods=["POST"])
        self.register_route("/battery-saver", self._api_battery_saver, methods=["POST"])
        self.register_route("/wifi", self._api_wifi, methods=["POST"])
        self.register_route("/bluetooth", self._api_bluetooth, methods=["POST"])
        self.register_route("/status", self._api_status, methods=["GET"])
        self.logger.info("Quick Actions Hub loaded")

    def _shell(self, *args):
        try:
            return self.controller._shell(*args)
        except Exception as e:
            self.logger.error(f"Shell error: {e}")
            return ""

    def _get_setting(self, scope, key):
        return self._shell("settings", "get", scope, key).strip()

    def _set_setting(self, scope, key, value):
        return self._shell("settings", "put", scope, key, str(value))

    # ── API ──────────────────────────────────────────────────────────
    def _api_list_actions(self):
        from flask import jsonify
        return jsonify({
            "flashlight": "Toggle linterna",
            "rotate": "Auto-rotate on/off",
            "dnd": "Do Not Disturb modes",
            "data": "Mobile data on/off",
            "hotspot": "WiFi hotspot on/off",
            "timeout": "Screen timeout",
            "night-mode": "Night mode on/off",
            "media": "Media controls",
            "clipboard/clear": "Clear clipboard",
            "airplane": "Airplane mode",
            "battery-saver": "Battery saver",
            "wifi": "WiFi toggle",
            "bluetooth": "Bluetooth toggle"
        })

    def _api_flashlight(self):
        from flask import request, jsonify
        data = request.get_json(force=True) if request.data else {}
        state = data.get("state", "toggle")  # on, off, toggle
        
        current = self._get_setting("system", "flashlight_enabled")
        if state == "toggle":
            new_state = "0" if current == "1" else "1"
        else:
            new_state = "1" if state == "on" else "0"
        
        # MIUI-specific
        self._set_setting("system", "flashlight_enabled", new_state)
        return jsonify({"ok": True, "state": "on" if new_state == "1" else "off"})

    def _api_rotate(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        state = data.get("state", "toggle")
        current = self._get_setting("system", "accelerometer_rotation")
        if state == "toggle":
            new = "0" if current == "1" else "1"
        else:
            new = "1" if state == "on" else "0"
        self._set_setting("system", "accelerometer_rotation", new)
        return jsonify({"ok": True, "auto_rotate": new == "1"})

    def _api_dnd(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        mode = data.get("mode", "off")  # off, priority, alarms, total
        mode_map = {"off": "0", "priority": "1", "alarms": "2", "total": "3"}
        zen_mode = mode_map.get(mode, "0")
        self._set_setting("global", "zen_mode", zen_mode)
        return jsonify({"ok": True, "dnd_mode": mode})

    def _api_data(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        state = data.get("state")
        if state is not None:
            val = "1" if state in ["on", True, 1] else "0"
            self._shell("svc", "data", val)
        return jsonify({"ok": True})

    def _api_hotspot(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        state = data.get("state")
        if state is not None:
            val = "enable" if state in ["on", True, 1] else "disable"
            # Tethering control
            self._shell("svc", "wifi", val if val == "enable" else "disable")
        return jsonify({"ok": True})

    def _api_timeout(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        seconds = data.get("seconds", 30)
        ms = seconds * 1000
        self._set_setting("system", "screen_off_timeout", str(ms))
        return jsonify({"ok": True, "timeout_seconds": seconds})

    def _api_night_mode(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        state = data.get("state", "toggle")
        # Night display / blue light filter
        if state == "toggle":
            current = self._get_setting("secure", "display_night_mode_enabled")
            new = "0" if current == "1" else "1"
        else:
            new = "1" if state == "on" else "0"
        self._set_setting("secure", "display_night_mode_enabled", new)
        return jsonify({"ok": True, "night_mode": new == "1"})

    def _api_media(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        action = data.get("action", "")  # play, pause, next, prev, volume_up, volume_down
        key_map = {
            "play": "KEYCODE_MEDIA_PLAY",
            "pause": "KEYCODE_MEDIA_PAUSE",
            "play_pause": "KEYCODE_MEDIA_PLAY_PAUSE",
            "next": "KEYCODE_MEDIA_NEXT",
            "prev": "KEYCODE_MEDIA_PREVIOUS",
            "stop": "KEYCODE_MEDIA_STOP",
        }
        if action in key_map:
            self._shell("input", "keyevent", key_map[action])
            return jsonify({"ok": True, "action": action})
        return jsonify({"error": "Invalid action"}), 400

    def _api_clear_clipboard(self):
        from flask import jsonify
        # Set clipboard to empty via service call
        self._shell("service", "call", "clipboard", "2")
        # Or set empty text
        self._shell("am", "broadcast", "-a", "clipper.set", "-e", "text", "")
        return jsonify({"ok": True, "message": "Clipboard cleared"})

    def _api_airplane(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        state = data.get("state")
        if state is not None:
            val = "1" if state in ["on", True, 1] else "0"
            self._set_setting("global", "airplane_mode_on", val)
            # Broadcast to apply
            self._shell("am", "broadcast", "-a", "android.intent.action.AIRPLANE_MODE",
                       "--ez", "state", val)
        return jsonify({"ok": True})

    def _api_battery_saver(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        state = data.get("state", "toggle")
        if state == "toggle":
            current = self._get_setting("global", "low_power")
            new = "0" if current == "1" else "1"
        else:
            new = "1" if state == "on" else "0"
        self._set_setting("global", "low_power", new)
        return jsonify({"ok": True, "battery_saver": new == "1"})

    def _api_wifi(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        state = data.get("state")
        if state is not None:
            val = "enable" if state in ["on", True, 1] else "disable"
            self._shell("svc", "wifi", val)
        return jsonify({"ok": True})

    def _api_bluetooth(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        state = data.get("state")
        if state is not None:
            val = "enable" if state in ["on", True, 1] else "disable"
            self._shell("svc", "bluetooth", val)
        return jsonify({"ok": True})

    def _api_status(self):
        from flask import jsonify
        return jsonify({
            "auto_rotate": self._get_setting("system", "accelerometer_rotation") == "1",
            "flashlight": self._get_setting("system", "flashlight_enabled") == "1",
            "dnd": self._get_setting("global", "zen_mode"),
            "night_mode": self._get_setting("secure", "display_night_mode_enabled") == "1",
            "battery_saver": self._get_setting("global", "low_power") == "1",
            "timeout_ms": self._get_setting("system", "screen_off_timeout"),
        })


plugin_class = QuickActionsPlugin
