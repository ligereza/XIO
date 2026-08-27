# Registro crudo -- show DREF CHOCOLATE, 2026-07-24

Respaldo de los logs reales del show. **Fuente de verdad** del analisis en
`xio/show_kit/ANOTACIONES_SHOW_20260724.md`. No editar: son evidencia.

| Archivo | Origen | Contenido |
|---|---|---|
| `foh_20260724.jsonl` | xio, plugin `foh_monitor` | 2020 eventos del 24 completo (incluye el show 20:12-21:27) |
| `foh_20260725.jsonl` | xio, plugin `foh_monitor` | 148 eventos post-medianoche (cola del show) |
| `soundcheck_20260724.jsonl` | colector de sesion (PC) | 216 muestras del soundcheck, 17:32-18:34, cada 15 s |

## Como se obtuvieron

```bash
# Los del telefono (xio), via el endpoint del propio plugin:
curl "http://<IP_XIO>:5000/api/plugins/foh_monitor/log?date=20260724" -o foh_20260724.jsonl
curl "http://<IP_XIO>:5000/api/plugins/foh_monitor/logs"   # lista los dias disponibles
```

Ojo: el parametro es `?date=YYYYMMDD`. Sin el, el endpoint devuelve **siempre el
log del dia actual** (se puede creer que se bajo otro dia y bajar un duplicado).

## Esquema de los `foh_*.jsonl`

Un evento JSON por linea: `{ts, tipo, detalle, tc}`.

| `tipo` | Significado |
|---|---|
| `heartbeat` | Latido cada ~60 s: estado de canales, bateria, estado del TC |
| `setlist_next` | Cambio de tema. `accion: auto-tc` = disparado por cue de timecode |
| `tc_freeze` | El TC se congela (`estado: congelado`) o se pierde (`estado: caido`); trae el valor de LTC |
| `tc_resume` | El TC vuelve; trae el valor de LTC al reanudar |
| `bateria` | Cambio de nivel/carga/temperatura |

El campo `detalle.valor` de `tc_freeze`/`tc_resume` viene en **segundos de LTC**.
De ahi salen las duraciones exactas por tema (ver ANOTACIONES, "Duraciones EXACTAS").

## Ventana util

- Soundcheck: 17:32 - 18:34
- Show: **20:12:32 (intro) - 21:27:30**
- Apagon del telefono por bateria: **14:30:31 - 16:16:00** (105 min sin log)
