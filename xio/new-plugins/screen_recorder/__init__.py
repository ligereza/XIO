"""
Screen Recorder Pro – Control avanzado de grabación de pantalla.
"""

from plugins.base import PluginBase
import time
from datetime import datetime


class ScreenRecorderPlugin(PluginBase):
    plugin_id = "screen_recorder"
    name = "Screen Recorder Pro"
    version = "1.0.0"
    description = "Control avanzado de grabación"
    author = "Arena Agent"
    icon = "system"
    category = "system"
    permissions = ["system"]

    PRESETS = {
        "low": {"size": "720x1600", "bitrate": "4000000", "fps": "30"},
        "medium": {"size": "1080x2400", "bitrate": "8000000", "fps": "30"},
        "high": {"size": "1080x2400", "bitrate": "12000000", "fps": "60"},
    }

    def __init__(self, context):
        super().__init__(context)
        self._recording = False
        self._current_file = None
        self._start_time = None

    def on_load(self):
        self.register_route("/status", self._api_status, methods=["GET"])
        self.register_route("/start", self._api_start, methods=["POST"])
        self.register_route("/stop", self._api_stop, methods=["POST"])
        self.register_route("/presets", self._api_presets, methods=["GET"])
        self.register_route("/files", self._api_list_files, methods=["GET"])
        self.context.schedule("rec_check", self._check_recording, interval_seconds=5)
        self.logger.info("Screen Recorder Pro loaded")

    def _start(self, preset="medium"):
        if self._recording:
            return False, "Already recording"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._current_file = f"/sdcard/DCIM/ScreenRecord/record_{ts}.mp4"
        self.controller._shell("mkdir", "-p", "/sdcard/DCIM/ScreenRecord/")
        
        s = self.PRESETS.get(preset, self.PRESETS["medium"])
        cmd = ["screenrecord", "--size", s["size"], "--bit-rate", s["bitrate"], self._current_file]
        try:
            self.controller._shell("nohup", *cmd, "&")
            self._recording = True
            self._start_time = time.time()
            return True, self._current_file
        except Exception as e:
            return False, str(e)

    def _stop(self):
        if not self._recording:
            return False
        try:
            self.controller._shell("pkill", "-INT", "screenrecord")
            self._recording = False
            duration = time.time() - self._start_time if self._start_time else 0
            return self._current_file, duration
        except:
            return False

    def _check_recording(self):
        if self._recording:
            try:
                out = self.controller._shell("pidof", "screenrecord")
                if not out.strip():
                    self._recording = False
            except:
                pass

    def _api_status(self):
        from flask import jsonify
        dur = time.time() - self._start_time if self._recording and self._start_time else 0
        return jsonify({"recording": self._recording, "file": self._current_file, "duration": round(dur, 1)})

    def _api_start(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        ok, result = self._start(data.get("preset", "medium"))
        if ok:
            return jsonify({"ok": True, "file": result})
        return jsonify({"error": result}), 400

    def _api_stop(self):
        from flask import jsonify
        result = self._stop()
        if result[0]:
            return jsonify({"ok": True, "file": result[0], "duration": result[1]})
        return jsonify({"ok": False})

    def _api_presets(self):
        from flask import jsonify
        return jsonify(self.PRESETS)

    def _api_list_files(self):
        from flask import jsonify
        try:
            return jsonify(self.controller.list_dir("/sdcard/DCIM/ScreenRecord/"))
        except Exception as e:
            return jsonify({"error": str(e)})


plugin_class = ScreenRecorderPlugin
