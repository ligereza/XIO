"""
Desktop / Freeform Mode – Ventanas flotantes y modo escritorio.
Freeform windows, redimensionar, multiples apps simultaneas.
"""

from plugins.base import PluginBase


class DesktopModePlugin(PluginBase):
    plugin_id = "desktop_mode"
    name = "Desktop / Freeform Mode"
    version = "1.0.0"
    description = "Ventanas flotantes y modo escritorio"
    author = "Arena Agent"
    icon = "system"
    category = "system"
    permissions = ["system", "input"]

    WINDOW_MODES = {
        "fullscreen": 1,
        "freeform": 5,
        "split_top": 3,
        "split_bottom": 4,
        "pip": 9,
    }

    def __init__(self, context):
        super().__init__(context)
        self._open_windows = []

    def on_load(self):
        self.register_route("/launch-freeform", self._api_launch_freeform, methods=["POST"])
        self.register_route("/launch-pip", self._api_launch_pip, methods=["POST"])
        self.register_route("/launch-split", self._api_launch_split, methods=["POST"])
        self.register_route("/launch-mode", self._api_launch_mode, methods=["POST"])
        self.register_route("/windows", self._api_list_windows, methods=["GET"])
        self.register_route("/close", self._api_close_window, methods=["POST"])
        self.register_route("/close-all", self._api_close_all, methods=["POST"])
        self.register_route("/resize", self._api_resize, methods=["POST"])
        self.register_route("/move", self._api_move, methods=["POST"])
        self.register_route("/display-info", self._api_display_info, methods=["GET"])
        self.register_route("/enable-freeform", self._api_enable_freeform, methods=["POST"])
        self.logger.info("Desktop Mode loaded")

    def _launch_in_mode(self, package, mode="freeform", bounds=None):
        mode_id = self.WINDOW_MODES.get(mode, 5)
        cmd = ["am", "start"]
        if mode == "freeform":
            cmd.extend(["--windowingMode", "5"])
            if bounds:
                cmd.extend(["--bounds", bounds])
            else:
                cmd.extend(["--bounds", "100,100,900,1600"])
        elif mode == "pip":
            cmd.extend(["--windowingMode", "9"])
        elif mode == "split_top":
            cmd.extend(["--windowingMode", "3"])
        elif mode == "split_bottom":
            cmd.extend(["--windowingMode", "4"])
        else:
            cmd.extend(["--windowingMode", str(mode_id)])
        cmd.extend(["-n", f"{package}/{self._get_launch_activity(package)}"])
        try:
            self.controller._shell(*cmd)
            self._open_windows.append({"package": package, "mode": mode})
            return True
        except Exception as e:
            self.logger.error(f"Error launching {package} in {mode}: {e}")
            return False

    def _get_launch_activity(self, package):
        try:
            out = self.controller._shell("cmd", "package", "resolve-activity", "--brief", package)
            for line in out.splitlines():
                if "/" in line:
                    return line.strip().split("/")[-1] if "/" in line.strip() else line.strip()
        except:
            pass
        try:
            out = self.controller._shell("monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1")
            return "launch"
        except:
            pass
        return "MainActivity"

    def _get_windows(self):
        try:
            out = self.controller._shell("dumpsys", "activity", "activities")
            windows = []
            for line in out.splitlines():
                if "TaskRecord" in line or "ActivityRecord" in line:
                    windows.append(line.strip())
            return windows[:30]
        except:
            return []

    def _api_launch_freeform(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        pkg = data.get("package", "")
        bounds = data.get("bounds")
        if not pkg:
            return jsonify({"error": "package required"}), 400
        ok = self._launch_in_mode(pkg, "freeform", bounds)
        return jsonify({"ok": ok, "package": pkg, "mode": "freeform"})

    def _api_launch_pip(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        pkg = data.get("package", "")
        ok = self._launch_in_mode(pkg, "pip")
        return jsonify({"ok": ok, "package": pkg, "mode": "pip"})

    def _api_launch_split(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        pkg1 = data.get("package1", "")
        pkg2 = data.get("package2", "")
        ok1 = self._launch_in_mode(pkg1, "split_top") if pkg1 else True
        ok2 = self._launch_in_mode(pkg2, "split_bottom") if pkg2 else True
        return jsonify({"ok": ok1 and ok2})

    def _api_launch_mode(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        pkg = data.get("package", "")
        mode = data.get("mode", "freeform")
        bounds = data.get("bounds")
        ok = self._launch_in_mode(pkg, mode, bounds)
        return jsonify({"ok": ok, "mode": mode})

    def _api_list_windows(self):
        from flask import jsonify
        return jsonify({"windows": self._get_windows(), "tracked": self._open_windows})

    def _api_close_window(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        pkg = data.get("package", "")
        self.controller.force_stop(pkg)
        self._open_windows = [w for w in self._open_windows if w["package"] != pkg]
        return jsonify({"ok": True})

    def _api_close_all(self):
        from flask import jsonify
        for w in self._open_windows:
            self.controller.force_stop(w["package"])
        closed = len(self._open_windows)
        self._open_windows = []
        return jsonify({"ok": True, "closed": closed})

    def _api_resize(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        stack_id = data.get("stack_id")
        bounds = data.get("bounds", "100,100,800,1200")
        if stack_id:
            try:
                self.controller._shell("wm", "stack", "resize", str(stack_id), bounds)
                return jsonify({"ok": True})
            except Exception as e:
                return jsonify({"error": str(e)}), 500
        return jsonify({"error": "stack_id required"}), 400

    def _api_move(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        stack_id = data.get("stack_id")
        bounds = data.get("bounds", "200,200,900,1400")
        if stack_id:
            try:
                self.controller._shell("wm", "stack", "resize", str(stack_id), bounds)
                return jsonify({"ok": True})
            except Exception as e:
                return jsonify({"error": str(e)}), 500
        return jsonify({"error": "stack_id required"}), 400

    def _api_display_info(self):
        from flask import jsonify
        try:
            size = self.controller._shell("wm", "size")
            density = self.controller._shell("wm", "density")
            displays = self.controller._shell("dumpsys", "display")
            return jsonify({
                "size": size.strip(),
                "density": density.strip(),
                "displays_info": displays[:2000]
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    def _api_enable_freeform(self):
        from flask import jsonify
        try:
            self.controller._shell("settings", "put", "global", "enable_freeform_windows", "1")
            return jsonify({"ok": True, "message": "Freeform windows enabled"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500


plugin_class = DesktopModePlugin
