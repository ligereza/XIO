# Anotaciones show DREF CHOCOLATE -- 2026-07-24 (en vivo)

Registro pasivo. NO altera el setlist corriendo (xio 10.134.166.149) ni Chataigne.
Documenta cambios de ultimo momento para reconciliar despues del show.

## Tema agregado en vivo: "Random Friends" (con invitado)

- **Posicion:** entre `A Fuego` (idx 15) y `Misionar` (idx 16) del setlist DREF.
- **Anclaje por timecode:**
  - A Fuego  -> cue `07:30:00:00`
  - **Random Friends (invitado) -> ocurre aqui, despues de A Fuego, antes de la cue 08:00**
  - Misionar -> cue `08:00:00:00`
- **TC vivo al momento de anotarlo:** `07:33:56:29` (val 27236.97 s)
- **Nota:** no se inyecto al engine en vivo (correria indices y romperia panel/cues).
  Reconciliar post-show en `setlist_festival_sentir.txt` + `setlist_durations_dref.json`
  (nueva linea entre A Fuego y Misionar; asignar visual/duracion o null si sin visual).

_Autor: Cauce (fallback pasivo). Config del show intacta._

## Observacion: transicion intro -> "Ultimo Dia" no avanza por duracion

- **Sintoma (usuario):** no pasa a "Ultimo Dia"; el calculo entre la duracion del
  clip de intro (~1 min) y la llegada a Ultimo Dia no cuadra.
- **Lectura:** el avance del setlist es por CUE de timecode, no por duracion de clip.
  - intro show -> cue `00:00:00:00` (clip real ~`00:01:11`, 71.2 s)
  - Ultimo Dia -> cue `01:00:00:00`
  - Entre el fin del clip (~00:01:11) y la cue de Ultimo Dia (01:00:00:00) hay un
    hueco enorme: el panel se queda en intro hasta que el TC llega a 1:00:00:00.
- **TC vivo al anotar:** `00:02:24:00` (aun en intro, next = Ultimo Dia).
- **Reconciliar post-show:** revisar el anclaje de cues del setlist -- si la intencion
  es avanzar por fin-de-clip, la cue de Ultimo Dia deberia caer cerca de ~00:01:11,
  no en 01:00:00:00. NO se toca en vivo.

---

# POST-SHOW: datos medidos (log real de foh_monitor)

Fuente: `xio/show_kit/_logs/xio_show_2026072{4,5}.jsonl`, descargados de xio
(`/api/plugins/foh_monitor/log?date=YYYYMMDD`). 2168 eventos.
Metodo: tiempo entre disparos `setlist_next` (auto-tc), **descontando** las
ventanas con TC muerto. Confirmado con el usuario tras el show.

**Show: 20:12 (intro) -> 21:27:30. Total ~1h15.**

## Clave de lectura: TC muerto = intencional, no falla

Los tramos sin SMPTE eran contenido, no caidas:
- **CCTV / visual quieta** -> Random Friends.
- **Texto y conversacion de DREF con el publico** -> ventanas cortas entre temas.

## Hallazgo 1: el intro era el clip largo (resuelve pendiente)

El TC arranco 20:12:32 y murio en **exactamente 331.0 s = 5:31**.
- Se uso **"intro - intro ultimo dia" (5:31)**, NO "INTRO" (1:11).
- Corrige el `pendiente_confirmar` de `setlist_durations_dref.json`.
- **Explica el gap anotado en preshow:** "Ultimo Dia" venia DENTRO del clip de
  intro, por eso su cue (n=2, `01:00:00:00`) nunca disparo -- el TC del clip
  solo llega a 5:31.

## Hallazgo 2: Random Friends (invitado) medido

- Ventana sin TC `21:09:07 -> 21:13:23` = **4:16** (visual CCTV).
- **A Fuego real = 4:04** (los 8:19 aparentes eran A Fuego + Random Friends).

## Hallazgo 3: Pinky + FINAL FALSO son una unidad

La visual "final falso" estaba separada del clip de Pinky.
- Pinky visual `21:02:06 -> 21:04:41` = **2:35** (cue `07:02:35:00` disparo exacta).
- FINAL FALSO `21:04:42 -> 21:05:03` = **0:21**.
- **Tema Pinky completo = 2:57.** El clip de Pinky (3:03) queda con **28 s sin usar**
  porque el final falso entra antes. Las duraciones deben calzar entre las dos entradas.

