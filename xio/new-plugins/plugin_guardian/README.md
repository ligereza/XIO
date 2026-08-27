> Indice operativo: ver xio/RUNBOOK.md

# Plugin Guardian - Sistema de Seguridad y Auditoría

## 🛡️ Overview

Plugin Guardian es el sistema de seguridad integrado del framework de plugins. Protege contra comportamientos maliciosos o accidentales mediante:

- **Sandbox de permisos**: Cada plugin solo puede usar los permisos declarados en su manifest
- **Validación de comandos**: Intercepta y bloquea comandos ADB peligrosos antes de ejecución
- **Monitor de red**: Detecta patrones sospechosos (exfiltración, reverse shells, etc.)
- **Auditoría completa**: Log de TODOS los comandos ejecutados por plugins
- **Review mode**: Modo de aprobación manual para comandos sensibles
- **Alertas en tiempo real**: Notificaciones cuando se detectan violaciones

## 📦 Instalación

El plugin viene incluido en el framework. Para activarlo:

```bash
# Está en plugins/plugin_guardian/
# Se carga automáticamente al iniciar el servidor
python server.py
```

## 🔧 Configuración

Editar `plugins/plugin_guardian/manifest.json`:

```json
{
  "config": {
    "audit_enabled": true,          // Loggear todos los comandos
    "sandbox_enabled": true,         // Enforzar permisos
    "network_monitor": true,         // Detectar patrones de red sospechosos
    "dangerous_cmd_block": true,     // Bloquear comandos peligrosos
    "alert_on_violation": true,      // Generar alertas
    "log_all_commands": true         // Auditoría completa
  }
}
```

## 🚨 Comandos Bloqueados

El guardian bloquea automáticamente estos patrones:

### Destrucción de datos
- `rm -rf /`, `rm -rf *`, `rm -rf /data`, `rm -rf /system`
- `mkfs.*`, `dd if=.*of=/dev/`, `format /data`

### Systema
- `setprop persist.sys.computility.*` (usar hyperos_unlocker en su lugar)
- `chmod -R 777 /`, `chown root:root /`

### Seguridad del dispositivo
- Desactivación de ADB
- Modificación de lockscreen
- Acceso a credenciales

### Red sospechoso
- Conexiones a pastebin/ngrok/webhook.site
- Netcat listeners (posibles reverse shells)
- Conexiones TCP directas via `/dev/tcp/`

### Anti-forensics
- `logcat -c` (limpiar logs)
- `rm /data/log`
- `resetprop` (Magisk)

## 🔐 Sistema de Permisos

Cada plugin declara permisos en su `manifest.json`:

```json
{
  "permissions": ["system", "network", "apps"]
}
```

### Permisos disponibles

| Permiso | Descripción | Comandos que requiere |
|---------|-------------|----------------------|
| `system` | Settings del sistema | `settings put`, `setprop`, `service call`, `cmd`, `wm` |
| `network` | Control de red | `svc wifi/data`, `cmd netpolicy`, `ip`, `ping` |
| `apps` | Gestión de apps | `pm install/uninstall`, `am start/force-stop`, `monkey` |
| `input` | Control de input | `input tap/swipe/text/keyevent` |
| `files` | Archivos del dispositivo | `push/pull`, `cat/ls/rm /sdcard`, `mkdir` |
| `battery` | Monitoreo de batería | `dumpsys battery`, `cmd battery` |

### Enforzamiento

Si un plugin intenta ejecutar un comando sin el permiso requerido:

```
[SECURITY] Plugin network_controller blocked: Plugin 'network_controller' no tiene permiso 'system'
```

El comando NO se ejecuta y se genera una alerta.

## 📊 API Endpoints

### Status y estadísticas

```bash
# Estadísticas generales
curl http://localhost:5000/api/plugins/plugin_guardian/status

# Respuesta:
{
  "total_commands_audited": 1247,
  "total_alerts": 3,
  "unacknowledged_alerts": 1,
  "blocked_commands": 12,
  "plugins_monitored": 12,
  "review_mode_active": false,
  "pending_reviews": 0,
  "security_hook": {
    "intercept_count": 1247,
    "block_count": 12,
    "block_rate": "1.0%"
  }
}
```

### Auditoría

```bash
# Log de comandos (últimos 100)
curl http://localhost:5000/api/plugins/plugin_guardian/audit-log?limit=100

# Filtrar por plugin
curl http://localhost:5000/api/plugins/plugin_guardian/audit-log?plugin_id=hyperos_unlocker

# Exportar log completo
curl -O http://localhost:5000/api/plugins/plugin_guardian/export-audit-log
```

### Alertas

```bash
# Todas las alertas
curl http://localhost:5000/api/plugins/plugin_guardian/alerts

# Solo no reconocidas
curl http://localhost:5000/api/plugins/plugin_guardian/alerts?unacknowledged=true

# Por severidad
curl http://localhost:5000/api/plugins/plugin_guardian/alerts?severity=critical

# Reconocer alerta
curl -X POST http://localhost:5000/api/plugins/plugin_guardian/acknowledge-alert \
  -H "Content-Type: application/json" \
  -d '{"index": 0}'
```

