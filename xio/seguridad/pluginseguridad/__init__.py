"""
Plugin Registry – Auto-discovery, loading, and lifecycle management.
Scans the plugins/ directory for valid plugins and manages their lifecycle.
"""

import os
import sys
import json
import importlib
import importlib.util
from pathlib import Path
from typing import Optional
from .base import PluginBase, PluginContext


class PluginRegistry:
    """
    Manages all plugins: discovery, loading, enabling/disabling, and teardown.

    Plugin directory structure:
        plugins/
        ├── __init__.py           (this file)
        ├── base.py               (PluginBase + PluginContext)
        ├── battery_care/
        │   ├── __init__.py       (must export `plugin_class`)
        │   ├── manifest.json     (optional, overrides class attributes)
        │   ├── plugin.py         (actual implementation)
        │   ├── config.json       (auto-generated, user config)
        │   └── static/           (plugin-specific static assets)
        └── ...
    """

    def __init__(self, context: PluginContext):
        self.context = context
        self._plugins: dict[str, PluginBase] = {}
        self._plugins_dir = Path(context._plugins_dir)

    def discover(self) -> list[str]:
        """Scan plugins/ directory and return list of found plugin IDs."""
        found = []
        if not self._plugins_dir.exists():
            return found
        for entry in sorted(self._plugins_dir.iterdir()):
            if entry.is_dir() and not entry.name.startswith((".", "_")):
                init_file = entry / "__init__.py"
                if init_file.exists():
                    found.append(entry.name)
        return found

    def load_plugin(self, plugin_id: str) -> Optional[PluginBase]:
        """Load a single plugin by ID."""
        plugin_dir = self._plugins_dir / plugin_id
        init_file = plugin_dir / "__init__.py"

        if not init_file.exists():
            self.context.logger.error(f"Plugin {plugin_id}: no __init__.py found")
            return None

        try:
            # Load the plugin module dynamically
            module_name = f"plugins.{plugin_id}"
            spec = importlib.util.spec_from_file_location(module_name, init_file)
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            # Get the plugin class
            plugin_class = getattr(module, "plugin_class", None)
            if plugin_class is None:
                self.context.logger.error(f"Plugin {plugin_id}: no 'plugin_class' exported")
                return None

            # Instantiate
            instance = plugin_class(self.context)
            instance.plugin_id = plugin_id  # Ensure ID is set

            # Load manifest.json overrides
            manifest_file = plugin_dir / "manifest.json"
            if manifest_file.exists():
                try:
                    manifest = json.loads(manifest_file.read_text())
                    for key in ["name", "version", "description", "author", "icon",
                                "category", "permissions"]:
                        if key in manifest:
                            setattr(instance, key, manifest[key])
                    
                    # Validate permissions
                    from .plugin_guardian.security_hook import PermissionEnforcer
                    valid, errors = PermissionEnforcer.validate_manifest(manifest, plugin_id)
                    if not valid:
                        self.context.logger.warning(f"Plugin {plugin_id}: invalid permissions: {errors}")
                except ImportError:
                    pass  # plugin_guardian no cargado aún
                except Exception as e:
                    self.context.logger.warning(f"Plugin {plugin_id}: bad manifest.json: {e}")

            # Lifecycle: load
            instance.on_load()
            instance.enabled = True

            self._plugins[plugin_id] = instance
            self.context.logger.info(f"Plugin loaded: {plugin_id} v{instance.version}")
            return instance

        except Exception as e:
            self.context.logger.error(f"Failed to load plugin {plugin_id}: {e}")
            import traceback
            traceback.print_exc()
            return None

    def unload_plugin(self, plugin_id: str):
        """Unload a plugin, calling its cleanup hooks."""
        plugin = self._plugins.pop(plugin_id, None)
        if plugin:
            try:
                plugin.on_disable()
                plugin.on_unload()
            except Exception as e:
                self.context.logger.error(f"Error unloading {plugin_id}: {e}")

    def enable_plugin(self, plugin_id: str) -> bool:
        plugin = self._plugins.get(plugin_id)
        if plugin and not plugin.enabled:
            plugin.on_enable()
            plugin.enabled = True
            return True
        return False

    def disable_plugin(self, plugin_id: str) -> bool:
        plugin = self._plugins.get(plugin_id)
        if plugin and plugin.enabled:
            plugin.on_disable()
            plugin.enabled = False
            return True
        return False

    def load_all(self) -> dict[str, PluginBase]:
        """Discover and load all plugins."""
        for pid in self.discover():
            if pid not in self._plugins:
                self.load_plugin(pid)
        return self._plugins

    def unload_all(self):
        """Unload all plugins (shutdown hook)."""
        for pid in list(self._plugins.keys()):
            self.unload_plugin(pid)
        self.context.cancel_all()

    def get(self, plugin_id: str) -> Optional[PluginBase]:
        return self._plugins.get(plugin_id)

    def get_all(self) -> dict[str, PluginBase]:
        return dict(self._plugins)

    def get_manifests(self) -> list[dict]:
        """Return manifests for all loaded plugins (for the API/UI)."""
        return [p.to_manifest() for p in self._plugins.values()]

    def get_all_routes(self) -> list[dict]:
        """Collect all routes from all plugins for Flask registration."""
        routes = []
        for plugin in self._plugins.values():
            if plugin.enabled:
                routes.extend(plugin.get_routes())
        return routes

    def install_from_path(self, source_path: str) -> Optional[str]:
        """
        Install a plugin from a local directory or zip file.
        Returns the plugin_id on success.
        """
        source = Path(source_path)
        if source.is_dir():
            # Copy directory into plugins/
            plugin_id = source.name
            dest = self._plugins_dir / plugin_id
            if dest.exists():
                self.unload_plugin(plugin_id)
            import shutil
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(source, dest)
            return plugin_id
        elif source.suffix == ".zip":
            import zipfile
            import shutil
            extract_dir = self._plugins_dir / "__temp_extract"
            if extract_dir.exists():
                shutil.rmtree(extract_dir)
            with zipfile.ZipFile(source, "r") as zf:
                zf.extractall(extract_dir)
            # Find the actual plugin folder
            contents = list(extract_dir.iterdir())
            if len(contents) == 1 and contents[0].is_dir():
                plugin_id = contents[0].name
            else:
                plugin_id = source.stem
            dest = self._plugins_dir / plugin_id
            if dest.exists():
                shutil.rmtree(dest)
            if len(contents) == 1 and contents[0].is_dir():
                contents[0].rename(dest)
            else:
                extract_dir.rename(dest)
            if extract_dir.exists():
                shutil.rmtree(extract_dir)
            return plugin_id
        return None
