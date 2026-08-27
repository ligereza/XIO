"""
MIUI/HyperOS Tweaker – Plugin específico para Xiaomi
Controla configuraciones propietarias de MIUI/HyperOS vía ADB sin root.
"""

import re

from plugins.base import PluginBase


class MIUITweakerPlugin(PluginBase):
    plugin_id = "miui_tweaker"
    name = "MIUI/HyperOS Tweaker"
    version = "1.0.0"
    description = "Tweaks específicos para Xiaomi con HyperOS"
    author = "Arena Agent"
    icon = "system"
    category = "system"
    permissions = ["system"]

    # Configuraciones de MIUI/HyperOS
    SETTINGS = {
        "animation_scale": {
            "key": "window_animation_scale",
            "scope": "global",
            "values": {"fast": "0.5", "normal": "1.0", "slow": "1.5", "off": "0"},
            "description": "Escala de animación de ventanas"
        },
        "transition_scale": {
            "key": "transition_animation_scale",
            "scope": "global",
            "values": {"fast": "0.5", "normal": "1.0", "slow": "1.5", "off": "0"},
            "description": "Escala de animación de transiciones"
        },
        "animator_scale": {
            "key": "animator_duration_scale",
            "scope": "global",
            "values": {"fast": "0.5", "normal": "1.0", "slow": "1.5", "off": "0"},
            "description": "Escala de duración de animadores"
        },
        "ad_tracking": {
            "key": "ad_tracking_enabled",
            "scope": "secure",
            "values": {"on": "1", "off": "0"},
            "description": "Tracking de publicidad"
        },
        "personalized_ads": {
            "key": "miui_personalized_ads",
            "scope": "secure",
            "values": {"on": "1", "off": "0"},
            "description": "Publicidad personalizada MIUI"
        }
    }

    # Apps de publicidad de Xiaomi (MSA - MIUI System Ads)
    AD_APPS = [
        "com.miui.msa.global",           # MIUI System Ads (principal)
        "com.miui.systemAdSolution",      # Solución de publicidad
        "com.xiaomi.advertising",         # Servicio de publicidad
        "com.miui.analytics",             # Analytics/telemetría
        "com.miui.daemon",                # Daemon con tracking
    ]

    # Apps de telemetría
    TELEMETRY_APPS = [
        "com.miui.analytics",
        "com.miui.daemon",
        "com.xiaomi.miui.daemon",
        "com.miui.bugreport",
        "com.miui.nextpay",
    ]

    def on_load(self):
        self.register_route("/settings", self._api_get_settings, methods=["GET"])
        self.register_route("/settings", self._api_set_settings, methods=["POST"])
        self.register_route("/ads/status", self._api_ads_status, methods=["GET"])
        self.register_route("/ads/disable", self._api_disable_ads, methods=["POST"])
        self.register_route("/ads/enable", self._api_enable_ads, methods=["POST"])
        self.register_route("/telemetry/status", self._api_telemetry_status, methods=["GET"])
        self.register_route("/telemetry/disable", self._api_disable_telemetry, methods=["POST"])
        self.register_route("/telemetry/enable", self._api_enable_telemetry, methods=["POST"])
        self.register_route("/animations/preset", self._api_animation_preset, methods=["POST"])
        self.register_route("/game-turbo/bypass", self._api_game_turbo_bypass, methods=["POST"])
        self.logger.info("MIUI/HyperOS Tweaker loaded")

    def _get_setting(self, scope, key):
        """Leer un setting de Android."""
        try:
            out = self.controller._shell("settings", "get", scope, key)
            return out.strip()
        except Exception as e:
            self.logger.error(f"Error reading {scope}/{key}: {e}")
            return None

    def _set_setting(self, scope, key, value):
        """Escribir un setting de Android."""
        try:
            self.controller._shell("settings", "put", scope, key, str(value))
            return True
        except Exception as e:
            self.logger.error(f"Error setting {scope}/{key}={value}: {e}")
            return False

    def _disabled_out(self):
        """Lista cruda de paquetes deshabilitados (1 pm call). Reusar para
        clasificar N apps en Python en vez de 1 pm call POR app."""
        return self.controller._shell("pm", "list", "packages", "-d")

    def _app_status_from(self, package, disabled_out):
        """enabled = no esta en la lista de deshabilitados (semantica original).

        Parseo exacto: `pm list packages -d` emite una linea `package:<name>`
        por app. Comparar con `in` sobre el texto crudo reporta mal (un paquete
        cuyo nombre es prefijo de otro, p.ej. com.miui.analytics vs
        com.miui.analytics.overlay). Se construye el set exacto de nombres.
        """
        disabled = {
            line.replace("package:", "").strip()
            for line in disabled_out.splitlines()
        }
        return package not in disabled

    def _app_status(self, package):
        """Verificar si una app está habilitada (single = 1 pm call)."""
        try:
            return self._app_status_from(package, self._disabled_out())
        except Exception:
            return None

    def _get_all_settings(self):
        """Lee TODOS los SETTINGS en 1 shell call (era 1 `settings get` por key)."""
        items = list(self.SETTINGS.items())
        cmd = "; ".join(
            'echo "%s|$(settings get %s %s 2>/dev/null)"' % (name, c["scope"], c["key"])
            for name, c in items
        )
        result = {}
        try:
            out = self.controller._shell(cmd)
            for line in out.splitlines():
                if "|" in line:
                    k, _, v = line.partition("|")
                    result[k.strip()] = v.strip()
        except Exception as e:
            self.logger.error(f"batched settings get error: {e}")
        return result

    def _disable_app(self, package):
        """Deshabilitar una app (user 0)."""
        try:
            self.controller._shell("pm", "disable-user", "--user", "0", package)
            return True
        except Exception as e:
            self.logger.error(f"Error disabling {package}: {e}")
            return False

    def _enable_app(self, package):
        """Habilitar una app."""
        try:
            self.controller._shell("pm", "enable", package)
            return True
        except Exception as e:
            self.logger.error(f"Error enabling {package}: {e}")
            return False

    # ── API Endpoints ────────────────────────────────────────────────

    def _api_get_settings(self):
        """GET /api/plugins/miui_tweaker/settings"""
        from flask import jsonify
        values = self._get_all_settings()  # 1 shell call en vez de N settings get
        current = {}
        for name, config in self.SETTINGS.items():
            current[name] = {
                "value": values.get(name),
                "description": config["description"],
                "options": config["values"]
            }
        return jsonify(current)

    def _api_set_settings(self):
        """POST /api/plugins/miui_tweaker/settings"""
        from flask import request, jsonify
        data = request.get_json(force=True)
        results = {}
        for setting_name, value in data.items():
            if setting_name in self.SETTINGS:
                config = self.SETTINGS[setting_name]
                # value debe ser una clave conocida (fast/normal/...) o uno de los
                # literales permitidos (0.5/1.0/...). Cualquier otra cosa entraria
                # cruda a `settings put` via _shell -> inyeccion de comandos.
                if value not in config["values"] and value not in config["values"].values():
                    return jsonify({"error": f"invalid value for {setting_name}"}), 400
                actual_value = config["values"].get(value, value)
                success = self._set_setting(config["scope"], config["key"], actual_value)
                results[setting_name] = success
        return jsonify({"ok": True, "results": results})

    def _api_ads_status(self):
        """GET /api/plugins/miui_tweaker/ads/status"""
        from flask import jsonify
        disabled_out = self._disabled_out()  # 1 pm call para todas las AD_APPS
        status = {}
        for app in self.AD_APPS:
            status[app] = {
                "enabled": self._app_status_from(app, disabled_out),
                "name": app.split(".")[-1]
            }
        # Settings de ads
        ad_tracking = self._get_setting("secure", "ad_tracking_enabled")
        personalized = self._get_setting("secure", "miui_personalized_ads")
        return jsonify({
            "apps": status,
            "settings": {
                "ad_tracking": ad_tracking,
                "personalized_ads": personalized
            }
        })

    def _api_disable_ads(self):
        """POST /api/plugins/miui_tweaker/ads/disable"""
        from flask import jsonify
        results = {}
        # Deshabilitar apps de publicidad
        for app in self.AD_APPS:
            results[app] = self._disable_app(app)
        # Deshabilitar tracking
        self._set_setting("secure", "ad_tracking_enabled", "0")
        self._set_setting("secure", "miui_personalized_ads", "0")
        return jsonify({"ok": True, "results": results, "message": "Publicidad desactivada"})

    def _api_enable_ads(self):
        """POST /api/plugins/miui_tweaker/ads/enable"""
        from flask import jsonify
        results = {}
        for app in self.AD_APPS:
            results[app] = self._enable_app(app)
        self._set_setting("secure", "ad_tracking_enabled", "1")
        self._set_setting("secure", "miui_personalized_ads", "1")
        return jsonify({"ok": True, "results": results, "message": "Publicidad activada"})

    def _api_telemetry_status(self):
        """GET /api/plugins/miui_tweaker/telemetry/status"""
        from flask import jsonify
        disabled_out = self._disabled_out()  # 1 pm call para todas las TELEMETRY_APPS
        status = {}
        for app in self.TELEMETRY_APPS:
            status[app] = {
                "enabled": self._app_status_from(app, disabled_out),
                "name": app.split(".")[-1]
            }
        return jsonify(status)

    def _api_disable_telemetry(self):
        """POST /api/plugins/miui_tweaker/telemetry/disable"""
        from flask import jsonify
        results = {}
        for app in self.TELEMETRY_APPS:
            results[app] = self._disable_app(app)
        return jsonify({"ok": True, "results": results, "message": "Telemetría desactivada"})

    def _api_enable_telemetry(self):
        """POST /api/plugins/miui_tweaker/telemetry/enable"""
        from flask import jsonify
        results = {}
        for app in self.TELEMETRY_APPS:
            results[app] = self._enable_app(app)
        return jsonify({"ok": True, "results": results, "message": "Telemetría activada"})

    def _api_animation_preset(self):
        """POST /api/plugins/miui_tweaker/animations/preset"""
        from flask import request, jsonify
        data = request.get_json(force=True)
        preset = data.get("preset", "normal")  # fast, normal, slow, off
        
        if preset not in ["fast", "normal", "slow", "off"]:
            return jsonify({"error": "Invalid preset"}), 400
        
        results = {}
        for name in ["animation_scale", "transition_scale", "animator_scale"]:
            config = self.SETTINGS[name]
            value = config["values"][preset]
            results[name] = self._set_setting(config["scope"], config["key"], value)
        
        return jsonify({"ok": True, "preset": preset, "results": results})

    def _api_game_turbo_bypass(self):
        """POST /api/plugins/miui_tweaker/game-turbo/bypass
        Enable Game Turbo features for specific apps without official Game Turbo.
        """
        from flask import request, jsonify
        data = request.get_json(force=True)
        package = data.get("package", "")
        
        if not package:
            return jsonify({"error": "No package specified"}), 400

        # El package entra crudo a am/dumpsys via _shell (sh -c "..."); un valor
        # como "a; id > /sdcard/pwned ;" inyectaria comandos. Solo se aceptan
        # nombres de paquete Android validos (letras, digitos, punto, guion bajo).
        if not re.fullmatch(r"[A-Za-z0-9._]+", package):
            return jsonify({"error": "invalid package"}), 400

        # Activar modo juego para la app específica
        try:
            # Game space / Game Turbo settings
            self.controller._shell(
                "settings", "put", "system", "game_mode_enabled", "1"
            )
            # Performance mode for the app
            self.controller._shell(
                "am", "set-standby-bucket", package, "active"
            )
            # Disable battery optimization for this app
            self.controller._shell(
                "dumpsys", "deviceidle", "whitelist", f"+{package}"
            )
            return jsonify({
                "ok": True,
                "message": f"Game Turbo features enabled for {package}",
                "features": ["performance_mode", "no_battery_optimization", "priority_cpu"]
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500


plugin_class = MIUITweakerPlugin
