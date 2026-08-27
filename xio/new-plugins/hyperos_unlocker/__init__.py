"""
HyperOS Unlocker – Desbloquea features flagship en cualquier Xiaomi.
Advanced Textures, Blur, Liquid Glass, Stack Recents, CPU/GPU override.
"""

from plugins.base import PluginBase
import json


class HyperOSUnlockerPlugin(PluginBase):
    plugin_id = "hyperos_unlocker"
    name = "HyperOS Unlocker"
    version = "1.0.0"
    description = "Desbloquea features flagship"
    author = "Arena Agent"
    icon = "cpu"
    category = "system"
    permissions = ["system"]

    PROPS = {
        "cpu_level": {
            "cmd": 'service call miui.mqsas.IMQSNative 21 i32 1 s16 "setprop" i32 1 s16 "persist.sys.computility.cpulevel {level}" s16 "/storage/emulated/0/log.txt" i32 600',
            "values": {"low": "0", "medium": "3", "high": "6"},
            "description": "Nivel de CPU (0=bajo, 3=medio, 6=flagship)"
        },
        "gpu_level": {
            "cmd": 'service call miui.mqsas.IMQSNative 21 i32 1 s16 "setprop" i32 1 s16 "persist.sys.computility.gpulevel {level}" s16 "/storage/emulated/0/log.txt" i32 600',
            "values": {"low": "0", "medium": "3", "high": "6"},
            "description": "Nivel de GPU (0=bajo, 3=medio, 6=flagship)"
        },
        "visual_release": {
            "cmd": 'service call miui.mqsas.IMQSNative 21 i32 1 s16 "setprop" i32 1 s16 "persist.sys.advanced_visual_release {level}" s16 "/storage/emulated/0/log.txt" i32 600',
            "values": {"off": "0", "textures": "3", "liquid_glass": "4"},
            "description": "Advanced Visual Release (3=texturas, 4=liquid glass)"
        },
        "background_blur": {
            "cmd": 'service call miui.mqsas.IMQSNative 21 i32 1 s16 "setprop" i32 1 s16 "persist.sys.background_blur_supported {val}" s16 "/storage/emulated/0/log.txt" i32 600',
            "values": {"false": "false", "true": "true"},
            "description": "Soporte de blur en el fondo"
        },
        "shadow_supported": {
            "cmd": 'service call miui.mqsas.IMQSNative 21 i32 1 s16 "setprop" i32 1 s16 "persist.sys.mi_shadow_supported {val}" s16 "/storage/emulated/0/log.txt" i32 600',
            "values": {"false": "false", "true": "true"},
            "description": "Sombras avanzadas"
        },
        "stack_recents": {
            "cmd": 'settings put global task_stack_view_layout_style {val}',
            "values": {"grid": "0", "stack": "1", "stack_ios": "2"},
            "description": "Estilo de recents"
        },
        "device_level_list": {
            "cmd": 'settings put system deviceLevelList v:1,c:{cpu},g:{gpu}',
            "values": None,
            "description": "Override de nivel del dispositivo (CPU/GPU)"
        },
    }

    PRESETS = {
        "flagship": {
            "name": "🏆 Flagship Mode",
            "description": "Todos los features al maximo",
            "props": {
                "cpu_level": "6",
                "gpu_level": "6",
                "visual_release": "4",
                "background_blur": "true",
                "shadow_supported": "true",
                "stack_recents": "2"
            }
        },
        "balanced": {
            "name": "⚖️ Balanced",
            "description": "Features premium sin sacrificar bateria",
            "props": {
                "cpu_level": "3",
                "gpu_level": "3",
                "visual_release": "3",
                "background_blur": "true",
                "shadow_supported": "true",
                "stack_recents": "1"
            }
        },
        "reset": {
            "name": "🔄 Reset",
            "description": "Volver a valores por defecto",
            "props": {
                "cpu_level": "0",
                "gpu_level": "0",
                "visual_release": "0",
                "background_blur": "false",
                "shadow_supported": "false",
                "stack_recents": "0"
            }
        }
    }

    def on_load(self):
        self.register_route("/props", self._api_list_props, methods=["GET"])
        self.register_route("/set", self._api_set_prop, methods=["POST"])
        self.register_route("/presets", self._api_list_presets, methods=["GET"])
        self.register_route("/preset/apply", self._api_apply_preset, methods=["POST"])
        self.register_route("/current", self._api_current_state, methods=["GET"])
        self.register_route("/device-level", self._api_set_device_level, methods=["POST"])
        self.logger.info("HyperOS Unlocker loaded")

    def _exec_prop(self, prop_name, value):
        if prop_name not in self.PROPS:
            return False, "Prop not found"
        info = self.PROPS[prop_name]
        cmd = info["cmd"]
        if prop_name == "device_level_list":
            cmd = cmd.format(cpu=value, gpu=value)
        elif prop_name in ["background_blur", "shadow_supported"]:
            cmd = cmd.format(val=value)
        elif prop_name == "stack_recents":
            cmd = cmd.format(val=value)
        else:
            cmd = cmd.format(level=value)
        try:
            self.controller._shell(cmd)
            return True, "OK"
        except Exception as e:
            return False, str(e)

    def _api_list_props(self):
        from flask import jsonify
        result = {}
        for name, info in self.PROPS.items():
            result[name] = {"description": info["description"], "values": info["values"]}
        return jsonify(result)

    def _api_set_prop(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        prop = data.get("prop", "")
        value = data.get("value", "")
        if prop not in self.PROPS:
            return jsonify({"error": "Unknown prop"}), 400
        ok, msg = self._exec_prop(prop, value)
        return jsonify({"ok": ok, "message": msg, "prop": prop, "value": value})

    def _api_list_presets(self):
        from flask import jsonify
        return jsonify(self.PRESETS)

    def _api_apply_preset(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        preset = data.get("preset", "")
        if preset not in self.PRESETS:
            return jsonify({"error": "Unknown preset"}), 400
        results = {}
        for prop, value in self.PRESETS[preset]["props"].items():
            ok, msg = self._exec_prop(prop, value)
            results[prop] = {"ok": ok, "value": value}
        return jsonify({"ok": True, "preset": preset, "results": results})

    def _api_current_state(self):
        from flask import jsonify
        state = {}
        try:
            for prop in ["computility.cpulevel", "computility.gpulevel", "advanced_visual_release", "background_blur_supported", "mi_shadow_supported"]:
                val = self.controller._shell("getprop", f"persist.sys.{prop}")
                state[prop] = val.strip()
            stack = self.controller._shell("settings", "get", "global", "task_stack_view_layout_style")
            state["task_stack_view_layout_style"] = stack.strip()
            dll = self.controller._shell("settings", "get", "system", "deviceLevelList")
            state["deviceLevelList"] = dll.strip()
        except Exception as e:
            state["error"] = str(e)
        return jsonify(state)

    def _api_set_device_level(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        try:
            cpu = int(data.get("cpu", 3))
            gpu = int(data.get("gpu", 3))
        except (TypeError, ValueError):
            return jsonify({"error": "cpu and gpu must be integers"}), 400
        if not (0 <= cpu <= 6 and 0 <= gpu <= 6):
            return jsonify({"error": "cpu and gpu must be in range 0..6"}), 400
        try:
            self.controller._shell("settings", "put", "system", "deviceLevelList", f"v:1,c:{cpu},g:{gpu}")
            return jsonify({"ok": True, "cpu": cpu, "gpu": gpu})
        except Exception as e:
            return jsonify({"error": str(e)}), 500


plugin_class = HyperOSUnlockerPlugin
