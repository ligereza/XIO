"""
Example Tool Plugin – Demonstrates integration with an external Xiaomi repo/agent.

This plugin serves as a template for connecting an external codebase (e.g. a GitHub
repo adapted by another agent) to the Xiaomi Controller plugin system.

Integration patterns:
1. Direct: Import classes from the external repo
2. Adapter: Wrap external API calls
3. Bridge: Subprocess calls to external tools

Replace the placeholder implementation with actual integration code.
"""

from plugins.base import PluginBase


class ExampleToolPlugin(PluginBase):
    plugin_id = "example_tool"
    name = "Xiaomi Enhanced Control"
    version = "0.1.0"
    description = "Bridge for external Xiaomi ADB extensions"
    author = "External Agent"
    icon = "cpu"
    category = "system"
    permissions = ["system", "input"]

    def on_load(self):
        # Register routes
        self.register_route("/info", self._api_info, methods=["GET"])
        self.register_route("/features", self._api_features, methods=["GET"])
        self.register_route("/execute", self._api_execute, methods=["POST"])
        self.logger.info("Example Tool plugin loaded (placeholder)")

    def _api_info(self):
        """Return info about the external integration."""
        from flask import jsonify
        return jsonify({
            "plugin": "example_tool",
            "status": "placeholder",
            "message": "Replace this with your external repo integration",
            "external_repo": "https://github.com/your-user/your-xiaomi-repo",
            "available_features": [
                "game_turbo_control",
                "display_profiles",
                "thermal_management",
                "miui_specific",
            ],
        })

    def _api_features(self):
        """List available features from the external integration."""
        from flask import jsonify
        return jsonify({
            "features": [
                {"id": "game_turbo", "name": "Game Turbo", "enabled": False},
                {"id": "display_profile", "name": "Display Profiles", "enabled": False},
                {"id": "thermal", "name": "Thermal Management", "enabled": False},
            ]
        })

    def _api_execute(self):
        """Execute a feature command from the external integration."""
        from flask import request, jsonify
        data = request.get_json(force=True)
        feature = data.get("feature", "")
        action = data.get("action", "")
        params = data.get("params", {})

        # ── Replace this with actual external repo integration ──
        # Example patterns:
        #
        # Pattern 1: Direct import
        # from external_repo import XiaomiEnhancer
        # enhancer = XiaomiEnhancer(self.controller)
        # result = enhancer.execute(feature, action, params)
        #
        # Pattern 2: Subprocess
        # import subprocess
        # result = subprocess.run(["python", "-m", "external_tool", feature, action],
        #                        capture_output=True)
        #
        # Pattern 3: ADB commands specific to Xiaomi
        # self.controller._shell("miui_specific_command", action)

        return jsonify({
            "ok": True,
            "feature": feature,
            "action": action,
            "result": "placeholder – implement your integration here",
            "hint": "See source code for integration patterns",
        })


plugin_class = ExampleToolPlugin
