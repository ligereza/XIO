"""
[Plugin Name] – Template for Xiaomi Controller plugins.

Replace this docstring with a description of your plugin.
Rename this folder and update plugin_id below.
"""

from plugins.base import PluginBase


class MyPlugin(PluginBase):
    """
    Template plugin. Copy this folder, rename it, and customize.
    
    Available in self:
        self.controller      → XiaomiController instance (tap, swipe, text, etc.)
        self.logger           → Logger (self.logger.info/warning/error)
        self.data_dir         → Persistent data directory for this plugin
        self.context.schedule → Schedule background tasks
    """
    
    # ── Metadata (also in manifest.json, this is fallback) ──────────
    plugin_id = "my_plugin"       # Must match folder name
    name = "My Plugin"
    version = "1.0.0"
    description = "Describe your plugin"
    author = "Your Name"
    icon = "puzzle"               # battery | cpu | puzzle | network | automation | file | system
    category = "general"          # general | automation | system | file | network | battery
    permissions = ["input"]       # battery | files | apps | input | network | system

    def on_load(self):
        """
        Called once when plugin is loaded.
        Register your API routes here.
        Routes are auto-prefixed: /api/plugins/<plugin_id>/...
        """
        self.register_route("/info", self._api_info, methods=["GET"])
        self.register_route("/action", self._api_action, methods=["POST"])
        self.register_route("/config", self._api_get_config, methods=["GET"])
        self.register_route("/config", self._api_set_config, methods=["POST"])
        
        # Optional: start a background task
        # self.context.schedule("my_loop", self._background_loop, interval_seconds=60)
        
        self.logger.info(f"{self.name} loaded successfully")

    def on_enable(self):
        """Called when user enables the plugin."""
        self.logger.info(f"{self.name} enabled")

    def on_disable(self):
        """Called when user disables the plugin."""
        self.logger.info(f"{self.name} disabled")

    def on_unload(self):
        """Called on server shutdown or plugin removal. Clean up here."""
        # self.context.cancel_schedule("my_loop")
        pass

    # ── API Handlers ─────────────────────────────────────────────────
    
    def _api_info(self):
        """GET /api/plugins/my_plugin/info"""
        from flask import jsonify
        return jsonify({
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "device_connected": self.controller.is_connected(),
        })

    def _api_action(self):
        """POST /api/plugins/my_plugin/action"""
        from flask import request, jsonify
        
        data = request.get_json(force=True)
        action = data.get("action", "")
        
        # Example: use the controller to interact with the device
        # self.controller.tap(540, 1200)
        # self.controller.swipe(540, 1800, 540, 600)
        # self.controller.named_key("home")
        # self.controller.text("hello")
        
        return jsonify({"ok": True, "action": action})

    def _api_get_config(self):
        """GET /api/plugins/my_plugin/config"""
        from flask import jsonify
        return jsonify(self._config)

    def _api_set_config(self):
        """POST /api/plugins/my_plugin/config"""
        from flask import request, jsonify
        data = request.get_json(force=True)
        for key, value in data.items():
            self.set_config(key, value)
        return jsonify({"ok": True, "config": self._config})

    # ── Background Tasks (optional) ──────────────────────────────────
    
    def _background_loop(self):
        """Runs every N seconds (set in on_load via context.schedule)."""
        try:
            status = self.controller.battery_status()
            # Do something with the data...
            self.logger.debug(f"Battery: {status}")
        except Exception as e:
            self.logger.error(f"Background task error: {e}")


# ══════════════════════════════════════════════════════════════════════
# REQUIRED: Export the plugin class
# ══════════════════════════════════════════════════════════════════════
plugin_class = MyPlugin