## Hallazgo 4: Enrolar mal calculado en el setlist

- Clip de video: **1:28**. Cancion real: **5:12** (exacto por LTC: cue 08:30:00.033 ->
  congela 08:35:11.699 = 311.7 s) -> **faltan 3:44 de visual**.
- Funkysolo: clip 5:03, real **5:46** (+43 s quieto).
- **Yoseke NO se toco** (confirmado usuario). Su cue n=19 nunca disparo: correcto,
  no es bug. El hueco Enrolar->Funkysolo es solo Enrolar mal medido.

## Precision del sistema

Los 12 temas que corrieron con SMPTE dieron **+-6 s** contra lo esperado.
La medicion fue fiable; todos los desvios grandes se explican por tramos sin TC
(CCTV, texto, conversacion) o por duraciones mal cargadas, no por deriva.

## Duraciones reales medidas (para reconciliar el setlist)

| n | tema | clip cargado | REAL medido | nota |
|---|---|---|---|---|
| 1 | intro + Ultimo Dia | 1:11 (INTRO) | **5:31** | usar clip largo; Ultimo Dia va dentro |
| 3 | 2000s | 4:34 | 4:40 | ok |
| 4 | Un call | 3:11 | 3:08 | ok |
| 5 | Lo deberias pensar | 3:57 | 4:12 | ok |
| 6 | La receta | 4:23 | 4:24 | ok |
| 7 | Bossa Lova | 3:16 | 3:22 | ok |
| 8 | 2+1 | 2:25 | 2:30 | ok |
| 9 | Pego fuerte | sin visual | 3:02 | dato nuevo |
| 10 | Las flores que te gustan | 4:21 | 4:27 | ok |
| 11 | Despertador | 2:51 | 2:56 | ok |
| 12 | Botero | 3:54 | 3:58 | ok |
| 13 | Llama a tu amiga | 3:03 | 2:09 + 1:03 conversacion | clip ok |
| 14 | Pinky | 3:03 | 2:35 | +0:21 FINAL FALSO = 2:57 |
| 15 | FINAL FALSO | 0:16 | 0:21 | separada del clip de Pinky |
| 16 | A Fuego | 3:54 | 4:04 | ok |
| -- | **Random Friends (invitado)** | -- | **4:16** | CCTV, sin SMPTE |
| 17 | Misionar | 2:00 | 2:12 | ok |
| 18 | Enrolar | 1:28 | **5:12** | clip corto: faltan 3:44 |
| 19 | Yoseke | 3:14 | -- | NO se toco |
| 20 | Funkysolo | 5:03 | 5:46 | clip corto |

_Medido por Cauce sobre el log real. Nada se toco en vivo._

## Hallazgo 5: cierre con QR manual, no DIABLO SANTO

- La visual **"DIABLO SANTO FINAL SHOW" (n=21) fue reemplazada por un QR**,
  soltado **a mano** despues de Funkysolo. Confirmado por el usuario.
- Coherente con el log: la cue n=21 **nunca disparo** (el ultimo `setlist_next`
  del show es n=20 Funkysolo a las 21:21:35). No es bug: no se uso.
- Ventana del QR segun log: Funkysolo 21:21:35 + clip 5:03 -> fin ~21:26:38;
  reset del panel a intro 21:27:30. **QR visible ~52 s** en esa cola (mas lo que
  haya quedado tras el reset). TC muere definitivo 21:28:04.
- El contenido del QR no se registra aqui (material del cliente).
- **Para el setlist:** el cierre real del show fue Funkysolo -> QR manual.
  DIABLO SANTO queda sin usar; decidir si se retira del setlist o se deja armado.

## Hallazgo 6: Funkysolo corrio casi sin SMPTE (cierre a ciegas)

- TC arranca `21:21:36` en cue `09:30:00.500` y **muere a los 7 s** (`09:30:07`).
- El tema siguio **~5:46 sin timecode**, y encima el cierre fue el QR manual.
- Es decir: **todo el final del show (Funkysolo + QR) corrio a ciegas**, sin TC.
- A revisar antes del proximo show: por que se corto el LTC de Funkysolo a los 7 s
  (pista sin LTC grabado / se corto el envio / clip sin la pista de tiempo).

## Duraciones EXACTAS por LTC (tramos con TC limpio)

