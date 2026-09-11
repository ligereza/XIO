# XIO

Repositorio extraído de `ligereza/vibecodeine` para reunir el sistema XIO en
un solo lugar: runtime Xiaomi/Termux, plugins, control de show, seguridad,
automatización, documentación, ideas y proyectos de instalación.

## Qué contiene

- `xio/new/`: runtime activo del servidor Flask y su dashboard web.
- `xio/new-plugins/`: plugins vivos, plantillas y pruebas off-device.
- `xio/show_kit/`: control de cues, timecode, Art-Net/OSC y materiales de los
  shows DREF CHOCOLATE y Festival Sentir.
- `xio/hotspot_boot_service/`: servicio Android de recuperación/arranque.
- `xio/seguridad/`: guardianes y notas de seguridad.
- `xio/actual/`: primera implementación del controlador ADB, conservada como
  referencia histórica.
- `cultura/`: mapa conceptual XIO, handoff técnico y puente MAK↔XIO.
- `projects/cultura/MAPA_GENERATIVO.md`: contexto del XIO dentro del mapa de
  proyectos e ideas de Cauce.
- `tests/test_xio_superficie.py` y `tests/test_xio_puente_staged.py`:
  regresiones sobre la superficie de seguridad y el puente staged.

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

Medido sobre Linux con `requirements-dev.txt` instalado: 82 pruebas, 82 pasan
—4 en `tests/test_xio_superficie.py`, 9 en `tests/test_xio_puente_staged.py` y
69 en las diez suites de `showcontrol`—. Ninguna toca el teléfono, la red ni
`adb`.

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

Snapshot tomado desde `ligereza/vibecodeine` en la revisión local
`f588ecf8`. Los paths XIO seleccionados coincidían con `origin/main` al
extraerlos; el resto del proyecto original no se copia aquí.

Licencia: MIT, ver `LICENSE`.
