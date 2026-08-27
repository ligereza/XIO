> Indice operativo: ver xio/RUNBOOK.md

# Plugin Template

This is a starting template for creating new plugins.

## Steps to create a plugin:

1. **Copy this folder** and rename it:
   ```bash
   cp -r plugins/_template plugins/my_awesome_plugin
   ```

2. **Edit `manifest.json`** with your plugin's metadata.

3. **Edit `__init__.py`**:
   - Change `plugin_id` to match your folder name
   - Update class attributes (name, version, description, etc.)
   - Implement your routes in `on_load()`
   - Add your logic

4. **Restart the server** or reload from the UI.

## Tips:

- Routes are auto-prefixed with `/api/plugins/<plugin_id>/`
- Use `self.controller` to interact with the device
- Use `self.get_config()` / `self.set_config()` for persistent settings
- Use `self.data_dir` for storing data files
- Use `self.context.schedule()` for background tasks
- The dashboard auto-generates a nav item for enabled plugins
