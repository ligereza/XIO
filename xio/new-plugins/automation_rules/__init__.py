"""
Automation Rules – Motor de reglas tipo Tasker-lite sin root.
Triggers: battery, time, wifi, app, notification.
Actions: tap, swipe, setting, open_app, force_stop, send_key, profile.
"""

from plugins.base import PluginBase
import json, time
from datetime import datetime


class AutomationRulesPlugin(PluginBase):
    plugin_id = "automation_rules"
    name = "Automation Rules"
    version = "1.0.0"
    description = "Motor de reglas con triggers y actions"
    author = "Arena Agent"
    icon = "automation"
    category = "automation"
    permissions = ["input", "system", "apps"]

    TRIGGER_TYPES = ["battery", "time", "wifi", "app_open", "notification", "manual"]
    ACTION_TYPES = ["tap", "swipe", "setting", "open_app", "force_stop", "key", "profile", "notification"]

    def __init__(self, context):
        super().__init__(context)
        self._rules = []
        self._execution_log = []
        self._last_state = {}

    def on_load(self):
        self._load_rules()
        self.register_route("/rules", self._api_list_rules, methods=["GET"])
        self.register_route("/rules", self._api_create_rule, methods=["POST"])
        self.register_route("/rules/<int:rule_id>", self._api_delete_rule, methods=["DELETE"])
        self.register_route("/rules/<int:rule_id>/toggle", self._api_toggle_rule, methods=["POST"])
        self.register_route("/rules/<int:rule_id>/test", self._api_test_rule, methods=["POST"])
        self.register_route("/log", self._api_log, methods=["GET"])
        self.register_route("/state", self._api_current_state, methods=["GET"])
        self.register_route("/examples", self._api_examples, methods=["GET"])
        # Evaluar reglas cada 15 segundos
        self.context.schedule("rules_eval", self._evaluate_rules, interval_seconds=15)
        self.logger.info("Automation Rules loaded")

    def _load_rules(self):
        rules_file = self.data_dir / "rules.json"
        if rules_file.exists():
            try:
                self._rules = json.loads(rules_file.read_text())
            except:
                self._rules = []

    def _save_rules(self):
        rules_file = self.data_dir / "rules.json"
        rules_file.write_text(json.dumps(self._rules, indent=2))

    def _get_state(self):
        """Obtener el estado actual del dispositivo para evaluar triggers."""
        state = {}
        try:
            bat = self.controller.battery_status()
            state["battery_level"] = bat.get("level", 100)
            state["charging"] = bat.get("charging", False)
        except:
            state["battery_level"] = 100
            state["charging"] = False
        try:
            net = self.controller.network_info()
            state["wifi_ssid"] = net.get("ssid", "")
            state["wifi_connected"] = bool(net.get("ip"))
        except:
            state["wifi_ssid"] = ""
            state["wifi_connected"] = False
        state["time"] = datetime.now().strftime("%H:%M")
        state["hour"] = datetime.now().hour
        state["minute"] = datetime.now().minute
        return state

    def _evaluate_trigger(self, trigger, state):
        """Evaluar si un trigger se cumple con el estado actual."""
        t_type = trigger.get("type")
        params = trigger.get("params", {})

        if t_type == "battery":
            level = state.get("battery_level", 100)
            op = params.get("operator", "below")
            threshold = params.get("level", 20)
            if op == "below": return level < threshold
            if op == "above": return level > threshold
            if op == "equals": return level == threshold
        elif t_type == "time":
            time_str = state.get("time", "00:00")
            rule_time = params.get("time", "00:00")
            return time_str == rule_str if isinstance(time_str, str) else False
        elif t_type == "wifi":
            ssid = state.get("wifi_ssid", "")
            expected = params.get("ssid", "")
            connected = state.get("wifi_connected", False)
            if params.get("connected") is not None:
                return connected == params.get("connected")
            return ssid == expected and connected
        elif t_type == "app_open":
            # TODO: detectar app en foreground (requiere dumpsys window)
            return False
        elif t_type == "manual":
            return params.get("triggered", False)
        return False

    def _execute_action(self, action):
        """Ejecutar una acción."""
        a_type = action.get("type")
        params = action.get("params", {})
        try:
            if a_type == "tap":
                self.controller.tap(params.get("x", 0), params.get("y", 0))
            elif a_type == "swipe":
                self.controller.swipe(params.get("x1"), params.get("y1"),
                                     params.get("x2"), params.get("y2"))
            elif a_type == "setting":
                scope = params.get("scope", "system")
                key = params.get("key", "")
                value = params.get("value", "")
                self.controller._shell("settings", "put", scope, key, str(value))
            elif a_type == "open_app":
                self.controller.open_app(params.get("package", ""))
            elif a_type == "force_stop":
                self.controller.force_stop(params.get("package", ""))
            elif a_type == "key":
                self.controller.named_key(params.get("key", ""))
            elif a_type == "notification":
                self.controller._shell("am", "broadcast", "-a",
                    "com.xiaomi.controller.RULE_TRIGGERED",
                    "--es", "message", params.get("message", ""))
            return True
        except Exception as e:
            self.logger.error(f"Action error: {e}")
            return False

    def _evaluate_rules(self):
        """Evaluar todas las reglas activas contra el estado actual."""
        if not self._rules:
            return
        state = self._get_state()
        for rule in self._rules:
            if not rule.get("enabled", True):
                continue
            triggers = rule.get("triggers", [])
            if not triggers:
                continue
            # Evaluar según el modo (AND/OR)
            mode = rule.get("mode", "all")
            results = [self._evaluate_trigger(t, state) for t in triggers]
            if mode == "all" and all(results):
                self._fire_rule(rule)
            elif mode == "any" and any(results):
                self._fire_rule(rule)
        self._last_state = state

    def _fire_rule(self, rule):
        """Ejecutar las acciones de una regla."""
        # Cooldown: no ejecutar si ya se ejecutó en los últimos N segundos
        cooldown = rule.get("cooldown_seconds", 60)
        last_fire = rule.get("last_fired", 0)
        if time.time() - last_fire < cooldown:
            return
        
        rule["last_fired"] = time.time()
        self._save_rules()
        
        for action in rule.get("actions", []):
            self._execute_action(action)
        
        self._execution_log.append({
            "rule_id": rule["id"],
            "rule_name": rule["name"],
            "timestamp": datetime.now().isoformat()
        })
        if len(self._execution_log) > 200:
            self._execution_log = self._execution_log[-200:]

    # ── API ──────────────────────────────────────────────────────────
    def _api_list_rules(self):
        from flask import jsonify
        return jsonify(self._rules)

    def _api_create_rule(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        rule = {
            "id": data.get("id", int(time.time() * 1000)),
            "name": data.get("name", "Untitled"),
            "description": data.get("description", ""),
            "triggers": data.get("triggers", []),
            "actions": data.get("actions", []),
            "mode": data.get("mode", "all"),
            "cooldown_seconds": data.get("cooldown_seconds", 60),
            "enabled": data.get("enabled", True),
            "last_fired": 0
        }
        existing = [r for r in self._rules if r["id"] != rule["id"]]
        existing.append(rule)
        self._rules = existing
        self._save_rules()
        return jsonify({"ok": True, "rule": rule})

    def _api_delete_rule(self, rule_id):
        from flask import jsonify
        self._rules = [r for r in self._rules if r["id"] != rule_id]
        self._save_rules()
        return jsonify({"ok": True})

    def _api_toggle_rule(self, rule_id):
        from flask import jsonify
        for r in self._rules:
            if r["id"] == rule_id:
                r["enabled"] = not r.get("enabled", True)
                self._save_rules()
                return jsonify({"ok": True, "enabled": r["enabled"]})
        return jsonify({"error": "Not found"}), 404

    def _api_test_rule(self, rule_id):
        from flask import jsonify
        rule = next((r for r in self._rules if r["id"] == rule_id), None)
        if not rule:
            return jsonify({"error": "Not found"}), 404
        results = []
        for action in rule.get("actions", []):
            results.append(self._execute_action(action))
        return jsonify({"ok": True, "executed": len(results), "results": results})

    def _api_log(self):
        from flask import jsonify
        return jsonify(self._execution_log[-50:])

    def _api_current_state(self):
        from flask import jsonify
        return jsonify(self._get_state())

    def _api_examples(self):
        from flask import jsonify
        return jsonify([
            {
                "name": "Battery Saver Auto",
                "description": "Activa battery saver cuando la batería baja de 20%",
                "triggers": [{"type": "battery", "params": {"operator": "below", "level": 20}}],
                "actions": [{"type": "setting", "params": {"scope": "global", "key": "low_power", "value": "1"}}]
            },
            {
                "name": "Night Mode",
                "description": "Reduce brillo a las 23:00",
                "triggers": [{"type": "time", "params": {"time": "23:00"}}],
                "actions": [{"type": "setting", "params": {"scope": "system", "key": "screen_brightness", "value": "30"}}]
            },
            {
                "name": "Home WiFi",
                "description": "Cuando me conecto al WiFi de casa, desactiva datos móviles",
                "triggers": [{"type": "wifi", "params": {"ssid": "MiCasa"}}],
                "actions": [{"type": "setting", "params": {"scope": "global", "key": "mobile_data", "value": "0"}}]
            }
        ])


plugin_class = AutomationRulesPlugin
