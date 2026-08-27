# Material de origen y criterio de extracción

## Origen

La extracción se hizo desde la copia local de `C:\IA\flujo`, clonada de
`https://github.com/ligereza/vibecodeine.git`, usando la revisión
`f588ecf8`.

## Incluido

- Todo el contenido versionado de `xio/`.
- El workflow manual para construir el APK de `xio/hotspot_boot_service`.
- `cultura/xiotech.md` y `cultura/xio-concept.html`.
- `cultura/mak_xio_puente/` y `cultura/mak_plataforma/xio_evidence.py`.
- `cultura/mak_plataforma/mak-xio.service` y `WAKE_ON_LAN.md`.
- El mapa de ideas `projects/cultura/MAPA_GENERATIVO.md`.
- La regresión específica `tests/test_xio_superficie.py`.

Se mantuvieron los paths originales para que las instrucciones, imports y
workflows de XIO sigan siendo legibles y rastreables.

## Excluido

El árbol fuente tenía elementos locales que no son código o ideas reutilizables
del sistema: Android platform-tools, ejecutables/DLL, caches `__pycache__`,
datos persistentes, `.remember`, logs, PID files y autosaves de Resolume. El
`.gitignore` de este repo los mantiene fuera de futuras publicaciones.

Los tests de integración que dependen de todo el stack MAK permanecen en el
repo padre; el código del puente y del adaptador XIO sí se conserva aquí.
