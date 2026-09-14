# Contrato de entrada — XIO

XIO es un repositorio autónomo y externo a MAK: su checkout canónico local es
`/home/mak/XIO`. No usar la carpeta `/home/mak/xio` para modificar XIO; esa
carpeta pertenece a VIBECODEINE y queda congelada como legado hasta completar
su inventario.

## Topología vigente

- La rama de integración operativa es `integration/xio-field-20260911`.
- RD y FOH/ISKVW son namespaces/plugins dentro de esa rama, no ramas Git
  separadas: `rd_field` y `foh_monitor` comparten el listener HTTP de XIO.
- `main` y las ramas `codex/*` son candidatos o snapshots hasta que una
  revisión demuestre un consumidor completo; no se mezclan automáticamente.
- El repositorio tiene autoridad sobre el runtime móvil, sus plugins y sus
  contratos de captura. MAK/FLUJO tienen autoridad sobre sus propios árboles.

## Fronteras de datos

- XIO-RD usa `eventRef` y la proyección RD canónica de FLUJO/MAK; no inventa
  eventos por una referencia desconocida ni comparte datos de muestras con FOH.
- XIO-FOH/ISKVW usa `eventKey` y el contexto VJ leído desde FLUJO; no acepta ni
  escribe `eventRef` de RD.
- La SQLite del host es `/home/mak/data/rd.db`. Los datos runtime del teléfono
  y las configuraciones locales viven fuera de Git; no versionar snapshots,
  logs, caches ni credenciales.
- `foh_monitor` es un monitor pasivo; `showcontrol` es la superficie activa
  separada y mantiene sus propios gates, token y rutas de riesgo.

## Antes de cambiar

1. Leer `README.md`, `FACES.md` y `RUNBOOK.md`; el código y el dispositivo
   actual tienen prioridad sobre planes históricos.
2. Ejecutar `git status --short --branch` y conservar cambios locales. No usar
   `reset --hard`, `checkout`, borrar archivos ni sobrescribir datos sin una
   operación reversible y una autoridad explícita.
3. Validar primero off-device; no instalar APKs, abrir controles de show ni
   cambiar el hotspot por efecto de una prueba local.
4. Ejecutar `python -m pytest -q` y las suites directas de `showcontrol` antes
   de declarar una superficie lista. La prueba local no demuestra teléfono,
   red, ADB ni reconciliación post-show.

Responde en español claro y conserva `source_ref`, `eventRef`, `eventKey`,
`raw_hash` y los estados de revisión sin convertir una observación en una
afirmación química, artística o de aprendizaje.
