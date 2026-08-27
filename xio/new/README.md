> Indice operativo: ver xio/RUNBOOK.md

# Xiaomi ADB Web Controller + Plugin System

Dashboard web para controlar remotamente un Xiaomi Android vía ADB, con un **sistema de plugins modular** que permite extender funcionalidades sin modificar el core.

```
┌─────────────────────────────────────────────────────────┐
│                    Web Dashboard                         │
│  Dashboard │ Input │ Apps │ Files │ Automation │ ...    │
└──────────────────────┬──────────────────────────────────┘
                       │ REST API
┌──────────────────────┴──────────────────────────────────┐
│                     Flask Server                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │              Plugin Registry                     │    │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐        │    │
│  │  │ Battery  │ │ Xiaomi   │ │  Your    │        │    │
│  │  │   Care   │ │ Enhanced │ │  Plugin  │  ...   │    │
│  │  └──────────┘ └──────────┘ └──────────┘        │    │
│  └─────────────────────────────────────────────────┘    │
│                       │                                  │
│              XiaomiController (ADB)                      │
└──────────────────────┬──────────────────────────────────┘
                       │ ADB (USB / WiFi)
                ┌──────┴──────┐
                │   Xiaomi    │
                │   Phone     │
                └─────────────┘
```

## Quick Start

```bash
pip install flask
# Asegúrate de tener `adb` en el PATH y el dispositivo conectado
python server.py
# Abre http://localhost:5000
```

## Estructura del Proyecto

```
.
├── server.py                  # Flask server + rutas core
├── xiaomi_controller.py       # Wrapper ADB (tap, swipe, screenshot, etc.)
├── static/
│   └── index.html             # Dashboard SPA (una sola página)
├── plugins/                   # Base + _template + legacy (NO es la fuente de plugins activos)
│   ├── __init__.py            # PluginRegistry: auto-descubrimiento
│   ├── base.py                # PluginBase + PluginContext
│   ├── _template/             # Template para nuevos plugins
│   └── [legacy plugins]/      # Plugins retirados
├── ../new-plugins/            # ← LIVE: Conjunto de 30 plugins en deploy
│   ├── plugin_guardian/
│   ├── battery_care/
│   └── [28 mas plugins]
└── data/                      # Datos persistentes (macros, historial, etc.)
    ├── macros.json
    └── <plugin_id>/           # Datos por plugin
```

**Plugin Resolution (server.py):** env `PLUGINS_DIR` -> `../new-plugins/` (default) -> fallback `plugins/`

## Sistema de Plugins

### ¿Qué es un plugin?

Un plugin es una carpeta dentro de `plugins/` que contiene al menos:
- `__init__.py` que exporta `plugin_class`
- `manifest.json` con metadata

El server **descubre automáticamente** todos los plugins al iniciar, los carga, y registra sus rutas.

### Crear un Plugin

**1. Estructura mínima:**
```
plugins/my_plugin/
├── __init__.py
└── manifest.json
```

**2. manifest.json:**
```json
{
  "name": "Mi Plugin",
  "version": "1.0.0",
  "description": "Descripción de lo que hace",
  "author": "Tu nombre",
  "icon": "battery",
  "category": "automation",
  "permissions": ["battery", "apps"]
}
```

**3. __init__.py:**
```python
from plugins.base import PluginBase

class MyPlugin(PluginBase):
    plugin_id = "my_plugin"
    name = "Mi Plugin"
    version = "1.0.0"
    
    def on_load(self):
        # Registrar rutas API
        self.register_route("/hello", self._api_hello, methods=["GET"])
        self.register_route("/action", self._api_action, methods=["POST"])
        
        # Iniciar tarea en background (opcional)
        self.context.schedule("my_task", self._background_work, interval_seconds=60)
    
    def on_enable(self):
        self.logger.info("Plugin activado!")
    
    def on_disable(self):
        self.logger.info("Plugin desactivado")
    
    def _api_hello(self):
        from flask import jsonify
        return jsonify({"message": "Hello from my plugin!"})
    
    def _api_action(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        # Usar el controller para controlar el dispositivo
        self.controller.tap(540, 1200)
        return jsonify({"ok": True})
    
    def _background_work(self):
        # Tarea que se ejecuta cada 60 segundos
        status = self.controller.battery_status()
        if status.get("level", 100) < 10:
            self.logger.warning("Battery critically low!")

# Requerido: exportar la clase
plugin_class = MyPlugin
```

**4. Las rutas quedan disponibles en:**
```
GET  /api/plugins/my_plugin/hello
POST /api/plugins/my_plugin/action
```

### API de PluginBase

| Método / Propiedad | Descripción |
|---|---|
| `self.controller` | Instancia de `XiaomiController` |
| `self.logger` | Logger compartido |
| `self.data_dir` | Directorio persistente del plugin |
| `self.register_route(rule, func, methods)` | Registrar ruta Flask |
| `self.get_config(key, default)` | Leer configuración |
| `self.set_config(key, value)` | Guardar configuración |
| `self.context.schedule(name, func, interval)` | Tarea en background |
| `self.context.cancel_schedule(name)` | Cancelar tarea |
| `self.on_load()` | Hook: al cargar |
| `self.on_enable()` | Hook: al activar |
| `self.on_disable()` | Hook: al desactivar |
| `self.on_unload()` | Hook: al descargar |

