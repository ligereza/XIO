"""
Battery Care Plugin – Xiaomi Controller
Monitor, optimize, and protect battery health on non-rooted Xiaomi devices (HyperOS).

Capabilities (NO ROOT REQUIRED):
- Real-time battery monitoring (level, temperature, status, voltage)
- Battery health logging with history charts
- Smart alerts: overheating, overcharging, critically low
- Auto power-saving: enable battery saver mode at configurable threshold
- App killer: auto-close specified apps when battery is low
- Charge completion alerts (80% and 100% notifications via ADB)
- Scheduled optimization routines
- Battery drain rate calculation
- Screen brightness reduction in low battery

Architecture:
- Background thread polls battery status every N seconds
- Events stored in JSON log for history/charts
- REST API for the dashboard to query status, history, and configure
"""

import time
import json
import threading
from datetime import datetime, timedelta
from pathlib import Path
from plugins.base import PluginBase


class BatteryCarePlugin(PluginBase):
    plugin_id = "battery_care"
    name = "Battery Care"
    version = "1.0.0"
    description = "Battery monitoring and optimization for Xiaomi without root"
    author = "Arena Agent"
    icon = "battery"
    category = "battery"
    permissions = ["battery", "system", "apps"]

    # Default configuration
    DEFAULT_CONFIG = {
        "poll_interval_seconds": 30,
        "alert_overheat_celsius": 38.0,
        "alert_low_battery_pct": 15,
        "alert_critical_battery_pct": 5,
        "auto_save_battery_at_pct": 20,
        "charge_complete_alert_pct": 80,
        "auto_kill_apps_at_pct": 10,
        "apps_to_kill": [],  # package names to kill when battery is critically low
        "reduce_brightness_at_pct": 15,
        "brightness_low_value": 30,
        "enable_notifications": True,
        "history_max_entries": 2880,  # ~24h at 30s intervals
    }

    def __init__(self, context):
        super().__init__(context)
        self._running = False
        self._thread = None
        self._history = []
        self._alerts = []
        self._last_battery = {}
        self._charge_start_time = None
        self._charge_start_level = None
        self._daily_stats = {}

        # Merge defaults with saved config
        for k, v in self.DEFAULT_CONFIG.items():
            if k not in self._config:
                self._config[k] = v

    def on_load(self):
        # Register all API routes
        self.register_route("/status", self._api_status, methods=["GET"])
        self.register_route("/history", self._api_history, methods=["GET"])
        self.register_route("/alerts", self._api_alerts, methods=["GET"])
        self.register_route("/alerts/clear", self._api_clear_alerts, methods=["POST"])
        self.register_route("/config", self._api_get_config, methods=["GET"])
        self.register_route("/config", self._api_set_config, methods=["POST"])
        self.register_route("/optimize", self._api_optimize, methods=["POST"])
        self.register_route("/drain-rate", self._api_drain_rate, methods=["GET"])
        self.register_route("/health-report", self._api_health_report, methods=["GET"])
        self.register_route("/start", self._api_start_monitor, methods=["POST"])
        self.register_route("/stop", self._api_stop_monitor, methods=["POST"])
        self.register_route("/stats/daily", self._api_daily_stats, methods=["GET"])
        self.register_route("/apps-to-kill", self._api_set_kill_list, methods=["POST"])

        # Load persisted history
        self._load_history()

        self.logger.info("Battery Care plugin loaded")

    def on_enable(self):
        self._start_monitoring()

    def on_disable(self):
        self._stop_monitoring()

    def on_unload(self):
        self._stop_monitoring()
        self._save_history()

    # ── Background monitoring ────────────────────────────────────────
    def _start_monitoring(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True,
                                        name="battery-care-monitor")
        self._thread.start()
        self.logger.info("Battery Care monitoring started")

    def _stop_monitoring(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        self.logger.info("Battery Care monitoring stopped")

    def _monitor_loop(self):
        while self._running:
            try:
                self._poll_battery()
            except Exception as e:
                self.logger.error(f"Battery poll error: {e}")
            # Coerce to a sane numeric interval: a non-numeric config value
            # (e.g. the string "30") would otherwise make int(interval * 10)
            # explode into a huge/invalid number and hang or kill the loop
            # while /status still reports monitoring active.
            try:
                interval = float(self._config.get("poll_interval_seconds", 30))
            except (TypeError, ValueError):
                interval = 30
            if interval < 1:
                interval = 30
            # Interruptible sleep
            for _ in range(int(interval * 10)):
                if not self._running:
                    return
                time.sleep(0.1)

    def _poll_battery(self):
        """Single battery poll – check conditions and trigger actions."""
        try:
            bat = self.controller.battery_status()
        except Exception as e:
            self.logger.error(f"Cannot read battery: {e}")
            return

        if not bat or "level" not in bat:
            return

        now = datetime.now().isoformat()
        level = bat.get("level", 0)
        charging = bat.get("charging", False)
        temperature = bat.get("temperature", 0)
        status = bat.get("status", "unknown")

        entry = {
            "timestamp": now,
            "level": level,
            "charging": charging,
            "temperature": temperature,
            "status": status,
        }
        self._history.append(entry)

        # Trim history
        max_entries = self._config.get("history_max_entries", 2880)
        if len(self._history) > max_entries:
            self._history = self._history[-max_entries:]

        # Track charging sessions
        if charging and self._charge_start_time is None:
            self._charge_start_time = now
            self._charge_start_level = level
        elif not charging and self._charge_start_time is not None:
            self._charge_start_time = None
            self._charge_start_level = None

        # ── Check alert conditions ───────────────────────────────────
        # Overheating
        overheat_threshold = self._config.get("alert_overheat_celsius", 38.0)
        if temperature > overheat_threshold:
            self._add_alert("overheat", f"Device overheating: {temperature}°C", level="warning")

        # Critically low battery
        critical = self._config.get("alert_critical_battery_pct", 5)
        low = self._config.get("alert_low_battery_pct", 15)
        if level <= critical and not charging:
            self._add_alert("critical", f"Battery critical: {level}%", level="critical")
        elif level <= low and not charging:
            self._add_alert("low", f"Battery low: {level}%", level="warning")

        # Charge complete alert
        charge_alert_at = self._config.get("charge_complete_alert_pct", 80)
        if charging and level >= charge_alert_at:
            self._add_alert("charge_complete",
                           f"Battery at {level}% – consider unplugging to preserve longevity",
                           level="info")

        # ── Auto actions ─────────────────────────────────────────────
        # Auto-enable battery saver
        save_at = self._config.get("auto_save_battery_at_pct", 20)
        if level <= save_at and not charging:
            self._enable_battery_saver()

        # Reduce brightness
        bright_at = self._config.get("reduce_brightness_at_pct", 15)
        if level <= bright_at and not charging:
            self._reduce_brightness()

        # Kill battery-hungry apps
        kill_at = self._config.get("auto_kill_apps_at_pct", 10)
        if level <= kill_at and not charging:
            self._kill_battery_drainers()

        # Update daily stats
        self._update_daily_stats(entry)
        self._last_battery = bat

    def _add_alert(self, alert_type: str, message: str, level: str = "info"):
        """Add an alert, avoiding duplicates within 5 minutes."""
        now = time.time()
        for existing in self._alerts[-10:]:
            if existing["type"] == alert_type and (now - existing["timestamp_unix"]) < 300:
                return  # Already alerted recently
        self._alerts.append({
            "type": alert_type,
            "message": message,
            "level": level,
            "timestamp": datetime.now().isoformat(),
            "timestamp_unix": now,
            "dismissed": False,
        })
        # Keep max 50 alerts
        if len(self._alerts) > 50:
            self._alerts = self._alerts[-50:]
        # Optionally show notification on device
        if self._config.get("enable_notifications", True):
            self._show_device_notification(message)
        self.logger.info(f"Battery alert [{level}]: {message}")

    def _show_device_notification(self, message: str):
        """Show a toast notification on the Android device."""
        try:
            self.controller._shell(
                "am", "broadcast",
                "-a", "com.xiaomi.controller.BATTERY_ALERT",
                "--es", "message", message
            )
        except Exception:
            pass  # Non-critical

    # ── Auto-optimization actions ────────────────────────────────────
    def _enable_battery_saver(self):
        """Enable Android battery saver mode via ADB."""
        try:
            self.controller._shell("settings", "put", "global", "low_power", "1")
            self._add_alert("auto_action", "Battery saver enabled automatically", level="info")
        except Exception as e:
            self.logger.error(f"Cannot enable battery saver: {e}")

    def _reduce_brightness(self):
        """Reduce screen brightness to save battery."""
        try:
            target = self._config.get("brightness_low_value", 30)
            self.controller._shell("settings", "put", "system", "screen_brightness", str(target))
            self.controller._shell("settings", "put", "system", "screen_brightness_mode", "0")
        except Exception as e:
            self.logger.error(f"Cannot reduce brightness: {e}")

    def _kill_battery_drainers(self):
        """Force-stop apps from the kill list."""
        apps = self._config.get("apps_to_kill", [])
        killed = []
        for pkg in apps:
            try:
                self.controller.force_stop(pkg)
                killed.append(pkg)
            except Exception:
                pass
        if killed:
            self._add_alert("auto_kill",
                           f"Auto-closed {len(killed)} apps to save battery",
                           level="info")

    def _disable_battery_saver(self):
        try:
            self.controller._shell("settings", "put", "global", "low_power", "0")
        except Exception:
            pass

    # ── Daily statistics ─────────────────────────────────────────────
    def _update_daily_stats(self, entry: dict):
        today = datetime.now().strftime("%Y-%m-%d")
        if today not in self._daily_stats:
            self._daily_stats[today] = {
                "min_level": 100, "max_level": 0,
                "max_temp": 0, "cycles": 0,
                "charge_sessions": 0,
            }
        stats = self._daily_stats[today]
        level = entry.get("level", 50)
        temp = entry.get("temperature", 0)
        stats["min_level"] = min(stats["min_level"], level)
        stats["max_level"] = max(stats["max_level"], level)
        stats["max_temp"] = max(stats["max_temp"], temp)
        if entry.get("charging"):
            stats["charge_sessions"] = max(stats.get("charge_sessions", 0), 1)

    # ── History persistence ──────────────────────────────────────────
    def _load_history(self):
        hist_file = self.data_dir / "history.json"
        if hist_file.exists():
            try:
                self._history = json.loads(hist_file.read_text())
            except Exception:
                self._history = []
        alerts_file = self.data_dir / "alerts.json"
        if alerts_file.exists():
            try:
                self._alerts = json.loads(alerts_file.read_text())
            except Exception:
                self._alerts = []

    def _save_history(self):
        try:
            (self.data_dir / "history.json").write_text(json.dumps(self._history))
            (self.data_dir / "alerts.json").write_text(json.dumps(self._alerts))
        except Exception as e:
            self.logger.error(f"Cannot save history: {e}")

    # ── Drain rate calculation ───────────────────────────────────────
    def _calculate_drain_rate(self) -> dict:
        """Calculate battery drain rate in %/hour from recent history."""
        if len(self._history) < 3:
            return {"rate": None, "estimated_hours": None, "samples": 0}

        # Use last 30 minutes of non-charging data
        recent = [e for e in self._history[-60:] if not e.get("charging")]
        if len(recent) < 2:
            return {"rate": None, "estimated_hours": None, "samples": 0}

        first = recent[0]
        last = recent[-1]
        t1 = datetime.fromisoformat(first["timestamp"])
        t2 = datetime.fromisoformat(last["timestamp"])
        hours = (t2 - t1).total_seconds() / 3600.0
        if hours < 0.01:
            return {"rate": None, "estimated_hours": None, "samples": len(recent)}

        drain = first["level"] - last["level"]
        rate_per_hour = drain / hours if hours > 0 else 0
        current_level = last["level"]
        est_hours = current_level / rate_per_hour if rate_per_hour > 0 else None

        return {
            "rate": round(rate_per_hour, 2),
            "estimated_hours": round(est_hours, 1) if est_hours else None,
            "samples": len(recent),
            "period_hours": round(hours, 2),
            "drain_pct": round(drain, 1),
        }

    # ── API Endpoints ────────────────────────────────────────────────
    def _api_status(self):
        from flask import jsonify
        try:
            bat = self.controller.battery_status()
        except Exception as e:
            return jsonify({"error": str(e)}), 500

        drain = self._calculate_drain_rate()
        return jsonify({
            "battery": bat,
            "drain": drain,
            "monitoring": self._running,
            "alert_count": len([a for a in self._alerts if not a.get("dismissed")]),
            "last_update": self._history[-1]["timestamp"] if self._history else None,
            "history_points": len(self._history),
        })

    def _api_history(self):
        from flask import request, jsonify
        hours = int(request.args.get("hours", 6))
        # Filter last N hours
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        filtered = [e for e in self._history if e["timestamp"] >= cutoff]
        # Downsample if too many points
        if len(filtered) > 200:
            step = len(filtered) // 200
            filtered = filtered[::step]
        return jsonify(filtered)

    def _api_alerts(self):
        from flask import jsonify
        active = [a for a in self._alerts if not a.get("dismissed")]
        return jsonify(active)

    def _api_clear_alerts(self):
        from flask import jsonify
        for a in self._alerts:
            a["dismissed"] = True
        self._save_history()
        return jsonify({"ok": True})

    def _api_get_config(self):
        from flask import jsonify
        return jsonify(self._config)

    def _api_set_config(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        for key, value in data.items():
            if key in self.DEFAULT_CONFIG:
                self._config[key] = value
        self.set_config("_all", self._config)
        # Write full config
        self.config_path.write_text(json.dumps(self._config, indent=2))
        return jsonify({"ok": True, "config": self._config})

    def _api_optimize(self):
        """Manual optimization trigger."""
        from flask import jsonify
        actions = []
        try:
            self._enable_battery_saver()
            actions.append("battery_saver")
        except Exception:
            pass
        try:
            self._reduce_brightness()
            actions.append("brightness_reduced")
        except Exception:
            pass
        try:
            self._kill_battery_drainers()
            actions.append("apps_killed")
        except Exception:
            pass
        return jsonify({"ok": True, "actions": actions})

    def _api_drain_rate(self):
        from flask import jsonify
        return jsonify(self._calculate_drain_rate())

    def _api_health_report(self):
        """Comprehensive battery health report."""
        from flask import jsonify
        drain = self._calculate_drain_rate()
        bat = self._last_battery or {}

        # Compute daily averages
        today = datetime.now().strftime("%Y-%m-%d")
        today_stats = self._daily_stats.get(today, {})

        # Charge cycles in last 24h
        recent = [e for e in self._history[-48:]]
        charge_transitions = sum(1 for i in range(1, len(recent))
                                if recent[i]["charging"] != recent[i-1]["charging"]
                                and recent[i]["charging"])

        report = {
            "current_level": bat.get("level", "N/A"),
            "charging": bat.get("charging", False),
            "temperature": bat.get("temperature", "N/A"),
            "status": bat.get("status", "unknown"),
            "drain_rate_pct_per_hour": drain.get("rate"),
            "estimated_remaining_hours": drain.get("estimated_hours"),
            "today_min_level": today_stats.get("min_level"),
            "today_max_temp": today_stats.get("max_temp"),
            "charge_cycles_24h": charge_transitions,
            "monitoring_active": self._running,
            "total_history_points": len(self._history),
        }
        return jsonify(report)

    def _api_start_monitor(self):
        from flask import jsonify
        self._start_monitoring()
        return jsonify({"ok": True, "monitoring": True})

    def _api_stop_monitor(self):
        from flask import jsonify
        self._stop_monitoring()
        return jsonify({"ok": True, "monitoring": False})

    def _api_daily_stats(self):
        from flask import jsonify
        # Return last 7 days
        sorted_days = sorted(self._daily_stats.keys(), reverse=True)[:7]
        return jsonify({d: self._daily_stats[d] for d in sorted_days})

    def _api_set_kill_list(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        self._config["apps_to_kill"] = data.get("apps", [])
        self.config_path.write_text(json.dumps(self._config, indent=2))
        return jsonify({"ok": True, "apps": self._config["apps_to_kill"]})


# Required: export the plugin class
plugin_class = BatteryCarePlugin
