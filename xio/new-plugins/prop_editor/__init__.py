"""
System Prop Editor – Editor visual de propiedades del sistema.
Leer/escribir setprop/getprop, presets, monitor en tiempo real.
"""

from plugins.base import PluginBase
import json, time


class PropEditorPlugin(PluginBase):
    plugin_id = "prop_editor"
    name = "System Prop Editor"
    version = "1.0.0"
    description = "Editor de propiedades del sistema"
    author = "Arena Agent"
    icon = "system"
    category = "system"
    permissions = ["system"]

    SAFE_PROPS = [
        "persist.sys.computility.cpulevel",
        "persist.sys.computility.gpulevel",
        "persist.sys.advanced_visual_release",
        "persist.sys.background_blur_supported",
        "persist.sys.mi_shadow_supported",
        "persist.sys.launcher_blur_supported",
        "persist.log.tag",
        "debug.force-opengl",
        "debug.hwc.force_gpu_vsync",
        "ro.product.model",
        "ro.product.brand",
        "ro.build.display.id",
        "ro.build.version.release",
        "ro.build.version.sdk",
        "ro.hardware.chipname",
        "ro.soc.model",
        "gsm.version.ril-impl",
        "net.dns1",
        "net.dns2",
    ]

    def __init__(self, context):
        super().__init__(context)
        self._watch_list = []
        self._history = []

    def on_load(self):
        self.register_route("/list", self._api_list, methods=["GET"])
        self.register_route("/get", self._api_get, methods=["GET"])
        self.register_route("/set", self._api_set, methods=["POST"])
        self.register_route("/safe-props", self._api_safe_props, methods=["GET"])
        self.register_route("/search", self._api_search, methods=["GET"])
        self.register_route("/watch", self._api_watch, methods=["POST"])
        self.register_route("/watch/list", self._api_watch_list, methods=["GET"])
        self.register_route("/snapshot", self._api_snapshot, methods=["GET"])
        self.register_route("/diff", self._api_diff, methods=["GET"])
        self.register_route("/export", self._api_export, methods=["GET"])
        self.register_route("/reset", self._api_reset, methods=["POST"])
        self.context.schedule("watch_poll", self._poll_watch, interval_seconds=10)
        self.logger.info("Prop Editor loaded")

    def _get_prop(self, key):
        try:
            return self.controller._shell("getprop", key).strip()
        except:
            return ""

    def _set_prop(self, key, value):
        try:
            self.controller._shell("setprop", key, str(value))
            self._history.append({
                "key": key,
                "old": self._get_prop(key),
                "new": value,
                "timestamp": time.time()
            })
            self._history = self._history[-200:]
            return True
        except Exception as e:
            self.logger.error(f"Error setting {key}: {e}")
            return False

    def _get_all_props(self):
        try:
            out = self.controller._shell("getprop")
            props = {}
            for line in out.splitlines():
                if line.startswith("[") and "]:" in line:
                    key_end = line.index("]:")
                    key = line[1:key_end]
                    value = line[key_end+3:-1] if line.endswith("]") else line[key_end+3:]
                    props[key] = value
            return props
        except:
            return {}

    def _poll_watch(self):
        if not self._watch_list:
            return
        snapshot = {}
        for prop in self._watch_list:
            snapshot[prop] = self._get_prop(prop)
        f = self.data_dir / "watch_history.json"
        history = []
        if f.exists():
            try:
                history = json.loads(f.read_text())
            except:
                pass
        history.append({"timestamp": time.time(), "values": snapshot})
        if len(history) > 500:
            history = history[-500:]
        f.write_text(json.dumps(history, indent=2))

    def _api_list(self):
        from flask import request, jsonify
        props = self._get_all_props()
        filter_str = request.args.get("filter", "")
        if filter_str:
            props = {k: v for k, v in props.items() if filter_str.lower() in k.lower()}
        return jsonify({"props": props, "count": len(props)})

    def _api_get(self):
        from flask import request, jsonify
        key = request.args.get("key", "")
        if not key:
            return jsonify({"error": "key required"}), 400
        value = self._get_prop(key)
        return jsonify({"key": key, "value": value})

    def _api_set(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        key = data.get("key", "")
        value = data.get("value", "")
        if not key:
            return jsonify({"error": "key required"}), 400
        ok = self._set_prop(key, value)
        return jsonify({"ok": ok, "key": key, "value": value})

    def _api_safe_props(self):
        from flask import jsonify
        result = {}
        for prop in self.SAFE_PROPS:
            result[prop] = self._get_prop(prop)
        return jsonify(result)

    def _api_search(self):
        from flask import request, jsonify
        query = request.args.get("q", "")
        if not query:
            return jsonify({"error": "q required"}), 400
        props = self._get_all_props()
        matched = {k: v for k, v in props.items() if query.lower() in k.lower() or query.lower() in v.lower()}
        return jsonify({"matches": matched, "count": len(matched)})

    def _api_watch(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        action = data.get("action", "add")
        prop = data.get("prop", "")
        if action == "add" and prop and prop not in self._watch_list:
            self._watch_list.append(prop)
        elif action == "remove" and prop in self._watch_list:
            self._watch_list.remove(prop)
        return jsonify({"ok": True, "watch_list": self._watch_list})

    def _api_watch_list(self):
        from flask import jsonify
        current = {}
        for prop in self._watch_list:
            current[prop] = self._get_prop(prop)
        return jsonify({"watch_list": self._watch_list, "current_values": current})

    def _api_snapshot(self):
        from flask import jsonify
        safe = {}
        for prop in self.SAFE_PROPS:
            safe[prop] = self._get_prop(prop)
        f = self.data_dir / "snapshots.json"
        snapshots = []
        if f.exists():
            try:
                snapshots = json.loads(f.read_text())
            except:
                pass
        snapshots.append({"timestamp": time.time(), "values": safe})
        snapshots = snapshots[-20:]
        f.write_text(json.dumps(snapshots, indent=2))
        return jsonify({"ok": True, "snapshot": safe})

    def _api_diff(self):
        from flask import jsonify
        f = self.data_dir / "snapshots.json"
        if not f.exists():
            return jsonify({"error": "No snapshots"}), 404
        snapshots = json.loads(f.read_text())
        if len(snapshots) < 2:
            return jsonify({"error": "Need at least 2 snapshots"}), 400
        old = snapshots[-2]["values"]
        new = snapshots[-1]["values"]
        diff = {}
        all_keys = set(list(old.keys()) + list(new.keys()))
        for key in all_keys:
            if old.get(key) != new.get(key):
                diff[key] = {"old": old.get(key, ""), "new": new.get(key, "")}
        return jsonify({"diff": diff, "changed": len(diff)})

    def _api_export(self):
        from flask import Response
        props = self._get_all_props()
        lines = [f"{k}={v}" for k, v in sorted(props.items())]
        return Response("\n".join(lines), mimetype="text/plain",
                       headers={"Content-Disposition": "attachment; filename=props_export.txt"})

    def _api_reset(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        prop = data.get("key", "")
        if not prop:
            return jsonify({"error": "key required"}), 400
        try:
            self.controller._shell("setprop", prop, "")
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500


plugin_class = PropEditorPlugin
