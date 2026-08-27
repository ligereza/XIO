# DÍA DEL SHOW — kit FOH (cero código, todo doble click)

Señales de HOY: **TC** (LTC por M-Audio → Chataigne → OSC) + **VISUAL** (Resolume OSC)
+ setlist + registro. Las luces son de la grandMA3 del venue con red propia: **NO se toca**.
El tile **LUCES quedará N/D (gris) toda la noche y eso es lo esperado, no una falla**
(solo cambia si el técnico acepta el apéndice del final).

IP del teléfono en modo hotspot: **192.168.127.125** (verifícala en el paso 3;
si difiere, usa la real en todos lados).

---

## ⚡ ARRANCAR EL SERVER DEL TELÉFONO (lo primero, y lo que siempre se busca)

Abrir **Termux** en el Xiaomi y escribir:

```sh
sh /sdcard/xio_termux/run_server.sh
```

Comprobar que quedó arriba (desde la laptop, con la IP real del teléfono):

```
http://<IP_TELEFONO>:5000/api/plugins/foh_monitor/panel
```

**El server NO arranca solo después de un reboot.** Es un hueco conocido
(ver `xio/HOTSPOT_SHOW_RUNBOOK.md`): si el teléfono se apaga —por batería a 0,
por ejemplo— al volver hay que lanzarlo **a mano** con ese comando.
Pasó de verdad el 2026-07-24: el teléfono se quedó sin batería a las 14:30,
rebooteó, y hubo que arrancarlo a mano antes del show.

**La IP cambia sola.** En un venue con DHCP el teléfono agarra IP nueva. Si el
panel no responde, buscar la IP real antes que nada: en el teléfono
`Ajustes > WiFi > (red) > IP`, o escanear desde la laptop. Después hay que
ponerla en Chataigne (`Modules > OSC > OSC Output > remoteHost`), puerto 7000.
Pasó el 2026-07-24: `10.195.40.198` → `10.134.166.149`.

---

## LOS DOS SISTEMAS (separación total — leer primero)

Son **dos sistemas independientes**. Ninguno depende del otro; si uno muere,
el otro sigue como si nada.

### XIO (teléfono) — PASIVO EN ESTE SHOW
- **En este kit solo escucha y registra. No manda NADA al rig.**
- Listeners Art-Net/sACN/OSC + tile TC + setlist + JSONL + panel en pantalla.
- **Si el teléfono muere, el show sigue completo**: pierdes el monitoreo y el
  registro, nada más. Ningún clip, luz ni timecode pasa por él.

Esto describe DREF CHOCOLATE, no todo XIO. El plugin `showcontrol` puede ser
activo en otro despliegue; revisa `xio/CAPACIDADES.md` y no lo habilites sin
token, prueba de ruta y autorizacion del show.

### LAPTOP — ACTIVO (el show en sí)
- **Chataigne**: recibe el LTC por la M-Audio y lo convierte a OSC `/timecode`.
- **cue_engine**: escucha ese `/timecode` en la propia laptop (:7001) y dispara
  los clips de Resolume (localhost:7000). Todo local a la laptop.
- Si la laptop muere, se pierden los visuales automáticos (se dispara a mano
  en Arena); el teléfono seguirá registrando lo que sí llegue.

### Único punto de contacto
Chataigne emite el MISMO mensaje `/timecode` a **dos destinos**: la propia
laptop (127.0.0.1:7001, pal cue_engine) y el teléfono (192.168.127.125:7000,
pal tile TC y el registro). Es un envío en paralelo, no una cadena: el
teléfono no reenvía nada al engine ni el engine le pide nada al teléfono.
**Cero dependencia mutua.**

## Soundcheck (pasos en orden)

1. **Teléfono**: enciende el hotspot del Xiaomi. Conéctalo a corriente/powerbank.
   Si el server no estuviera corriendo: abrir Termux y `sh /sdcard/xio_termux/run_server.sh`.
2. **Laptop**: conéctala al WiFi del hotspot.
3. **Chequeo GO/NO-GO**: doble click a `check_show.bat` (esta carpeta).
   Todo verde (los AVISOS amarillos de audio/setlist no bloquean) → seguir.
   Anota la IP que imprime: es la que se dicta a todo el mundo.
