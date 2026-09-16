> Indice operativo: ver xio/RUNBOOK.md

# Instalación - Plugin Guardian Security System

## Estado: ya integrado

El sistema de seguridad NO se instala desde un ZIP: ya está integrado en el
repositorio y se despliega con el runtime normal.

- Plugin: `xio/new-plugins/plugin_guardian/` (`__init__.py`, `security_hook.py`,
  `manifest.json`, `README.md`). Es la copia canónica y la que
  `run_server.sh` lleva al teléfono por overlay a `$HOME/xioplugins/`.
- Framework: los ganchos `safe_shell()`, `check_permission()`,
  `set_security_hook()`, `set_audit_logger()` y `log_plugin_event()` viven en
  `xio/new/plugins/base.py`, que es el `plugins.base` que importa `server.py`.

No queda un payload de instalación aparte. La copia duplicada que vivía en
`xio/seguridad/pluginseguridad/` se retiró: su `plugin_guardian/` ya había sido
archivado el 2026-07-18 y el resto era una versión estancada del framework.

Para desplegar, el procedimiento es el del runbook:

```bash
sh /sdcard/xio_termux/run_server.sh
```

Este documento conserva la verificación, el testing y el troubleshooting.

## Verificación

```bash
# 1. Verificar que plugin_guardian está cargado
curl http://localhost:5000/api/plugins | jq '.[] | select(.id == "plugin_guardian")'

# 2. Ver estado del security system
curl http://localhost:5000/api/plugins/plugin_guardian/status

# Respuesta esperada:
{
  "total_commands_audited": 0,
  "total_alerts": 0,
  "blocked_commands": 0,
  "plugins_monitored": 12,  # o el número de plugins que tengas
  "review_mode_active": false
}

# 3. Ver permisos de todos los plugins
curl http://localhost:5000/api/plugins/plugin_guardian/plugin-permissions

# 4. Ver información de permisos disponibles
curl http://localhost:5000/api/plugins/plugin_guardian/permissions-info
```

## Testing

```bash
# Test 1: Ejecutar un comando legítimo (debe funcionar)
curl -X POST http://localhost:5000/api/plugins/hyperos_unlocker/preset/apply \
  -H "Content-Type: application/json" \
  -d '{"preset": "balanced"}'

# Verificar que se auditó
curl http://localhost:5000/api/plugins/plugin_guardian/audit-log?limit=5

# Test 2: Verificar que el auditor está activo
curl http://localhost:5000/api/plugins/plugin_guardian/audit-log | jq length
# Debe mostrar > 0 después del test anterior

# Test 3: Activar review mode
curl -X POST http://localhost:5000/api/plugins/plugin_guardian/toggle-review-mode \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}'

# Verificar que está activo
curl http://localhost:5000/api/plugins/plugin_guardian/status | jq '.review_mode_active'
# Debe ser true

# Desactivar review mode
curl -X POST http://localhost:5000/api/plugins/plugin_guardian/toggle-review-mode \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}'
```

## Troubleshooting

### Plugin Guardian no aparece en /api/plugins

**Causa**: el overlay no llegó al directorio que el registro escanea
(`PLUGINS_DIR=$HOME/xioplugins`).

**Solución**:
```bash
ls -la $HOME/xioplugins/plugin_guardian/
# Debe mostrar: __init__.py, security_hook.py, manifest.json, README.md
```

### Error al cargar el módulo

**Causa**: falta `security_hook.py` o quedó a medio copiar.

**Solución**: volver a correr el overlay desde la fuente del repositorio.
```bash
sh /sdcard/xio_termux/run_server.sh
```

### Comandos legítimos bloqueados

**Causa**: El plugin no tiene los permisos necesarios en su manifest.json

**Solución**:
```bash
# Ver permisos actuales
curl http://localhost:5000/api/plugins/plugin_guardian/plugin-permissions | jq '.nombre_plugin'

# Editar manifest.json del plugin para agregar permisos faltantes
# Luego recargar el plugin
curl -X POST http://localhost:5000/api/plugins/nombre_plugin/reload
```

### Auditoría no funciona

**Causa**: El directorio data/plugin_guardian/logs/ no existe

**Solución**:
```bash
mkdir -p data/plugin_guardian/logs/
chmod 755 data/plugin_guardian/logs/
```

## Integración con plugins existentes

Los plugins existentes NO necesitan modificaciones. El sistema de seguridad es transparente:

1. Cuando un plugin usa `self.controller._shell()`, funciona como antes
2. Cuando un plugin usa `self.context.safe_shell()`, se beneficia de la validación
3. El guardian intercepta comandos a nivel del PluginContext

Para máxima seguridad, los plugins deberían migrar a `safe_shell()`:

```python
# Antes (legacy, sin validación):
self.controller._shell("settings", "put", "system", "brightness", "255")

# Después (con validación de seguridad):
self.context.safe_shell(self.plugin_id, "settings", "put", "system", "brightness", "255")
```

## Monitoreo continuo

```bash
# Script de monitoreo simple
while true; do
  STATUS=$(curl -s http://localhost:5000/api/plugins/plugin_guardian/status)
  ALERTS=$(echo $STATUS | jq '.unacknowledged_alerts')
  BLOCKED=$(echo $STATUS | jq '.blocked_commands')
  
  if [ "$ALERTS" -gt 0 ] || [ "$BLOCKED" -gt 0 ]; then
    echo "[$(date)] Alertas: $ALERTS, Bloqueados: $BLOCKED"
  fi
  
  sleep 60
done
```

## Actualización

```bash
# Backup de logs existentes
cp -r data/plugin_guardian/logs/ data/plugin_guardian/logs_backup_$(date +%Y%m%d)/

# Redesplegar desde el repositorio (reemplaza runtime, conserva estado durable)
sh /sdcard/xio_termux/run_server.sh
```

## Soporte

Para problemas o preguntas:
1. Ver logs: `tail -f data/plugin_guardian/logs/audit_$(date +%Y-%m-%d).jsonl | jq`
2. Ver comandos bloqueados: `curl http://localhost:5000/api/plugins/plugin_guardian/blocked-commands | jq`
3. Ver alertas: `curl http://localhost:5000/api/plugins/plugin_guardian/alerts | jq`

---

**Fuente canónica**: `xio/new-plugins/plugin_guardian/` + los ganchos en
`xio/new/plugins/base.py`. API completa en el README del plugin.