Metodo mas preciso que el de reloj: valor del propio LTC al entrar la cue y al
congelarse. Solo tramos con una sola cue adentro.

| tema | cue TC | TC final | REAL | clip | nota |
|---|---|---|---|---|---|
| intro + Ultimo Dia | 00:00:00 | 00:05:31 | **5:31** | 1:11 | usar el clip largo |
| 2000s | 01:30:00 | 01:34:34 | **4:34** | 4:34 | clavado |
| 2+1 | 04:00:00 | 04:02:25 | **2:25** | 2:25 | clavado |
| Pego fuerte | 04:30:00 | 04:32:57 | **2:57** | sin visual | dato nuevo |
| Las flores que te gustan | 05:00:00 | 05:04:21 | **4:20** | 4:21 | clavado |
| Despertador | 05:30:00 | 05:32:50 | **2:50** | 2:51 | clavado |
| Botero | 06:00:00 | 06:03:53 | **3:53** | 3:54 | clavado |
| Llama a tu amiga | 06:30:00 | 06:33:02 | **3:03** | 3:03 | clavado, el clip corrio entero |
| Misionar | 08:00:00 | 08:02:07 | **2:06** | 2:00 | ok |
| Enrolar | 08:30:00 | 08:35:11 | **5:12** | 1:28 | faltan 3:44 de visual |
| Funkysolo | 09:30:00 | 09:30:07 | **0:07 de TC** | 5:03 | LTC caido, ver Hallazgo 6 |

## Trabajo pendiente para el proximo show

1. **Enrolar**: extender la visual de 1:28 a **5:12**.
2. **intro**: dejar fijo el clip de 5:31 ("intro - intro ultimo dia") y quitar la
   cue n=2 de Ultimo Dia, o recortar el clip y darle cue propia.
3. **Funkysolo**: arreglar el LTC que muere a los 7 s.
4. **Random Friends**: si se repite, darle entrada propia (4:16, CCTV).
5. **Pinky**: dejar documentado que FINAL FALSO entra a 2:35 y son una unidad (2:57).
6. **DIABLO SANTO**: decidir si se retira (se cerro con QR manual).
7. **Yoseke**: quedo sin tocar; su cue n=19 sigue armada.

---

# Chequeo de infraestructura: bateria y red

## Red / estabilidad del server: IMPECABLE durante el show

- Heartbeats cada **60 s exactos** durante todo el show (79 latidos, gap maximo
  63 s). **Cero caidas del server, cero perdidas de red.**
- El cambio de IP por DHCP en el venue (`10.195.40.198` -> `10.134.166.149`) fue
  el unico incidente de red, y fue **antes** del show (resuelto en soundcheck).
- Los canales Art-Net / sACN / OSC quedaron en 0 paquetes: esperado, este show
  se opero por timecode, no por señal de consola.

## BATERIA: riesgo critico, hay que resolverlo antes del proximo show

Cronologia real del 24:

| Hora | Nivel | Estado |
|---|---|---|
| 00:01 | 89% | cargando |
| 05:42 | 68% | cargando |
| 09:50 | 80% | cargando |
| **10:04** | **84%** | **deja de cargar** |
| 11:02 | 59% | descargando (temp 40 C) |
| 13:52 | 4% | descargando |
| **14:30:31** | -- | **el telefono se apaga: 105 min sin log** |
| **16:16:00** | **0%** | vuelve encendido, y **se queda en 0% para siempre** |
| 20:12-21:27 | **0%** | **todo el show corrio en 0%** |
| ahora | 0% | sigue en 0%, `discharging`, pero el equipo responde |

### Lo que esto significa

1. **El telefono se quedo sin bateria y se apago 6 horas antes del show.**
   Volvio a las 16:16 porque lo enchufaron.
2. **Todo el show corrio con la bateria en 0%, alimentado solo por el cable.**
   Un tiron del cable = se cae el TC y el panel FOH en pleno show. Se zafo.
3. **Despues del reboot la carga no se recupero.** `charge_control` reporta
   `level 0`, `discharging`, y **no puede leer el puerto USB**
   (`current_mode`, `power_role`, `sink_power` = todos `null`).
   Ultima accion registrada: `charge_on` con nota `hard_floor 20%: carga forzada`
   -- el sistema intento forzar la carga y aun asi sigue en 0.