4. **Chataigne**: abrir `festival_sentir.noisette` (esta carpeta). Ya trae el
   módulo OSC apuntando a 192.168.127.125:7000 y el módulo Sound Card con LTC
   habilitado. Quedan **2 pasos manuales** (el generador validado del repo no
   cubre mappings, no se improvisa):
   - Módulo **Sound Card** → Inspector → seleccionar la **M-Audio** como
     dispositivo de entrada (el LTC entra por ahí).
   - Menú del panel State Machine o botón derecho → **Add Mapping**:
     - Input: `Sound Card > LTC > Time`
     - Output: módulo `OSC > Custom Message`, address **`/timecode`**, 1 argumento
       con el valor del input (string o float, el monitor acepta ambos).
   Dale play al LTC de la sesión: el tile TC del panel debe correr en verde.
5. **Resolume** (laptop de visuales): Preferences → OSC → **OSC Output**:
   IP `192.168.127.125`, puerto `7000`. Con eso el tile VISUAL se enciende
   cuando Resolume manda actividad.
6. **Setlist**: editar `setlist_festival_sentir.txt` (un tema por línea) y
   doble click a `cargar_setlist.bat`.
7. **Panel en el teléfono**: abrir en el navegador del Xiaomi
   `http://127.0.0.1:5000/api/plugins/foh_monitor/panel`, pantalla completa.
   Subir brillo y poner tiempo de pantalla en "10 min" o más
   (Ajustes → Pantalla); tocar una vez el panel arma el wake-lock del navegador.
   Dejarlo fijo en FOH.

## Líneas exactas para dictar

- Al de visuales (Resolume): «OSC Output a **192.168.127.125 puerto 7000**».
- El TC ya sale de nuestra Chataigne, nadie más configura nada.
- (Luces: solo si acepta el técnico — ver apéndice.)

## Si algo falla (playbook)

| Síntoma | Acción |
|---|---|
| Panel congelado / no refresca | Refrescar la página del navegador. |
| Tile TC rojo CONGELADO | El LTC se detuvo o Chataigne dejó de mapear: revisar play de la sesión y el mapping. |
| Tile TC rojo CAÍDO | No llegan paquetes: ¿laptop sigue en el WiFi del hotspot? ¿Chataigne abierto? |
| Nada llega de un equipo | Verificar que ESE equipo está EN la red del hotspot (no en el WiFi del venue) y que apunta a la IP del paso 3. |
| Server caído (check_show en rojo) | En el teléfono: abrir Termux → `sh /sdcard/xio_termux/run_server.sh` (vuelve en ~15 s; el supervisor también lo revive solo en ~90 s). |
| Hotspot caído | `hotspot_watch` lo revive solo en 30–90 s. Si no: Ajustes → Hotspot, un toque al toggle. |
| Post-show | Bajar el registro: `curl -O http://192.168.127.125:5000/api/plugins/foh_monitor/log` (cada evento lleva el timecode vigente para correlacionar con la sesión). |

## Batería para el show

- Cargar el teléfono **al 100 % antes de salir**.
- En FOH: enchufado a powerbank toda la noche. El charge-limiter **no corta**
  con powerbank común (viene apagado por defecto); si la noche es larga y
  quieres cuidar la batería, **desenchufa el powerbank al llegar a ~90 %** y
  vuelve a enchufar si baja de ~40 %.
- El panel muestra nivel y temperatura; ≥45 °C sale en rojo.

---

## APÉNDICE — LUCES: SI EL TÉCNICO ACEPTA (2 minutos)

Vía pre-armada por si el técnico de la grandMA3 ofrece una copia de Art-Net,
aunque sea a último minuto. Cable de la consola al puerto ethernet de la
laptop; la laptop reenvía por WiFi al teléfono (`relay_luces.bat`).

**Mensaje corto para mandarle al técnico si acepta:**

> Agrégame una salida Art-Net en una interfaz libre de la MA3, destino unicast
> `2.0.0.2` (mi laptop por cable), universo el que ustedes usen. Yo pongo
> `2.0.0.1/255.0.0.0` de tu lado si quieres, o dime qué IP le pongo a mi
> extremo. Es solo escucha, no mando nada.

**En la grandMA3 (dictar):**
1. Menú → **In & Out / Network Protocols → Art-Net → Add** (salida/output).
2. Interfaz: la libre (no la de su rig). Destino: **IP de la laptop en ese
   cable** (sugerido `2.0.0.2`). Universo: el que ellos usen.
3. Convención clásica Art-Net para el cable directo: consola `2.0.0.1`,
   laptop `2.0.0.2`, máscara `255.0.0.0` en ambos.