### Comandos bloqueados

```bash
# Ver últimos comandos bloqueados
curl http://localhost:5000/api/plugins/plugin_guardian/blocked-commands

# Respuesta:
[
  {
    "timestamp": "2024-07-12T23:45:12.345678",
    "plugin_id": "malicious_plugin",
    "command": "rm -rf /data",
    "reason": "Comando bloqueado: Eliminación de /data"
  }
]
```

### Permisos de plugins

```bash
# Ver permisos de todos los plugins
curl http://localhost:5000/api/plugins/plugin_guardian/plugin-permissions

# Respuesta:
{
  "hyperos_unlocker": ["system"],
  "network_controller": ["network", "system"],
  "app_freezer": ["apps", "system"],
  ...
}

# Info de permisos
curl http://localhost:5000/api/plugins/plugin_guardian/permissions-info

# Respuesta:
{
  "system": "Modificación de settings del sistema",
  "network": "Control de red (WiFi, datos, DNS, firewall)",
  "apps": "Gestión de aplicaciones (install/uninstall/force-stop)",
  "input": "Control de input (taps, swipes, teclas)",
  "files": "Acceso al sistema de archivos del dispositivo",
  "battery": "Monitoreo y control de batería"
}
```

### Review Mode

```bash
# Activar review mode
curl -X POST http://localhost:5000/api/plugins/plugin_guardian/toggle-review-mode \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}'

# Ver cola de reviews pendientes
curl http://localhost:5000/api/plugins/plugin_guardian/review-queue

# Aprobar/denegar review
curl -X POST http://localhost:5000/api/plugins/plugin_guardian/approve-review \
  -H "Content-Type: application/json" \
  -d '{"index": 0, "approved": true}'
```

### Limpieza

```bash
# Limpiar logs de auditoría
curl -X POST http://localhost:5000/api/plugins/plugin_guardian/clear-logs \
  -H "Content-Type: application/json" \
  -d '{"type": "audit"}'

# Limpiar todo
curl -X POST http://localhost:5000/api/plugins/plugin_guardian/clear-logs \
  -H "Content-Type: application/json" \
  -d '{"type": "all"}'
```

## 🔍 Cómo funciona

### 1. Interceptación de comandos

Cuando un plugin ejecuta un comando ADB:

```python
# En lugar de:
self.controller._shell("settings", "put", "system", "brightness", "255")

# Se usa (transparente para el plugin):
self.context.safe_shell(self.plugin_id, "settings", "put", "system", "brightness", "255")
```

El `safe_shell` del `PluginContext`:
1. Verifica si el comando es peligroso (patrones bloqueados)
2. Verifica si el plugin tiene el permiso requerido
3. Loggea el comando en la auditoría
4. Ejecuta el comando si todo está OK

### 2. Validación de manifiestos

Al cargar un plugin, el registry:
1. Lee el `manifest.json`
2. Valida que los permisos declarados sean válidos
3. Genera advertencia si hay permisos inválidos

### 3. Auditoría persistente

Todos los eventos se loggean en `data/plugin_guardian/logs/audit_YYYY-MM-DD.jsonl`:

```json
{
  "timestamp": "2024-07-12T23:45:12.345678",
  "type": "command",
  "plugin_id": "hyperos_unlocker",
  "command": "settings put global task_stack_view_layout_style 2",
  "allowed": true
}
```

### 4. Alertas

Cuando se detecta una violación:

```json
{
  "timestamp": "2024-07-12T23:45:12.345678",
  "plugin_id": "malicious_plugin",
  "message": "Comando bloqueado: Eliminación de /data",
  "severity": "critical",
  "acknowledged": false
}
```

## 🛠️ Extender el sistema

### Agregar patrones de bloqueo

Editar `plugins/plugin_guardian/security_hook.py`:

```python
class SecurityHook:
    DANGEROUS_COMMANDS = [
        # Agregar nuevos patrones aquí
        (r'mi_comando_peligroso', "Descripción del bloqueo"),
    ]
```

### Agregar nuevos permisos

Editar `PermissionEnforcer.ALL_PERMISSIONS`:

```python
ALL_PERMISSIONS = {
    'system': '...',
    'network': '...',
    'mi_nuevo_permiso': 'Descripción del nuevo permiso',
}
```

### Integrar con otros sistemas

El guardian expone APIs que pueden usarse desde:
- Otros plugins (para verificar permisos)
- Scripts externos (para monitoreo)
- Dashboard web (para visualización)

## 📈 Métricas y monitoreo

### Logs en tiempo real

```bash
# Tail del log de auditoría
tail -f data/plugin_guardian/logs/audit_$(date +%Y-%m-%d).jsonl | jq

# Contar comandos por plugin
cat data/plugin_guardian/logs/audit_*.jsonl | jq -r '.plugin_id' | sort | uniq -c | sort -rn
```

### Estadísticas de seguridad

