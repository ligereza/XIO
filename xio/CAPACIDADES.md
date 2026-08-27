# XIO - matriz de capacidades

Esta matriz separa lo que existe en el repositorio de lo que esta verificado en
el Xiaomi. La palabra `operativo` no se usa sin una prueba en el dispositivo.

| Superficie | Lee estado | Recibe senales | Envia senales | Ejecuta control | Estado en repo | Estado en Xiaomi |
|---|---:|---:|---:|---:|---|---|
| `mak_xio_puente/monitor.py` | si | no | no | no | implementado | no verificado |
| `foh_monitor` | si | si, UDP | no | no | implementado | no verificado |
| `showcontrol` | si | si, OSC opt-in | si, OSC/Art-Net/sACN | si, con token/permisos | implementado y testeado | no verificado |
| `show_kit/cue_engine.py` | si | si, timecode | si, OSC desde laptop | dispara cues en Resolume | implementado y testeado | no aplica: corre en laptop |
| panel web del MAK | si | no | no | no | implementado | no aplica |

## Lectura correcta

- `read-only` describe el monitor, el panel o el puente de observacion; no
  describe todo el servidor XIO.
- `showcontrol` es un nodo activo de red y puede enviar comandos al rig. Eso
  no significa que este instalado, habilitado o autorizado en el telefono.
- El `show_kit` documenta un show concreto: en DREF CHOCOLATE el telefono se
  uso pasivamente y la laptop hizo el control activo.
- Cualquier capacidad marcada `no verificado` requiere una prueba de estado,
  plugin cargado, token y ruta segura antes de presentarse como disponible.
