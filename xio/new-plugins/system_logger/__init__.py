"""
System Logger – Monitor de logcat remoto con filtros inteligentes.
Deteccion de crashes/ANRs, estadisticas, alertas, exportar.
"""

from plugins.base import PluginBase
import json, re, threading
from datetime import datetime


class SystemLoggerPlugin(PluginBase):
    plugin_id = "system_logger"
    name = "System Logger"
    version = "1.0.0"
    description = "Monitor de logcat remoto"
    author = "Arena Agent"
    icon = "system"
    category = "system"
    permissions = ["system"]

    CRASH_PATTERNS = [
        r"FATAL EXCEPTION",
        r"AndroidRuntime.*Error",
        r"ANR in",
        r"Application Not Responding",
        r"OutOfMemoryError",
        r"StackOverflowError",
        r"NullPointerException",
        r"SecurityException",
    ]

    def __init__(self, context):
        super().__init__(context)
        self._logs = []
        self._crashes = []
        self._monitoring = False
        self._filter_tag = None
        self._filter_package = None
        self._filter_priority = "E"
        self._max_logs = 5000
        self._max_crashes = 500

    def on_load(self):
        self.register_route("/logs", self._api_logs, methods=["GET"])
        self.register_route("/crashes", self._api_crashes, methods=["GET"])
        self.register_route("/crash-stats", self._api_crash_stats, methods=["GET"])
        self.register_route("/start", self._api_start, methods=["POST"])
        self.register_route("/stop", self._api_stop, methods=["POST"])
        self.register_route("/status", self._api_status, methods=["GET"])
        self.register_route("/filter", self._api_set_filter, methods=["POST"])
        self.register_route("/clear", self._api_clear, methods=["POST"])
        self.register_route("/snapshot", self._api_snapshot, methods=["POST"])
        self.register_route("/export", self._api_export, methods=["GET"])
        self.context.schedule("logcat_poll", self._poll_logcat, interval_seconds=5)
        self.logger.info("System Logger loaded")

    def _poll_logcat(self):
        if not self._monitoring:
            return
        try:
            priority_map = {"V": "V", "D": "D", "I": "I", "W": "W", "E": "E", "F": "F"}
            cmd = ["logcat", "-d", "-t", "100"]
            if self._filter_tag:
                cmd.extend(["-s", f"{self._filter_tag}:*"])
            out = self.controller._shell(*cmd)
            for line in out.splitlines():
                if not line.strip():
                    continue
                entry = self._parse_logcat_line(line)
                if entry:
                    self._logs.append(entry)
                    self._check_crash(entry)
            if len(self._logs) > self._max_logs:
                self._logs = self._logs[-self._max_logs:]
        except Exception as e:
            self.logger.error(f"Logcat poll error: {e}")

    def _parse_logcat_line(self, line):
        try:
            match = re.match(r'(\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+)\s+(\d+)\s+(\d+)\s+([VDIWEF])\s+(\S+):\s+(.*)', line)
            if match:
                return {
                    "timestamp": match.group(1),
                    "pid": match.group(2),
                    "tid": match.group(3),
                    "priority": match.group(4),
                    "tag": match.group(5),
                    "message": match.group(6),
                    "raw": line
                }
            elif line.strip():
                return {"raw": line, "priority": "I", "tag": "unknown", "message": line}
        except:
            pass
        return None

    def _check_crash(self, entry):
        msg = entry.get("message", "") + entry.get("raw", "")
        for pattern in self.CRASH_PATTERNS:
            if re.search(pattern, msg, re.IGNORECASE):
                crash = {
                    "timestamp": datetime.now().isoformat(),
                    "type": pattern,
                    "message": entry.get("message", "")[:500],
                    "tag": entry.get("tag", ""),
                    "raw": entry.get("raw", "")[:1000]
                }
                self._crashes.append(crash)
                if len(self._crashes) > self._max_crashes:
                    self._crashes = self._crashes[-self._max_crashes:]
                self.logger.warning(f"Crash detected: {pattern}")
                break

    def _api_logs(self):
        from flask import request, jsonify
        limit = int(request.args.get("limit", 100))
        tag = request.args.get("tag")
        priority = request.args.get("priority")
        logs = self._logs[-limit:]
        if tag:
            logs = [l for l in logs if tag.lower() in l.get("tag", "").lower()]
        if priority:
            logs = [l for l in logs if l.get("priority") == priority]
        return jsonify(logs)

    def _api_crashes(self):
        from flask import request, jsonify
        limit = int(request.args.get("limit", 50))
        return jsonify(self._crashes[-limit:])

    def _api_crash_stats(self):
        from flask import jsonify
        stats = {}
        for crash in self._crashes:
            t = crash.get("type", "unknown")
            stats[t] = stats.get(t, 0) + 1
        return jsonify({
            "total_crashes": len(self._crashes),
            "by_type": stats,
            "last_crash": self._crashes[-1]["timestamp"] if self._crashes else None
        })

    def _api_start(self):
        from flask import jsonify
        self._monitoring = True
        return jsonify({"ok": True, "monitoring": True})

    def _api_stop(self):
        from flask import jsonify
        self._monitoring = False
        return jsonify({"ok": True, "monitoring": False})

    def _api_status(self):
        from flask import jsonify
        return jsonify({
            "monitoring": self._monitoring,
            "log_count": len(self._logs),
            "crash_count": len(self._crashes),
            "filter_tag": self._filter_tag,
            "filter_priority": self._filter_priority
        })

    def _api_set_filter(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        self._filter_tag = data.get("tag")
        self._filter_priority = data.get("priority", "E")
        self._filter_package = data.get("package")
        return jsonify({"ok": True})

    def _api_clear(self):
        from flask import jsonify
        self._logs = []
        self._crashes = []
        try:
            self.controller._shell("logcat", "-c")
        except:
            pass
        return jsonify({"ok": True})

    def _api_snapshot(self):
        from flask import jsonify
        try:
            out = self.controller._shell("logcat", "-d", "-t", "200")
            return jsonify({"ok": True, "lines": len(out.splitlines()), "snapshot": out[:5000]})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    def _api_export(self):
        from flask import Response
        data = "\n".join([l.get("raw", "") for l in self._logs[-1000:]])
        return Response(data, mimetype="text/plain",
                       headers={"Content-Disposition": "attachment; filename=logcat_export.txt"})


plugin_class = SystemLoggerPlugin