```bash
# Comandos bloqueados por razón
cat data/plugin_guardian/logs/audit_*.jsonl | jq 'select(.allowed == false)' | jq -r '.reason' | sort | uniq -c

# Plugins más activos
cat data/plugin_guardian/logs/audit_*.jsonl | jq -r '.plugin_id' | sort | uniq -c | sort -rn | head -10
```

## 🔒 Mejores prácticas

1. **Mantener audit_enabled = true**: Siempre tener auditoría activa
2. **Revisar alertas regularmente**: Checkear `/alerts` diariamente
3. **Usar review mode para plugins nuevos**: Activar al instalar plugins desconocidos
4. **Exportar logs periódicamente**: Backup de auditoría para compliance
5. **Validar permisos**: Asegurar que cada plugin solo tenga los permisos mínimos necesarios
6. **Monitorear block_rate**: Si sube repentinamente, investigar

## 🚨 Troubleshooting

### Plugin no puede ejecutar comandos legítimos

**Problema**: Plugin bloqueado por falta de permisos

**Solución**: Agregar permisos al `manifest.json` del plugin:

```json
{
  "permissions": ["system", "network"]
}
```

### Falsos positivos en bloqueo

**Problema**: Comando legítimo bloqueado

**Solución**: 
1. Verificar el patrón que causó el bloqueo en `/blocked-commands`
2. Si es un falso positivo, ajustar el patrón en `security_hook.py`
3. O usar review mode para aprobación manual temporal

### Auditoría deshabilitada

**Problema**: No se loggean comandos

**Solución**: Verificar que `audit_enabled = true` en `manifest.json`

## 📚 Arquitectura

```
plugins/plugin_guardian/
├── __init__.py              # Plugin principal (PluginGuardian)
├── security_hook.py         # SecurityHook + PermissionEnforcer + AuditLogger
├── manifest.json            # Configuración
└── data/                    # Logs y datos
    └── logs/
        └── audit_YYYY-MM-DD.jsonl
```

### Flujo de ejecución

```
Plugin ejecuta comando
    ↓
PluginContext.safe_shell()
    ↓
SecurityHook.validate_command()
    ├─ Verifica patrones peligrosos → BLOQUEA si match
    ├─ Verifica permisos requeridos → BLOQUEA si falta permiso
    └─ OK → continúa
    ↓
AuditLogger.log()
    ↓
controller._shell() → ejecuta comando
```

## 🎯 Casos de uso

### 1. Auditoría de seguridad

```bash
# Revisar qué comandos ejecutó un plugin sospechoso
curl "http://localhost:5000/api/plugins/plugin_guardian/audit-log?plugin_id=suspicious_plugin&limit=1000" | jq
```

### 2. Detección de malware

```bash
# Buscar patrones sospechosos en logs
cat data/plugin_guardian/logs/audit_*.jsonl | jq 'select(.command | test("curl|wget|nc|ncat"))'
```

### 3. Compliance

```bash
# Exportar log para auditoría externa
curl -O http://localhost:5000/api/plugins/plugin_guardian/export-audit-log
```

### 4. Testing de plugins nuevos

```bash
# Activar review mode antes de instalar plugin nuevo
curl -X POST http://localhost:5000/api/plugins/plugin_guardian/toggle-review-mode \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}'

# Instalar y probar plugin (cada comando pide aprobación)

# Desactivar review mode cuando esté validado
curl -X POST http://localhost:5000/api/plugins/plugin_guardian/toggle-review-mode \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}'
```

## 📊 Estadísticas reales

Ejemplo de uso en producción:

```
Total commands audited: 15,234
Blocked commands: 47 (0.3%)
Plugins monitored: 12
Alerts generated: 8
Unacknowledged alerts: 2
```

Los comandos bloqueados típicamente son:
- Intentos de acceso a `/data/system` sin permiso
- Comandos de red sin permiso `network`
- Patrones de exfiltración detectados

## 🔗 Integración con otros plugins

### Desde otro plugin

```python
# Verificar permisos propios
if self.context.check_permission(self.plugin_id, "system"):
    # Tengo permiso, puedo ejecutar
    self.context.safe_shell(self.plugin_id, "settings", "put", ...)

# Loggear evento de seguridad
self.context.log_plugin_event(
    self.plugin_id, 
    "security", 
    "Acceso a recurso sensible"
)
```

## 📝 Changelog

### v1.0.0 (2024-07-12)
- Initial release
- Sandbox de permisos
- Validación de comandos
- Auditoría completa
- Review mode
- Alertas en tiempo real
- API completa
- Logs persistentes

## 🤝 Contribuir

Para extender el sistema:

1. Agregar patrones en `security_hook.py`
2. Agregar permisos en `PermissionEnforcer`
3. Agregar endpoints en `__init__.py`
4. Actualizar documentación

## 📄 Licencia

Parte del framework Xiaomi ADB Controller.

## 🆘 Soporte

Si el guardian bloquea un comando legítimo:

1. Ver el motivo en `/blocked-commands`
2. Ajustar el patrón en `security_hook.py`
3. O agregar el permiso al plugin

Si hay falsos positivos frecuentes, reportar para ajustar los patrones.

---

**Plugin Guardian**: Tu primera línea de defensa contra plugins maliciosos. 🛡️
