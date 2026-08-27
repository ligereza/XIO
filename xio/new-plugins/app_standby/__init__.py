"""
App Standby Manager – Control de background apps.
"""

from plugins.base import PluginBase
import json, re


class AppStandbyPlugin(PluginBase):
    plugin_id = "app_standby"
    name = "App Standby Manager"
    version = "1.0.0"
    description = "Control de apps en background"
    author = "Arena Agent"
    icon = "system"
    category = "system"
    permissions = ["apps", "system"]

    BUCKETS = {"active": 10, "working": 20, "frequent": 30, "rare": 40, "restricted": 45}

    def __init__(self, context):
        super().__init__(context)
        self._exclusions = []

    def on_load(self):
        f = self.data_dir / "exclusions.json"
        if f.exists():
            try: self._exclusions = json.loads(f.read_text())
            except: pass
        self.register_route("/running", self._api_running, methods=["GET"])
        self.register_route("/buckets", self._api_buckets, methods=["GET"])
        self.register_route("/bucket/set", self._api_set_bucket, methods=["POST"])
        self.register_route("/restrict", self._api_restrict, methods=["POST"])
        self.register_route("/unrestrict", self._api_unrestrict, methods=["POST"])
        self.register_route("/exclusions", self._api_exclusions, methods=["GET"])
        self.register_route("/exclusions", self._api_add_exclusion, methods=["POST"])
        self.logger.info("App Standby Manager loaded")

    def _get_running(self):
        try:
            out = self.controller._shell("dumpsys", "activity", "processes")
            apps = []
            for line in out.splitlines():
                m = re.search(r'proc=([\w.]+)', line)
                if m and m.group(1) not in apps:
                    apps.append(m.group(1))
            return apps
        except:
            return []

    def _set_bucket(self, pkg, bucket):
        if bucket not in self.BUCKETS:
            return False
        try:
            self.controller._shell("am", "set-standby-bucket", pkg, str(self.BUCKETS[bucket]))
            return True
        except:
            return False

    def _get_bucket(self, pkg):
        try:
            out = self.controller._shell("am", "get-standby-bucket", pkg)
            num = int(out.strip())
            for name, n in self.BUCKETS.items():
                if n == num:
                    return name
        except:
            pass
        return "unknown"

    def _api_running(self):
        from flask import jsonify
        apps = self._get_running()[:50]
        return jsonify([{"package": p, "bucket": self._get_bucket(p)} for p in apps])

    def _api_buckets(self):
        from flask import jsonify
        return jsonify(self.BUCKETS)

    def _api_set_bucket(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        ok = self._set_bucket(data.get("package", ""), data.get("bucket", "rare"))
        return jsonify({"ok": ok})

    def _api_restrict(self):
        from flask import request, jsonify
        pkg = request.get_json(force=True).get("package", "")
        self.controller._shell("cmd", "deviceidle", "whitelist", f"-{pkg}")
        self._set_bucket(pkg, "restricted")
        return jsonify({"ok": True})

    def _api_unrestrict(self):
        from flask import request, jsonify
        pkg = request.get_json(force=True).get("package", "")
        self.controller._shell("cmd", "deviceidle", "whitelist", f"+{pkg}")
        self._set_bucket(pkg, "active")
        return jsonify({"ok": True})

    def _api_exclusions(self):
        from flask import jsonify
        return jsonify(self._exclusions)

    def _api_add_exclusion(self):
        from flask import request, jsonify
        pkg = request.get_json(force=True).get("package", "")
        if pkg and pkg not in self._exclusions:
            self._exclusions.append(pkg)
            (self.data_dir / "exclusions.json").write_text(json.dumps(self._exclusions))
        return jsonify({"ok": True})


plugin_class = AppStandbyPlugin
