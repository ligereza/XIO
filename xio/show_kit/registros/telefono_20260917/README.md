# Registros rescatados del Xiaomi — 2026-09-17

Bajados por `adb pull` desde `/sdcard/xio_termux/foh_logs/` el 2026-09-17, con
el teléfono conectado por USB. Son lectura: no se tocó nada en el aparato para
obtenerlos.

Existían **sólo en el teléfono**. Se preservan acá por lo mismo que ya se
preservaron los del show DREF: un log de show no se puede volver a producir.

| archivo | registros | qué trae |
|---|---|---|
| `foh_20260723.jsonl` | 219 | la víspera del show DREF. **Tiene `senal_on`/`senal_off` de verdad** (5 y 5), que el log del 24 no tiene: ese show se operó por timecode y los tres canales quedaron en cero. |
| `foh_20260725_completo.jsonl` | 316 | la cola del show DREF. La copia que ya estaba en `show_dref_20260724/foh_20260725.jsonl` tiene 148 líneas: está cortada. |
| `foh_20260911.jsonl` | 843 | primera sesión con el **selector de evento en uso**: 478 registros llevan `fohEventKey`. Trae además `app_signal`, que es la APK nativa ingestando al host. |
| `foh_20260912.jsonl` | 275 | el teléfono encendido con el contexto puesto y nada más: 274 heartbeats y una lectura de batería. |

## Una inconsistencia que conviene resolver

El `fohEventKey` que el teléfono tiene seleccionado es
`vj_show:drefquila-chocolate-curico-2026-07-24`, y el catálogo actual
(`xio/new-plugins/foh_monitor/foh_vj_context.json`) usa claves del espacio
`producer_event:...`. O sea que el evento que el teléfono viene marcando en sus
registros **no existe en el catálogo que el plugin valida hoy**: `/resumen`
respondería 409 para esos registros. No se corrigió acá — decidir qué espacio
de claves manda es del operador.
