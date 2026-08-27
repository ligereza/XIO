"""
Plugin Base Class – All plugins inherit from PluginBase.
Defines the contract: metadata, routes, lifecycle hooks, and optional UI contributions.
"""

import os
import json
from pathlib import Path
from abc import ABC, abstractmethod
from typing import Any


class PluginBase(ABC):
    """
    Base class for all Xiaomi Controller plugins.

    Lifecycle:
        1. __init__(context)     – Plugin receives shared context (controller, config, logger)
        2. on_load()             – Called when plugin is loaded; register routes, start background tasks
        3. on_enable()           – Called when user enables the plugin
        4. on_disable()          – Called when user disables the plugin
        5. on_unload()           – Called when server shuts down or plugin is removed

    A plugin contributes:
        - Routes (via register_routes)
        - Static assets (served from plugin's own static/ folder)
        - API endpoints (prefixed with /api/plugins/<plugin_id>/)
        - UI components (optional manifest.contributions)
        - Background tasks (via context.scheduler)
    """

    # ── Metadata (override via manifest.json or class attributes) ────
    plugin_id: str = ""
    name: str = ""
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    icon: str = "puzzle"          # icon name (from icon set)
    category: str = "general"     # general | automation | system | file | network | battery
    min_controller_version: str = "1.0.0"
    permissions: list[str] = []   # battery | files | apps | input | network | system

    def __init__(self, context: "PluginContext"):
        self.context = context
        self.enabled = False
        self._routes = []
        self._config = {}
        self._load_config()

    # ── Lifecycle hooks ──────────────────────────────────────────────
    def on_load(self):
        """Called once when plugin is first loaded. Register routes here."""
        pass

    def on_enable(self):
        """Called when plugin is enabled by user or auto-start."""
        pass

    def on_disable(self):
        """Called when plugin is disabled."""
        pass

    def on_unload(self):
        """Called when plugin is removed or server shuts down."""
        pass

    # ── Route registration ───────────────────────────────────────────
    def register_route(self, rule: str, view_func, methods=None, **options):
        """Register a Flask route. Auto-prefixed with /api/plugins/<plugin_id>/"""
        if methods is None:
            methods = ["GET"]
        prefix = f"/api/plugins/{self.plugin_id}"
        full_rule = f"{prefix}{rule}"
        self._routes.append({
            "rule": full_rule,
            "endpoint": f"{self.plugin_id}.{view_func.__name__}",
            "view_func": view_func,
            "methods": methods,
            "options": options,
        })
        return full_rule

    def get_routes(self) -> list[dict]:
        return self._routes

    # ── Configuration ────────────────────────────────────────────────
    @property
    def config_path(self) -> Path:
        plugin_dir = self.context.plugin_dir(self.plugin_id)
        return plugin_dir / "config.json"

    def _load_config(self):
        if self.config_path.exists():
            try:
                self._config = json.loads(self.config_path.read_text())
            except Exception as e:
                # corrupt config must not crash the plugin, but silence here
                # made persisted state vanish with zero trace (audit finding)
                self._config = {}
                try:
                    self.context.logger.warning(
                        "plugin %s: config.json unreadable, starting empty (%s)",
                        self.plugin_id or self.__class__.__name__, e)
                except Exception:
                    pass

    def get_config(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def set_config(self, key: str, value: Any):
        self._config[key] = value
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps(self._config, indent=2))

    # ── Helpers ──────────────────────────────────────────────────────
    @property
    def controller(self):
        """Shortcut to the XiaomiController instance."""
        return self.context.controller

    @property
    def logger(self):
        return self.context.logger

    @property
    def data_dir(self) -> Path:
        """Per-plugin persistent data directory."""
        d = self.context.data_dir / self.plugin_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def to_manifest(self) -> dict:
        """Serialize plugin metadata for the API/UI."""
        return {
            "id": self.plugin_id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "icon": self.icon,
            "category": self.category,
            "enabled": self.enabled,
            "permissions": self.permissions,
            "routes": [r["rule"] for r in self._routes],
            "config_keys": list(self._config.keys()),
        }


class PluginContext:
    """
    Shared context passed to every plugin. Provides access to:
    - controller: XiaomiController instance
    - logger: shared logger
    - data_dir: global data directory for all plugins
    - scheduler: simple background task scheduler
    - security_hook: intercepta y valida comandos (si plugin_guardian está activo)
    """

    def __init__(self, controller, logger, data_dir: Path):
        self.controller = controller
        self.logger = logger
        self.data_dir = data_dir
        self._plugins_dir = data_dir.parent / "plugins"
        self._scheduler_tasks = {}
        self._security_hook = None  # Se inicializa cuando plugin_guardian carga
        self._audit_logger = None

    def plugin_dir(self, plugin_id: str) -> Path:
        return self._plugins_dir / plugin_id

    def schedule(self, name: str, func, interval_seconds: float):
        """Schedule a recurring background task."""
        import threading

        def _loop():
            while name in self._scheduler_tasks:
                try:
                    func()
                except Exception as e:
                    self.logger.error(f"Plugin task '{name}' error: {e}")
                import time
                # Use an event for cancellable sleep
                evt = self._scheduler_tasks.get(name)
                if evt and evt.wait(timeout=interval_seconds):
                    break  # cancelled

        t = threading.Thread(target=_loop, daemon=True, name=f"plugin-{name}")
        self._scheduler_tasks[name] = threading.Event()
        t.start()
        return name

    def cancel_schedule(self, name: str):
        evt = self._scheduler_tasks.pop(name, None)
        if evt:
            evt.set()

    def cancel_all(self):
        for name in list(self._scheduler_tasks.keys()):
            self.cancel_schedule(name)

    # ── Security Methods ─────────────────────────────────────────────
    def set_security_hook(self, hook):
        """Registrar el security hook (llamado por plugin_guardian al cargar)."""
        self._security_hook = hook
        self.logger.info("Security hook registered")

    def set_audit_logger(self, logger):
        """Registrar el audit logger (llamado por plugin_guardian al cargar)."""
        self._audit_logger = logger
        self.logger.info("Audit logger registered")

    def safe_shell(self, plugin_id: str, *args, timeout=30):
        """
        Ejecutar comando ADB con validación de seguridad.
        Si plugin_guardian está activo, intercepta y valida el comando.
        Si no, ejecuta directamente (modo legacy).
        """
        command = ' '.join(str(a) for a in args)
        
        # Si hay security hook, validar
        if self._security_hook:
            allowed, reason, _ = self._security_hook.validate_command(plugin_id, command)
            if not allowed:
                self.logger.warning(f"[SECURITY] Plugin {plugin_id} blocked: {reason}")
                if self._audit_logger:
                    self._audit_logger.log_command(plugin_id, command, False, reason)
                raise PermissionError(f"Comando bloqueado por seguridad: {reason}")
        
        # Auditoría
        if self._audit_logger:
            self._audit_logger.log_command(plugin_id, command, True)
        
        # Ejecutar comando
        return self.controller._shell(*args, timeout=timeout)

    def check_permission(self, plugin_id: str, permission: str) -> bool:
        """Verificar si un plugin tiene un permiso específico."""
        if self._security_hook:
            return self._security_hook.guardian.check_permission(plugin_id, permission)
        return True  # Sin security hook, todo permitido (legacy mode)

    def log_plugin_event(self, plugin_id: str, event_type: str, message: str):
        """Loggear un evento de plugin."""
        if self._audit_logger:
            self._audit_logger.log({
                'type': event_type,
                'plugin_id': plugin_id,
                'message': message
            })
