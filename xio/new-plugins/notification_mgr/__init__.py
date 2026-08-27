"""
Notification Manager – Gestión avanzada de notificaciones vía dumpsys.
Leer, dismiss, historial, reglas de silenciamiento, auto-dismiss.
"""

from plugins.base import PluginBase
import json, re
from datetime import datetime


class NotificationMgrPlugin(PluginBase):
    plugin_id = "notification_mgr"
    name = "Notification Manager"
    version = "1.0.0"
    description = "Gestión de notificaciones sin root"
    author = "Arena Agent"
    icon = "system"
    category = "system"
    permissions = ["system", "apps"]

    def __init__(self, context):
        super().__init__(context)
        self._history = []
        self._rules = []

    def on_load(self):
        self._load_rules()
        self._load_history()
        self.register_route("/list", self._api_list, methods=["GET"])
        self.register_route("/dismiss", self._api_dismiss, methods=["POST"])
        self.register_route("/dismiss-all", self._api_dismiss_all, methods=["POST"])
        self.register_route("/dismiss-package", self._api_dismiss_package, methods=["POST"])
        self.register_route("/history", self._api_history, methods=["GET"])
        self.register_route("/history/clear", self._api_clear_history, methods=["POST"])
        self.register_route("/rules", self._api_list_rules, methods=["GET"])
        self.register_route("/rules", self._api_add_rule, methods=["POST"])
        self.register_route("/rules/<int:rule_id>", self._api_delete_rule, methods=["DELETE"])
        self.register_route("/scan", self._api_scan, methods=["POST"])
        self.context.schedule("notif_scan", self._background_scan, interval_seconds=60)
        self.logger.info("Notification Manager loaded")

    def _load_rules(self):
        f = self.data_dir / "rules.json"
        if f.exists():
            try: self._rules = json.loads(f.read_text())
            except: self._rules = []

    def _save_rules(self):
        (self.data_dir / "rules.json").write_text(json.dumps(self._rules, indent=2))

    def _load_history(self):
        f = self.data_dir / "history.json"
        if f.exists():
            try: self._history = json.loads(f.read_text())
            except: self._history = []

    def _save_history(self):
        (self.data_dir / "history.json").write_text(json.dumps(self._history[-500:], indent=2))

    def _parse_notifications(self):
        """Parse dumpsys notification para obtener notificaciones activas."""
        try:
            out = self.controller._shell("dumpsys", "notification", "--noredact")
            notifications = []
            current = {}
            for line in out.splitlines():
                line = line.rstrip()
                if "NotificationRecord" in line and "pkg=" in line:
                    if current:
                        notifications.append(current)
                    pkg_match = re.search(r'pkg=([\w.]+)', line)
                    current = {"package": pkg_match.group(1) if pkg_match else "unknown"}
                elif line.strip().startswith("tickerText="):
                    current["ticker"] = line.split("=", 1)[1].strip()
                elif line.strip().startswith("android.title="):
                    current["title"] = line.split("=", 1)[1].strip()
                elif line.strip().startswith("android.text="):
                    current["text"] = line.split("=", 1)[1].strip()
                elif "key=" in line and "0=" in line:
                    key_match = re.search(r'key=(\S+)', line)
                    if key_match:
                        current["key"] = key_match.group(1)
            if current:
                notifications.append(current)
            return notifications
        except Exception as e:
            self.logger.error(f"Error parsing notifications: {e}")
            return []

    def _dismiss_notification(self, key):
        """Dismiss una notificación específica."""
        try:
            self.controller._shell("notification", "cancel", key)
            return True
        except:
            return False

    def _dismiss_all(self):
        """Dismiss todas las notificaciones."""
        try:
            self.controller._shell("notification", "cancel_all")
            return True
        except:
            return False

    def _apply_rules(self, notifications):
        """Aplicar reglas de auto-dismiss."""
        import time
        for notif in notifications:
            pkg = notif.get("package", "")
            for rule in self._rules:
                if not rule.get("enabled", True):
                    continue
                if rule.get("package") and rule["package"] != pkg:
                    continue
                # Time-based rule
                if rule.get("time_start") and rule.get("time_end"):
                    now = datetime.now().strftime("%H:%M")
                    if rule["time_start"] <= now <= rule["time_end"]:
                        if notif.get("key"):
                            self._dismiss_notification(notif["key"])
                # Pattern-based rule
                if rule.get("pattern"):
                    text = (notif.get("text", "") + notif.get("title", "")).lower()
                    if re.search(rule["pattern"].lower(), text):
                        if notif.get("key"):
                            self._dismiss_notification(notif["key"])

    def _background_scan(self):
        """Scan periódico para aplicar reglas y guardar historial."""
        try:
            notifications = self._parse_notifications()
            self._apply_rules(notifications)
            # Save to history
            for n in notifications:
                entry = {**n, "timestamp": datetime.now().isoformat()}
                self._history.append(entry)
            if len(self._history) > 500:
                self._history = self._history[-500:]
            self._save_history()
        except Exception as e:
            self.logger.error(f"Background scan error: {e}")

    # ── API ──────────────────────────────────────────────────────────
    def _api_list(self):
        from flask import jsonify
        notifications = self._parse_notifications()
        return jsonify(notifications)

    def _api_dismiss(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        key = data.get("key", "")
        success = self._dismiss_notification(key)
        return jsonify({"ok": success})

    def _api_dismiss_all(self):
        from flask import jsonify
        success = self._dismiss_all()
        return jsonify({"ok": success})

    def _api_dismiss_package(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        package = data.get("package", "")
        notifications = self._parse_notifications()
        dismissed = 0
        for n in notifications:
            if n.get("package") == package and n.get("key"):
                if self._dismiss_notification(n["key"]):
                    dismissed += 1
        return jsonify({"ok": True, "dismissed": dismissed})

    def _api_history(self):
        from flask import jsonify
        return jsonify(self._history[-100:])

    def _api_clear_history(self):
        from flask import jsonify
        self._history = []
        self._save_history()
        return jsonify({"ok": True})

    def _api_list_rules(self):
        from flask import jsonify
        return jsonify(self._rules)

    def _api_add_rule(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        import time
        rule = {
            "id": data.get("id", int(time.time() * 1000)),
            "name": data.get("name", ""),
            "package": data.get("package"),
            "time_start": data.get("time_start"),
            "time_end": data.get("time_end"),
            "pattern": data.get("pattern"),
            "enabled": data.get("enabled", True)
        }
        self._rules.append(rule)
        self._save_rules()
        return jsonify({"ok": True, "rule": rule})

    def _api_delete_rule(self, rule_id):
        from flask import jsonify
        self._rules = [r for r in self._rules if r["id"] != rule_id]
        self._save_rules()
        return jsonify({"ok": True})

    def _api_scan(self):
        from flask import jsonify
        notifications = self._parse_notifications()
        return jsonify({"ok": True, "count": len(notifications), "notifications": notifications})


plugin_class = NotificationMgrPlugin
