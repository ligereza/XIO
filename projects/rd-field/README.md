# XIO RD · Mesa de campo

Prototipo local-first para operadores y directiva de Reduciendo Daño. Es una base nueva y separada de `xio/vision/android`.

## Ejecutar en Windows

Desde la raíz del workspace:

```powershell
python -m http.server 4173 --directory projects/rd-field
```

Abrir `http://127.0.0.1:4173`. El servidor local permite probar el service worker; abrir `index.html` directamente también permite recorrer la interfaz, pero sin cache offline del navegador.

## Recorrido incluido

- Evento con inicio programado e inicio real independiente.
- ID y hora automáticos por muestra.
- Foto de cámara/archivo o imagen sintética explícitamente marcada.
- Declaración, apariencia, forma, textura y marca en capas separadas.
- Varias pruebas por muestra con cronómetro, observación, evolución, resultado y fotos de reacción.
- Edición, pausa, reanudación, persistencia en `localStorage` y exportación JSON + CSV con activos vinculados.
- Resumen de directiva con denominadores explícitos.
- Propuesta visual y recuperación demo por similitud; no afirma composición química ni entrena pesos.

## Estado de la demo

La primera carga trae registros sintéticos para hacer visible el flujo. Se conservan en el navegador bajo la clave `xio-rd-field-state-v0.1`; no hay llamadas de red ni sincronización automática.

## Host de campo

La APK RD usa por defecto `http://127.0.0.1:5000` cuando el Xiaomi ejecuta XIO
y conserva sus datos offline. Si un PC reemplaza al Xiaomi como host, el botón
`⌂` de la APK permite escribir la dirección del PC; los navegadores pueden
abrir directamente la misma superficie HTML desde ese host.

XIO-FOH es un producto Android separado (`cl.xio.foh`) con menú propio. Su
servicio en primer plano escucha Art-Net `6454`, sACN `5568` y OSC/timecode
`7000`, guarda `xio_foh.db` offline y entrega eventos al host mediante
`/api/plugins/foh_monitor/ingest` cuando vuelve la conectividad. El HTML/PWA de
`foh_monitor/view` es el hub visualizador ISKVW, no la APK activa. En Termux,
`foh_monitor` entra en modo `app_proxy` automáticamente para no competir por
los mismos puertos; en PC conserva el modo servidor.
