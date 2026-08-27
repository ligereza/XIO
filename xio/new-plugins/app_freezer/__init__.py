"""
App Freezer – Congela apps completamente al apagar pantalla.
Deep freeze, auto-unfreeze, stats, programacion por horarios.
"""

from plugins.base import PluginBase
import json, time
from datetime import datetime


class AppFreezerPlugin(PluginBase):
    plugin_id = "app_freezer"
    name = "App Freezer"
    version = "1.0.0"
    description = "Congelador de apps avanzado"
    author = "Arena Agent"
    icon = "automation"
    category = "automation"
    permissions = ["apps", "system"]

    def __init__(self, context):
        super().__init__(context)
        self._frozen_apps = []
        self._auto_freeze_list = []
        self._schedule = []
        self._stats = {"total_frozen": 0, "total_time_saved_min": 0}
        self._freeze_start = {}

    def on_load(self):
        self._load_state()
        self.register_route("/frozen", self._api_frozen_list, methods=["GET"])
        self.register_route("/freeze", self._api_freeze, methods=["POST"])
        self.register_route("/unfreeze", self._api_unfreeze, methods=["POST"])
        self.register_route("/unfreeze-all", self._api_unfreeze_all, methods=["POST"])
        self.register_route("/auto-freeze-list", self._api_get_auto_list, methods=["GET"])
        self.register_route("/auto-freeze-list", self._api_set_auto_list, methods=["POST"])
        self.register_route("/schedule", self._api_get_schedule, methods=["GET"])
        self.register_route("/schedule", self._api_set_schedule, methods=["POST"])
        self.register_route("/stats", self._api_stats, methods=["GET"])
        self.register_route("/deep-freeze", self._api_deep_freeze, methods=["POST"])
        self.context.schedule("screen_check", self._check_screen_off, interval_seconds=15)
        self.context.schedule("schedule_eval", self._check_schedule, interval_seconds=60)
        self.logger.info("App Freezer loaded")

    def _load_state(self):
        f = self.data_dir / "state.json"
        if f.exists():
            try:
                s = json.loads(f.read_text())
                self._auto_freeze_list = s.get("auto_freeze_list", [])
                self._schedule = s.get("schedule", [])
                self._stats = s.get("stats", self._stats)
            except:
                pass

    def _save_state(self):
        (self.data_dir / "state.json").write_text(json.dumps({
            "auto_freeze_list": self._auto_freeze_list,
            "schedule": self._schedule,
            "stats": self._stats
        }, indent=2))

    def _freeze_app(self, package):
        """Congela una app completamente."""
        try:
            self.controller._shell("am", "set-standby-bucket", package, "50")  # never
            self.controller.force_stop(package)
            self.controller._shell("cmd", "deviceidle", "whitelist", f"-{package}")
            self.controller._shell("settings", "put", "system", f"app_freeze_{package}", "1")
            if package not in self._frozen_apps:
                self._frozen_apps.append(package)
                self._freeze_start[package] = time.time()
                self._stats["total_frozen"] += 1
            return True
        except Exception as e:
            self.logger.error(f"Error freezing {package}: {e}")
            return False

    def _unfreeze_app(self, package):
        """Descongela una app."""
        try:
            self.controller._shell("am", "set-standby-bucket", package, "10")  # active
            if package in self._frozen_apps:
                self._frozen_apps.remove(package)
            if package in self._freeze_start:
                duration = time.time() - self._freeze_start.pop(package)
                self._stats["total_time_saved_min"] += duration / 60
            return True
        except Exception as e:
            self.logger.error(f"Error unfreezing {package}: {e}")
            return False

    def _is_screen_off(self):
        try:
            out = self.controller._shell("dumpsys", "power")
            return "mWakefulness=Asleep" in out or "Display Power: state=OFF" in out
        except:
            return False

    def _check_screen_off(self):
        """Auto-freeze cuando la pantalla se apaga."""
        if self._is_screen_off():
            for pkg in self._auto_freeze_list:
                if pkg not in self._frozen_apps:
                    self._freeze_app(pkg)
                    self.logger.info(f"Auto-frozen: {pkg}")
        else:
            pass

    def _check_schedule(self):
        """Evalua schedule de freeze por horario."""
        now = datetime.now()
        current_time = now.strftime("%H:%M")
        for entry in self._schedule:
            if entry.get("enabled", True):
                if entry.get("start_time") <= current_time <= entry.get("end_time", "23:59"):
                    for pkg in entry.get("apps", []):
                        if pkg not in self._frozen_apps:
                            self._freeze_app(pkg)

    def _api_frozen_list(self):
        from flask import jsonify
        result = []
        for pkg in self._frozen_apps:
            elapsed = time.time() - self._freeze_start.get(pkg, time.time())
            result.append({"package": pkg, "frozen_since": round(elapsed / 60, 1), "unit": "min"})
        return jsonify(result)

    def _api_freeze(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        pkg = data.get("package", "")
        if not pkg:
            return jsonify({"error": "package required"}), 400
        ok = self._freeze_app(pkg)
        return jsonify({"ok": ok, "package": pkg})

    def _api_unfreeze(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        pkg = data.get("package", "")
        ok = self._unfreeze_app(pkg)
        return jsonify({"ok": ok, "package": pkg})

    def _api_unfreeze_all(self):
        from flask import jsonify
        unfrozen = list(self._frozen_apps)
        for pkg in unfrozen:
            self._unfreeze_app(pkg)
        return jsonify({"ok": True, "unfrozen": len(unfrozen)})

    def _api_get_auto_list(self):
        from flask import jsonify
        return jsonify(self._auto_freeze_list)

    def _api_set_auto_list(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        self._auto_freeze_list = data.get("apps", [])
        self._save_state()
        return jsonify({"ok": True, "count": len(self._auto_freeze_list)})

    def _api_get_schedule(self):
        from flask import jsonify
        return jsonify(self._schedule)

    def _api_set_schedule(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        self._schedule = data.get("schedule", [])
        self._save_state()
        return jsonify({"ok": True})

    def _api_stats(self):
        from flask import jsonify
        return jsonify({
            "currently_frozen": len(self._frozen_apps),
            "total_frozen_events": self._stats["total_frozen"],
            "total_time_saved_min": round(self._stats["total_time_saved_min"], 1),
            "auto_freeze_count": len(self._auto_freeze_list),
            "schedule_entries": len(self._schedule)
        })

    def _api_deep_freeze(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        pkgs = data.get("packages", [])
        results = {}
        for pkg in pkgs:
            self._freeze_app(pkg)
            try:
                self.controller._shell("am", "set-standby-bucket", pkg, "50")
                results[pkg] = True
            except:
                results[pkg] = False
        return jsonify({"ok": True, "results": results, "mode": "deep_freeze"})


plugin_class = AppFreezerPlugin
