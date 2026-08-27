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
python -m pip install -r xio/new/requirements.txt
python xio/new/server.py
```

La resolución por defecto de plugins busca `xio/new-plugins/`. Para despliegue
en Termux, revisar primero `xio/RUNBOOK.md`, `xio/FACES.md` y
`xio/HOTSPOT_SHOW_RUNBOOK.md`.

## Pruebas sin hardware

```bash
python -m pytest xio/new-plugins/showcontrol
python -m pytest tests/test_xio_superficie.py
python -m pytest tests/test_xio_puente_staged.py
```

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