**En la laptop (3 clicks + doble click):**
1. Configuración → Red e Internet → Ethernet → el adaptador del cable →
   Editar asignación de IP → **Manual, IPv4**: IP `2.0.0.2`,
   máscara `255.0.0.0` (longitud 8), puerta de enlace vacía → Guardar.
2. Doble click a **`relay_luces.bat`**: muestra las IPs locales y un contador
   de paquetes en vivo (si el contador sube, la consola está llegando).
3. Verificar en el panel del teléfono: **tile LUCES pasa de N/D a verde**.

Si en vez de Art-Net ofrecen sACN, es el mismo relay (reenvía ambos puertos);
en la MA3 sería Network Protocols → sACN → output unicast a la laptop.

Nota técnica: el relay reenvía los paquetes tal cual por unicast a
`192.168.127.125:6454/5568`; el monitor solo escucha, jamás emite hacia el rig.

---

## SHOW "DREF CHOCOLATE" (Curicó) — visuales automáticos por timecode

Cadena: LTC (M-Audio) → Chataigne → OSC `/timecode` a DOS destinos → el
**cue engine** dispara los clips de Resolume solos, tema por tema.

**Puertos definidos (sin colisión — quién escucha dónde):**

| Puerto | Quién escucha | Quién le manda |
|---|---|---|
| 192.168.127.125:**7000** | xio / foh_monitor (teléfono) | Chataigne (`/timecode`) y Resolume (OSC output, actividad VISUAL) |
| 127.0.0.1:**7001** | cue_engine (esta laptop) | Chataigne (`/timecode`, segundo target) |
| 127.0.0.1:**7000** | Resolume Arena (OSC **Input**, default) | cue_engine (connects de clips) |

No hay choque: el 7000 del teléfono y el 7000 de Resolume son máquinas
distintas; en la laptop el engine escucha en 7001.

**Pasos (soundcheck):**
1. Abrir `dref_chocolate.noisette` en Chataigne. Manual (3 pasos, igual que
   el flujo general + un target extra):
   - Sound Card → Inspector → input = **M-Audio** (LTC entra por ahí).
   - Add Mapping: `Sound Card > LTC > Time` → `OSC > Custom Message` address
     **`/timecode`** (1 argumento con el valor).
   - En el módulo OSC → **OSC Outputs → añadir un segundo output**:
     `127.0.0.1` puerto `7001` (mismo mensaje llega al engine y al teléfono).
2. Resolume Arena: Preferences → OSC → **OSC Input ON, puerto 7000** (default)
   y OSC Output → `192.168.127.125:7000` (pal tile VISUAL del teléfono).
3. Revisar el mapeo: abrir `cue_map_dref.json` — la tabla la genera
   `py map_dref.py` (re-correr si cambió la composición). Hoy: 21 cues,
   19 con clip; **"Último Día" y "Pegó fuerte" NO tienen clip en la
   composición** (quedan null: el engine los anuncia y no dispara nada;
   si aparecen los .mov, agregar el clip en Arena, re-correr `map_dref.py`
   o poner layer/clip a mano).
   OJO ambiguos (2 candidatos, elegido el primero): YOSEKE (layer 4/clip 7,
   alternativa layer 5/clip 9) y DIABLO SANTO (layer 3/clip 9, alternativa
   layer 6/clip 7) — confirmar en soundcheck cuál es el bueno.
4. Doble click a **`cue_engine.bat`**. Muestra TC en vivo + tema vigente y
   loguea cada disparo en `cue_engine_log_YYYYMMDD.jsonl`.
   Prueba sin miedo: `cue_engine.bat --dry-run` imprime en vez de mandar.
5. Probar con la sesión: play al LTC → el clip del tema debe conectarse solo
   al cruzar cada media hora de TC (y el tile TC del teléfono corre en verde).

**Comportamiento del engine (robustez):**
- Un cue NO se re-dispara mientras siga vigente (idempotente).
- Salto/seek del TC (adelante o atrás): dispara UNA vez el cue vigente del
  nuevo punto y sigue (arrancar el engine a mitad de show también sincroniza).
- Dispara por **clip** (`/composition/layers/L/clips/C/connect`), no por
  columna: en esta composición los temas están apilados por layers en pocas
  columnas — una columna lanzaría 5 temas a la vez.
- Ctrl+C sale limpio; el log queda pa correlacionar post-show con el JSONL
  del teléfono (ambos llevan TC).
