# XIO

Repositorio extraído de `ligereza/vibecodeine` para reunir el sistema XIO en
un solo lugar: runtime Xiaomi/Termux, plugins, control de show, seguridad,
automatización, documentación, ideas y proyectos de instalación.

## Qué contiene

- `xio/new/`: runtime activo del servidor Flask, su dashboard web y el plano
  público RD NODO (`rd_nodo_*`).
- `xio/new-plugins/`: los 33 plugins vivos, entre ellos las dos superficies de
  campo `rd_field` (RD) y `foh_monitor` (FOH/ISKVW), más `_template`.
- `xio/show_kit/`: control de cues, timecode, Art-Net/OSC y materiales de los
  shows DREF CHOCOLATE y Festival Sentir.
- `xio/hotspot_boot_service/`: servicio Android de recuperación/arranque.
- `xio/seguridad/`: notas de instalación y verificación del plugin_guardian.
- `xio/vision/`: demo Android de inferencia offline; propone, nunca decide.
- `xio/actual/`: primera implementación del controlador ADB, conservada como
  referencia histórica.
- `projects/rd-field/` y `projects/foh-monitor/`: las APK clientes de cada
  superficie, con su propio paquete y menú.
- `cultura/`: mapa conceptual XIO, handoff técnico y puente MAK↔XIO.
- `projects/cultura/MAPA_GENERATIVO.md`: contexto del XIO dentro del mapa de
  proyectos e ideas de Cauce.
- `xio/show_reading.py`: la lectura medida de un show a partir de su JSONL, con
  el **reloj declarado por segmento** (`ltc`, `osc_trigger`, `wall`, `tap`).
  Reproduce la tabla de duraciones que se calculó a mano para el show del
  2026-07-24 y, donde el log se contradice, lo dice en vez de elegir.
- `xio/flicker.py`: flicker y bandas leídos de un cuadro de rolling shutter —
  frecuencia de PWM, profundidad de modulación, y de quién son las bandas
  (contenido o muro). Declara su propia resolución y se niega a dar una
  frecuencia que la ventana no puede resolver.
- `xio/foh_knowledge.py`: el ledger de conocimiento FOH/VJ (venues, eventos,
  artistas, obras) en dos capas que no se mezclan — lo declarado por una fuente
  y lo observado por un instrumento — y su publicación al Hub de MAK en el
  esquema `faro-xio-evidence-v1` que el Hub ya renderiza.
- `xio/foh_learning.py`: lo que el corpus de shows puede enseñar, con la
  cantidad de muestras pegada al número: la latencia del toque humano, la
  duración real contra el clip acumulada por obra, y las cues que no dispararon.
- `xio/semantic_lighting.py` y `xio/experimental_rehearsal.py`: la mitad
  generativa, que propone escena y paquete desde un evento canónico de
  audio/timecode. La superficie FOH todavía no las usa.
- `tests/`: 13 suites de pytest y 9 gates `check_xio_*.py` que se corren con el
  intérprete y verifican contratos (staging de campo, runtime del teléfono,
  puente RD, contexto FOH, host dinámico y las dos APK). Dos de esas suites
  —`test_showcontrol_token.py` y `test_wifi_intelligence_plugin.py`— llegaron
  desde VIBECODEINE el 2026-09-17: probaban plugins de este repositorio desde
  un árbol donde el código ya no estaba.

## Arranque rápido

El runtime necesita Python, Flask y `adb` disponible en el equipo o el backend
`rish` disponible en el teléfono. Desde la raíz:

```bash
python3 -m pip install -r xio/new/requirements.txt
python3 xio/new/server.py
```

La resolución por defecto de plugins busca `xio/new-plugins/`. Para despliegue
en Termux, revisar primero `xio/RUNBOOK.md`, `xio/FACES.md` y
`xio/HOTSPOT_SHOW_RUNBOOK.md`.

## Pruebas sin hardware

Las pruebas necesitan `requirements-dev.txt`, no sólo el requirements del
runtime: trae `pytest`, y `flask` es obligatorio para el puente staged —sin
Flask ese módulo entero se salta en silencio y sus nueve pruebas no corren.

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest tests
```

Las diez suites de `showcontrol` se ejecutan con el intérprete, no con pytest:
insertan su propio directorio en `sys.path` e importan sus vecinos de forma
plana, y pytest las importa como parte del paquete `showcontrol`, cuyo
`__init__` necesita `plugins.base` desde `xio/new/`.

```bash
for t in xio/new-plugins/showcontrol/test_*.py; do python3 "$t" || break; done
```

Medido sobre Linux con `requirements-dev.txt` instalado: `python -m pytest -q`
ejecuta 184 pruebas y todas pasan; las diez suites directas de `showcontrol`
ejecutan otras 69 y todas pasan. Son 253 pruebas locales en total. Ninguna
toca el teléfono, la red ni `adb`.

Las suites de `show_reading`, `foh_learning` y `foh_knowledge` se apoyan en el
registro VERSIONADO del show DREF del 2026-07-24
(`xio/show_kit/registros/show_dref_20260724/`), no en `xio/show_kit/_logs/`,
que está ignorado por git: una prueba que se salta sola cuando falta el archivo
se lee igual que una prueba que pasa.

Los nueve gates `tests/check_xio_*.py` son aparte y no los recoge pytest.
Medido el 2026-09-17: seis pasan sin argumentos; `check_xio_field_staging.py`
pasa con `--rd-db /home/mak/data/rd.db`; `check_xio_runtime_bundle.py` pasa
contra el paquete que construye `xio/new/build_field_bundle.py`; y
`check_xio_phone_runtime.py` exige el Xiaomi conectado y no se puede cerrar
sin el teléfono. Un gate que pide un argumento y no lo recibe sale con código
2 sin medir nada: eso no es un gate verde.

Este repositorio fija su propio `pytest.ini`. Sin él, pytest sube por encima
del checkout, adopta la configuración de un directorio padre y deselecciona
todo: el comando responde `deselected` y sale con código 5 sin ejecutar nada.

Las capacidades marcadas como implementadas no implican que estén instaladas
o verificadas en el Xiaomi; consultar `xio/CAPACIDADES.md` antes de operar un
show.

## Seguridad y alcance

No se incluyen binarios de Android, cachés, datos persistentes, logs de
ejecución ni autosaves. Los tokens se leen desde el entorno o desde el
dispositivo y no forman parte del repositorio. Algunas guías conservan valores
históricos de redes privadas del show: sustituirlos por los valores actuales
antes de desplegar.

## Procedencia

Este checkout autónomo fue extraído desde VIBECODEINE y se trabaja en la rama
`integration/xio-field-20260911`, que contiene las superficies actuales
`rd_field` y `foh_monitor`. `main` y las ramas `codex/*` se conservan como
referencias o candidatos; no representan automáticamente el runtime activo.

Tres de esas ramas (`codex/xio-transport`, `codex/xio-interface-layer`,
`codex/xio-lucida-input-contract`) traen un paquete `XIO_LAYER/` completo
—transporte, sesiones peer, registro de fuentes, puente Lucida— con sus
propias pruebas. Nada de eso está en la rama activa ni en `main`, y por eso
tampoco aparece en `xio/CAPACIDADES.md`: medir sólo la rama activa mide una
fracción del repositorio. Cuál de esas ramas es la fuente única de esa capa
sigue sin decidirse.

Licencia: MIT, ver `LICENSE`.
