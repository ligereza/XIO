"""
Clipboard Monitor – Monitor de clipboard con auto-clear.
Detecta cambios, guarda historial, filtro regex para datos sensibles.
"""

from plugins.base import PluginBase
import json, re
from datetime import datetime


class ClipboardMonitorPlugin(PluginBase):
    plugin_id = "clipboard_monitor"
    name = "Clipboard Monitor"
    version = "1.0.0"
    description = "Monitor de clipboard con auto-clear"
    author = "Arena Agent"
    icon = "system"
    category = "system"
    permissions = ["system"]

    SENSITIVE_PATTERNS = {
        "password": r'(?i)(password|pass|pwd|clave)\s*[:=]\s*\S+',
        "token": r'(?i)(token|api[_-]?key|secret|bearer)\s*[:=]\s*\S+',
        "credit_card": r'\b(?:\d[ -]*?){13,16}\b',
        "email": r'\b[\w.+-]+@[\w-]+\.[\w.-]+\b',
        "phone": r'\b\+?\d{10,15}\b',
    }

    def __init__(self, context):
        super().__init__(context)
        self._last_content = None
        self._history = []
        self._auto_clear_seconds = 30
        self._auto_clear_enabled = True
        self._sensitive_alerts = []

    def on_load(self):
        self._load_state()
        self.register_route("/status", self._api_status, methods=["GET"])
        self.register_route("/content", self._api_get_content, methods=["GET"])
        self.register_route("/history", self._api_history, methods=["GET"])
        self.register_route("/history/clear", self._api_clear_history, methods=["POST"])
        self.register_route("/clear", self._api_clear_clipboard, methods=["POST"])
        self.register_route("/config", self._api_get_config, methods=["GET"])
        self.register_route("/config", self._api_set_config, methods=["POST"])
        self.register_route("/alerts", self._api_alerts, methods=["GET"])
        self.context.schedule("clip_monitor", self._background_monitor, interval_seconds=5)
        self.logger.info("Clipboard Monitor loaded")

    def _load_state(self):
        f = self.data_dir / "state.json"
        if f.exists():
            try:
                state = json.loads(f.read_text())
                self._auto_clear_seconds = state.get("auto_clear_seconds", 30)
                self._auto_clear_enabled = state.get("auto_clear_enabled", True)
                hf = self.data_dir / "history.json"
                if hf.exists():
                    self._history = json.loads(hf.read_text())
            except:
                pass

    def _save_state(self):
        (self.data_dir / "state.json").write_text(json.dumps({
            "auto_clear_seconds": self._auto_clear_seconds,
            "auto_clear_enabled": self._auto_clear_enabled,
        }, indent=2))
        (self.data_dir / "history.json").write_text(json.dumps(self._history[-200:], indent=2))

    def _get_clipboard(self):
        try:
            out = self.controller._shell("service", "call", "clipboard", "1")
            return out.strip() if out else None
        except:
            return None

    def _clear_clipboard(self):
        try:
            self.controller._shell("service", "call", "clipboard", "2")
            return True
        except:
            return False

    def _check_sensitive(self, text):
        if not text:
            return []
        return [name for name, pattern in self.SENSITIVE_PATTERNS.items() if re.search(pattern, text)]

    def _background_monitor(self):
        try:
            current = self._get_clipboard()
            if current is None or current == self._last_content:
                return
            
            self._last_content = current
            sensitive = self._check_sensitive(current)
            entry = {
                "timestamp": datetime.now().isoformat(),
                "content": current[:200],
                "length": len(current),
                "sensitive": sensitive
            }
            self._history.append(entry)
            
            if sensitive:
                self._sensitive_alerts.append({
                    "type": "sensitive_data",
                    "patterns": sensitive,
                    "timestamp": entry["timestamp"]
                })
                self._sensitive_alerts = self._sensitive_alerts[-50:]
                
                if self._auto_clear_enabled:
                    import time
                    time.sleep(self._auto_clear_seconds)
                    self._clear_clipboard()
            
            if len(self._history) > 200:
                self._history = self._history[-200:]
            self._save_state()
        except Exception as e:
            self.logger.error(f"Clipboard monitor error: {e}")

    def _api_status(self):
        from flask import jsonify
        return jsonify({
            "auto_clear_enabled": self._auto_clear_enabled,
            "auto_clear_seconds": self._auto_clear_seconds,
            "last_content": self._last_content[:100] if self._last_content else None,
            "history_count": len(self._history)
        })

    def _api_get_content(self):
        from flask import jsonify
        current = self._get_clipboard()
        return jsonify({
            "content": current,
            "length": len(current) if current else 0,
            "sensitive": self._check_sensitive(current) if current else []
        })

    def _api_history(self):
        from flask import jsonify
        return jsonify(self._history[-50:])

    def _api_clear_history(self):
        from flask import jsonify
        self._history = []
        self._save_state()
        return jsonify({"ok": True})

    def _api_clear_clipboard(self):
        from flask import jsonify
        return jsonify({"ok": self._clear_clipboard()})

    def _api_get_config(self):
        from flask import jsonify
        return jsonify({
            "auto_clear_enabled": self._auto_clear_enabled,
            "auto_clear_seconds": self._auto_clear_seconds
        })

    def _api_set_config(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        if "auto_clear_enabled" in data:
            self._auto_clear_enabled = data["auto_clear_enabled"]
        if "auto_clear_seconds" in data:
            self._auto_clear_seconds = int(data["auto_clear_seconds"])
        self._save_state()
        return jsonify({"ok": True})

    def _api_alerts(self):
        from flask import jsonify
        return jsonify(self._sensitive_alerts[-20:])


plugin_class = ClipboardMonitorPlugin