4. `battery_care` esta directamente **sin monitoreo** (`monitoring_active: false`,
   `total_history_points: 0`, nivel `N/A`).

### Hipotesis a verificar (NO confirmadas, requieren revisar el telefono)

- **La mas probable:** tras el reboot de las 16:16, **Shizuku/rish quedo sin
  re-autorizar**. Sin ese permiso `charge_control` no puede leer ni cambiar el
  port-role USB, que es justo el mecanismo con el que este telefono controla la
  carga (ver memoria del proyecto: control de carga no-root via USB port-role).
  Encaja con que los tres campos `usb` sean `null`.
- Alternativas: cable o cargador fallando; puerto USB dañado; el limitador
  (`cap 80`) quedo en un estado raro -- aunque ahora figura `limiter_enabled: false`.

**No se toco nada del telefono para diagnosticar esto** (solo lecturas HTTP).

### Acciones recomendadas antes del proximo show

1. Revisar fisicamente: cable, cargador y que el telefono este **cargando de verdad**
   (no solo alimentado).
2. Re-autorizar **Shizuku/rish** despues de cualquier reboot -- y agregarlo al
   checklist de dia de show.
3. Que `check_show.py` **bloquee el GO** si la bateria lee 0% o si el puerto USB
   no se puede leer. Hoy solo avisa.
4. Reactivar `battery_care` (`monitoring_active: false`).
5. Regla de show: el telefono **enchufado y con carga real >60%** antes de empezar,
   con el cable asegurado (cinta) para que no se lo lleven por delante.

---

# Operacion: un gap y un logro

## GAP: el server no se desplego solo, y hubo que buscar el comando

Reportado por el usuario. Dos problemas encadenados con la bateria:

1. **No arranco solo.** El telefono se apago por bateria a las 14:30 y rebooteo
   ~16:16. **El server no vuelve solo tras un reboot**: es el hueco ya documentado
   en `xio/HOTSPOT_SHOW_RUNBOOK.md` ("El unico hueco: reboot sin host") y en
   `xio/PLAN_SERVICIOS_SIN_ROOT.md` ("El unico limite que sigue en pie: el REBOOT").
   O sea: **la bateria agotada disparo exactamente el escenario previsto como peor caso.**
   Cadena completa: bateria 0 -> reboot -> sin Shizuku -> sin autostart -> arranque a mano.

2. **Hubo que buscar el comando.** El comando **si estaba documentado**, pero
   enterrado como nota condicional al final del paso 1 del soundcheck:
   `sh /sdcard/xio_termux/run_server.sh`.

**Arreglado:** se subio al principio de `DIA_DEL_SHOW.md`, en un bloque propio
"ARRANCAR EL SERVER DEL TELEFONO", junto con la URL de verificacion y el aviso
de que la IP cambia sola en un venue con DHCP.

**Pendiente de fondo (no resuelto):** el autostart real tras reboot. Ya hay plan
escrito (Termux:Boot + Shizuku por wireless-debugging + MIUI autostart, ver
`PLAN_SERVICIOS_SIN_ROOT.md` fila 3; y el `AccessibilityService` de
`xio/hotspot_boot_service/`). Mientras no exista, **la defensa primaria es la
energia**: con el telefono en fuente estable no hay reboot y el hueco no aparece.

## LOGRO: la app se vio desde el escenario, en un iPhone ajeno

- Se le dio la clave a un colega **desde el escenario** y **pudo ver la app en Safari**.
- Es la primera vez que el panel FOH se consume **fuera de la laptop y fuera del
  telefono**: otro dispositivo, otro sistema (iOS), otro navegador (Safari), y
  operado por otra persona.
- Lo que valida en concreto:
  - El panel es **multi-cliente de verdad**, no un tablero de un solo espectador.
  - Funciona en **WebKit/Safari**, no solo en Chromium.
  - **Sirve al musico en escena**, no solo al FOH: quien esta tocando puede ver
    el timecode y el tema actual sin depender de nadie.
  - El acceso por clave a la red del telefono es una via practica en vivo.
- **Consecuencia:** el panel deja de ser solo monitoreo de FOH y pasa a ser un
  **monitor de escenario** valido. Vale la pena tratarlo como caso de uso propio
  (que se ve bien en pantalla chica, que sobreviva a que la pantalla se apague,
  y como se reparte el acceso sin dar la clave del hotspot a cualquiera).
