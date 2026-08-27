"""
Display Profiles – Perfiles predefinidos de pantalla con auto-switch.
Controla: brightness, resolution, refresh rate, night mode, DPI, timeout.
"""

from plugins.base import PluginBase
import json


class DisplayProfilesPlugin(PluginBase):
    plugin_id = "display_profiles"
    name = "Display Profiles"
    version = "1.0.0"
    description = "Perfiles de pantalla con auto-switch"
    author = "Arena Agent"
    icon = "system"
    category = "system"
    permissions = ["system"]

    # Perfiles predefinidos
    PROFILES = {
        "gaming": {
            "name": "🎮 Gaming",
            "description": "Alta performance para juegos",
            "settings": {
                "screen_brightness": ("system", "255"),
                "screen_brightness_mode": ("system", "0"),
                "user_refresh_rate": ("system", "120"),
                "display_density_forced": ("wm", "440"),
            },
            "actions": ["set_resolution_fhd"],
            "triggers": {"app_open": ["com.tencent.ig", "com.pubg.imobile", "com.garena.game.codm"]}
        },
        "reading": {
            "name": "📖 Reading",
            "description": "Modo lectura: baja resolución, brillo cálido",
            "settings": {
                "screen_brightness": ("system", "80"),
                "screen_brightness_mode": ("system", "0"),
                "user_refresh_rate": ("system", "60"),
            },
            "actions": ["enable_night_mode", "set_resolution_hd"],
            "triggers": {"app_open": ["com.amazon.kindle", "org.geometerplus.zlibrary.ui.android"]}
        },
        "sleep": {
            "name": "💤 Sleep",
            "description": "Modo nocturno: DND, brillo mínimo, night mode",
            "settings": {
                "screen_brightness": ("system", "5"),
                "screen_brightness_mode": ("system", "0"),
                "zen_mode": ("global", "2"),  # DND total
                "screen_off_timeout": ("system", "15000"),  # 15s
            },
            "actions": ["enable_night_mode"],
            "triggers": {"time": "23:00"}
        },
        "battery": {
            "name": "🔋 Battery Saver",
            "description": "Máxima duración de batería",
            "settings": {
                "screen_brightness": ("system", "100"),
                "screen_brightness_mode": ("system", "0"),
                "user_refresh_rate": ("system", "60"),
                "low_power": ("global", "1"),
                "screen_off_timeout": ("system", "30000"),
            },
            "actions": ["set_resolution_hd", "set_animations_half"],
            "triggers": {"battery_below": 20}
        },
        "normal": {
            "name": "⚡ Normal",
            "description": "Configuración estándar",
            "settings": {
                "screen_brightness_mode": ("system", "1"),  # Auto brightness
                "user_refresh_rate": ("system", "0"),  # Auto refresh
                "low_power": ("global", "0"),
                "screen_off_timeout": ("system", "30000"),
            },
            "actions": ["disable_night_mode", "set_animations_normal"],
            "triggers": {}
        }
    }

    def __init__(self, context):
        super().__init__(context)
        self._current_profile = "normal"
        self._auto_switch = True

    def on_load(self):
        self._load_state()
        self.register_route("/profiles", self._api_list_profiles, methods=["GET"])
        self.register_route("/profiles/apply", self._api_apply_profile, methods=["POST"])
        self.register_route("/profiles/current", self._api_current_profile, methods=["GET"])
        self.register_route("/profiles/custom", self._api_custom_profile, methods=["POST"])
        self.register_route("/auto-switch", self._api_toggle_auto, methods=["POST"])
        self.register_route("/auto-switch/status", self._api_auto_status, methods=["GET"])
        # Auto-switch evaluation
        self.context.schedule("profile_eval", self._evaluate_auto_switch, interval_seconds=30)
        self.logger.info("Display Profiles loaded")

    def _load_state(self):
        state_file = self.data_dir / "state.json"
        if state_file.exists():
            try:
                state = json.loads(state_file.read_text())
                self._current_profile = state.get("profile", "normal")
                self._auto_switch = state.get("auto_switch", True)
            except:
                pass

    def _save_state(self):
        state_file = self.data_dir / "state.json"
        state_file.write_text(json.dumps({
            "profile": self._current_profile,
            "auto_switch": self._auto_switch
        }, indent=2))

    def _apply_setting(self, key, scope, value):
        """Aplicar un setting de display."""
        try:
            if scope == "wm":
                if "density" in key:
                    self.controller._shell("wm", "density", str(value))
                elif "refresh" in key:
                    self.controller._shell("wm", "set-user-refresh-rate", str(value))
            else:
                self.controller._shell("settings", "put", scope, key, str(value))
            return True
        except Exception as e:
            self.logger.error(f"Error applying {key}: {e}")
            return False

    def _apply_action(self, action):
        """Ejecutar una acción especial."""
        try:
            if action == "enable_night_mode":
                self.controller._shell("cmd", "night_mode", "enable")
            elif action == "disable_night_mode":
                self.controller._shell("cmd", "night_mode", "disable")
            elif action == "set_resolution_fhd":
                self.controller._shell("wm", "size", "1080x2400")
            elif action == "set_resolution_hd":
                self.controller._shell("wm", "size", "720x1600")
            elif action == "set_animations_half":
                self._apply_setting("window_animation_scale", "global", "0.5")
                self._apply_setting("transition_animation_scale", "global", "0.5")
            elif action == "set_animations_normal":
                self._apply_setting("window_animation_scale", "global", "1.0")
                self._apply_setting("transition_animation_scale", "global", "1.0")
            return True
        except Exception as e:
            self.logger.error(f"Error in action {action}: {e}")
            return False

    def apply_profile(self, profile_name):
        """Aplicar un perfil completo."""
        if profile_name not in self.PROFILES:
            return False
        profile = self.PROFILES[profile_name]
        results = {"settings": {}, "actions": []}
        
        # Apply settings
        for key, (scope, value) in profile.get("settings", {}).items():
            success = self._apply_setting(key, scope, value)
            results["settings"][key] = success
        
        # Apply actions
        for action in profile.get("actions", []):
            success = self._apply_action(action)
            results["actions"].append({"action": action, "success": success})
        
        self._current_profile = profile_name
        self._save_state()
        return True, results

    def _evaluate_auto_switch(self):
        """Evaluar triggers para auto-switch."""
        if not self._auto_switch:
            return
        
        state = {}
        try:
            bat = self.controller.battery_status()
            state["battery_level"] = bat.get("level", 100)
            state["charging"] = bat.get("charging", False)
        except:
            return
        
        # Battery trigger
        for name, profile in self.PROFILES.items():
            triggers = profile.get("triggers", {})
            if "battery_below" in triggers and not state.get("charging"):
                if state["battery_level"] < triggers["battery_below"]:
                    if self._current_profile != name:
                        self.apply_profile(name)
                        self.logger.info(f"Auto-switched to {name} (battery)")
                    return
        
        # Reset to normal if charging and above 80%
        if state.get("charging") and state.get("battery_level", 0) > 80:
            if self._current_profile == "battery":
                self.apply_profile("normal")
                self.logger.info("Auto-switched to normal (charging)")

    # ── API ──────────────────────────────────────────────────────────
    def _api_list_profiles(self):
        from flask import jsonify
        profiles = []
        for name, data in self.PROFILES.items():
            profiles.append({
                "id": name,
                "name": data["name"],
                "description": data["description"],
                "settings": list(data.get("settings", {}).keys()),
                "actions": data.get("actions", []),
                "active": name == self._current_profile
            })
        return jsonify(profiles)

    def _api_apply_profile(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        profile_name = data.get("profile", "")
        if profile_name not in self.PROFILES:
            return jsonify({"error": "Profile not found"}), 404
        success, results = self.apply_profile(profile_name)
        return jsonify({"ok": success, "profile": profile_name, "results": results})

    def _api_current_profile(self):
        from flask import jsonify
        profile = self.PROFILES.get(self._current_profile, {})
        return jsonify({
            "id": self._current_profile,
            "name": profile.get("name", "Unknown"),
            "description": profile.get("description", "")
        })

    def _api_custom_profile(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        name = data.get("name", "custom")
        settings = data.get("settings", {})
        
        results = {}
        for key, value in settings.items():
            scope = value.get("scope", "system")
            val = value.get("value", "")
            success = self._apply_setting(key, scope, val)
            results[key] = success
        
        return jsonify({"ok": True, "applied": results})

    def _api_toggle_auto(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        self._auto_switch = data.get("enabled", True)
        self._save_state()
        return jsonify({"ok": True, "auto_switch": self._auto_switch})

    def _api_auto_status(self):
        from flask import jsonify
        return jsonify({
            "auto_switch": self._auto_switch,
            "current_profile": self._current_profile
        })


plugin_class = DisplayProfilesPlugin
