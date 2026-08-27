> Indice operativo: ver xio/RUNBOOK.md

# xio -- Plan post-descubrimiento: palancas de SERVICIO (sin root)

Fecha: 2026-07-13. Rama: claude/vola-cultura-portfolio-20260712.

This is a service and battery plan, not proof that every XIO plugin is deployed
on the Xiaomi. Runtime claims must be checked against `xio/CAPACIDADES.md`.
The passive FOH monitor and active `showcontrol` surface are separate
capabilities with separate security requirements.

## El descubrimiento (y por que cambia el mapa)

`dumpsys usb set-port-roles port0 <sink|source> <device|host>` controla el FLUJO
REAL de energia como shell-uid (via Shizuku/rish), SIN root:
- `sink device` -> el telefono RECIBE carga (charging).
- `source host`  -> el telefono es OTG source -> NO carga.

Probado bidireccional a traves del server (backend rish), no solo por wifi-adb:
OFF -> ufp/sink -> dfp/source, charging true->false; ON -> restaura. Ventana ~10s.

Esto habilita el charge-limiter no-root: el OBJETIVO ORIGINAL de xio (salud de
bateria), que estaba documentado como "imposible sin root".

### Meta-leccion (la lente nueva)

"Imposible sin root" casi siempre significa: "la ruta `/sys/class/power_supply/*`
esta cerrada por SELinux para shell-uid". Pero la MISMA capability suele estar
expuesta por un SERVICIO privilegiado del sistema (`dumpsys`, `cmd`, `settings`,
`service call`) que SI es alcanzable como shell-uid via Shizuku.

Regla: **atacar por el servicio, no por el sysfs.** Antes de declarar algo
imposible, enumerar que servicio maneja esa capa y si expone un setter.

## Hecho en esta sesion

- Plugin `charge_control` (25 plugins ahora): cap 80 + floor 77 (histeresis),
  `hard_floor` 20 (NUNCA morir: por debajo fuerza carga e ignora todo), charge
  on/off manual, powerbank (OTG source), dock (sink+host para hub PD).
- Seguridad en dos capas: guard del server (HTTP 423 sin confirm) + rechazo en el
  plugin si nivel <= hard_floor. Limiter default OFF.
- Probado en device end-to-end. Commit + push.

## Reabrir los "imposibles" con la lente de servicios

Prioridad | capacidad | ruta /sys bloqueada | palanca de servicio candidata | estado
--- | --- | --- | --- | ---
1 | Charge-stop LIMPIO (sin drenar por OTG) | charge_disable node | `set-port-roles source device` (power source, data device -> quiza corta sin OTG activo); `dumpsys battery set` combos; enumerar transacts de UsbManager via `service call` | por probar
2 | Control de tasa / PD (slow-charge, menos calor) | current_max node | perfil PD / `cmd usb`; set-port-roles a modo que negocie menos W | por investigar
3 | Persistencia tras REBOOT (el ultimo limite real) | -- | `settings put global adb_wifi_enabled 1`; Shizuku por wireless-debugging al boot; Termux:Boot addon; MIUI autostart | por armar
4 | Governor termico/CPU real | cpufreq/thermal nodes | `cmd thermalservice`; `device_config`; `cmd power`; `service call` al thermalservice | por mapear
5 | Ruta fisica: hub con PD passthrough | -- | endpoint `/dock` (sink+host) ya existe; hub 60W PD-in + Gigabit Ethernet | rig maduro

### El unico limite que sigue en pie: el REBOOT

Todo lo demas es recuperable sin PC (watchdogs + wifi-adb). Lo que aun NO sobrevive
un reinicio del telefono es el re-arme de Shizuku/wifi-adb (necesita el primer
`adb tcpip` o wireless-debugging). Prioridad 3 arriba es el camino para cerrarlo:
si `adb_wifi_enabled` + Shizuku-boot + Termux:Boot se encadenan, el server vuelve
solo tras un reboot. Ese seria el hito "operable sin PC" completo.

## Siguiente paso concreto

Enumerar los transacts de UsbManager / BatteryManager / thermalservice
(`service list`, `dumpsys <svc>`, `cmd <svc> help`) para mapear que MAS se puede
tocar por servicio. Es trabajo mecanico de volumen -> lo pueden hacer los agentes
gratis y reportar la tabla; Claude solo decide que se convierte en plugin.

## Marco artistico (concepto, sin codigo -- por decision del usuario)

"El juego de no caer en el 0": la bateria como recurso vital del sistema; el cero
mata todo lo construido encima. El `hard_floor` es la respuesta en codigo; el hub
con PD passthrough es la respuesta fisica. Queda como concepto, no se desarrolla.