### API del Controller (disponible via `self.controller`)

```python
# Input
controller.tap(x, y)
controller.swipe(x1, y1, x2, y2, duration_ms=300)
controller.long_press(x, y, duration_ms=1000)
controller.text("hello")
controller.named_key("home")  # home/back/recents/power/volume_up/volume_down

# Screen
controller.screenshot()  # → bytes PNG
controller.screen_size()  # → {width, height}

# Apps
controller.list_launchable_packages()  # → [{package, label, activity}]
controller.list_installed_packages()
controller.open_app(package)
controller.force_stop(package)
controller.uninstall(package)

# Files
controller.list_dir(path)
controller.push(local, remote)
controller.pull(remote, local)
controller.push_bytes(data, remote)
controller.pull_bytes(remote)  # → bytes
controller.delete_file(path)
controller.mkdir(path)

# Battery
controller.battery_status()  # → {level, charging, temperature, ...}
controller.network_info()
controller.device_info()

# UI Automation
controller.dump_ui()  # → [{text, bounds, center_x, center_y, clickable, ...}]
controller.tap_element(element)

# Macros
controller.run_sequence(actions, delay_ms)
```

### Permisos

Declara en `manifest.json` lo que tu plugin necesita:
- `battery` — Leer estado de batería
- `files` — Acceso al sistema de archivos del dispositivo
- `apps` — Listar/instalar/desinstalar apps
- `input` — Enviar taps, swipes, teclas
- `network` — Info de red
- `system` — Comandos de sistema (brillo, volume, etc.)

### Instalar Plugins

**Desde la UI:**
1. Ir a "Manage Plugins"
2. Click "Install Plugin"
3. Subir un archivo `.zip` con la estructura del plugin

**Manualmente:**
1. Copiar la carpeta del plugin a `plugins/`
2. Reiniciar el servidor (o recargar desde la UI)

**Desde código (para agentes/CI):**
```bash
# Zip y upload
cd plugins/my_plugin && zip -r ../my_plugin.zip .
curl -F "file=@plugins/my_plugin.zip" http://localhost:5000/api/plugins/install
```

## Casos de Uso para Plugins

### 1. Battery Care (incluido)
Monitoreo, alertas y optimización de batería sin root:
- Historial con gráficos
- Alertas de temperatura y nivel crítico
- Auto-activación de battery saver
- Cierre automático de apps que consumen batería
- Cálculo de drain rate y tiempo restante

### 2. Integración con Repos Externos
El plugin `example_tool` demuestra cómo conectar un repo de GitHub externo:
```python
# Patrón 1: Import directo
from external_repo import XiaomiEnhancer
enhancer = XiaomiEnhancer(self.controller)

# Patrón 2: Subprocess
import subprocess
result = subprocess.run(["python", "-m", "tool", "action"], capture_output=True)

# Patrón 3: Comandos Xiaomi-specific via ADB
self.controller._shell("settings", "put", "system", "...")
```

### 3. Ideas para Plugins

- **Game Turbo Controller**: Activar/desactivar game turbo, perfiles por juego
- **Screen Recorder**: Grabación de pantalla con control de calidad
- **Notification Manager**: Leer y gestionar notificaciones
- **WiFi Manager**: Cambiar redes, mostrar contraseña WiFi
- **App Cloner**: Gestión de dual apps
- **Thermal Monitor**: Monitoreo de temperatura por zona
- **Backup Automation**: Backup periódico de datos
- **Accessibility Bridge**: Control por voz o gestos
- **Multi-device**: Control de varios dispositivos simultáneamente
- **Custom ROM Utils**: Herramientas para dispositivos con custom ROM

## Endpoints Core (no-plugin)

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/status` | Estado completo del dispositivo |
| GET | `/api/screen` | Screenshot PNG |
| POST | `/api/tap` | Tap en coordenadas |
| POST | `/api/swipe` | Swipe |
| POST | `/api/text` | Escribir texto |
| POST | `/api/key` | Tecla nombrada |
| GET | `/api/apps` | Apps con launcher |
| POST | `/api/open` | Abrir app |
| POST | `/api/force-stop` | Forzar cierre |
| POST | `/api/uninstall` | Desinstalar |
| GET | `/api/browse?path=` | Listar directorio |
| POST | `/api/file/upload` | Subir archivo (multipart) |
| GET | `/api/file/download?path=` | Descargar archivo |
| GET | `/api/ui-tree` | Dump UI hierarchy |
| POST | `/api/tap-element` | Tap en elemento UI |
| GET | `/api/macros` | Listar macros |
| POST | `/api/macros` | Crear/actualizar macro |
| POST | `/api/macros/<id>/run` | Ejecutar macro |

### Endpoints de Plugins

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/plugins` | Listar todos los plugins |
| POST | `/api/plugins/<id>/enable` | Activar plugin |
| POST | `/api/plugins/<id>/disable` | Desactivar plugin |
| POST | `/api/plugins/<id>/reload` | Recargar plugin |
| POST | `/api/plugins/install` | Instalar plugin (.zip) |
| DELETE | `/api/plugins/<id>` | Eliminar plugin |
| * | `/api/plugins/<id>/*` | Rutas registradas por el plugin |

## Variables de Entorno

```bash
ADB_SERIAL=192.168.1.100:5555   # Conectar por WiFi (default: USB auto-detect)
```

## Licencia

MIT
