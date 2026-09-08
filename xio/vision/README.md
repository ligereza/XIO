# Visión offline de XIO

## Activo disponible

- Modelo: `models/efficientnet_lite0.tflite`
- SHA-256: `6C7AB0A6E5DCBF38A8C33B960996A55A3B4300B36A018C4545801DE3A3C8BDE0`
- Ejecución objetivo: Xiaomi Android, dentro de la aplicación local.
- Red/API: no requerida durante la inferencia.

## Alcance actual

El modelo permite probar el ciclo local de captura, inferencia, timestamp y registro. Sus
pesos son genéricos; no está entrenado para identificar sustancias ni categorías propias
de RD. Cualquier salida debe tratarse como propuesta visual y quedar sujeta a revisión
humana explícita.

## Próximo adaptador Android

1. Cargar el `.tflite` desde los assets de una app Android.
2. Ejecutar ImageClassifier en el Xiaomi.
3. Asociar cada captura con el evento y timestamp de XIO.
4. Guardar resultado, confianza y decisión humana en el registro local.
5. Reemplazar posteriormente el clasificador genérico por uno entrenado con imágenes
   autorizadas y etiquetadas por RD.

## Código inicial

El adaptador Android está en `android/src/main/java/com/xio/vision/`. Produce un
`VisionProposal` con `eventId`, timestamp, etiquetas, puntuaciones y `proposalId`.
La propuesta siempre queda marcada para revisión humana y no ejecuta acciones.

El proyecto `hotspot_boot_service` se mantiene separado: su responsabilidad es el
arranque del hotspot y no debe mezclarse con el adaptador de visión.

## Demo ejecutable en Xiaomi

El proyecto Android está en `android/`. La demo hace lo siguiente:

1. abre la cámara del sistema mediante `TakePicture` y conserva el archivo capturado;
2. crea un `eventId` y conserva el timestamp de captura;
3. ejecuta `ImageClassifier` localmente con MediaPipe;
4. muestra una propuesta, nunca una decisión;
5. guarda la imagen capturada en el almacenamiento privado y una línea JSON en `vision_proposals.jsonl` dentro del almacenamiento privado
   de la app.

La primera pulsación solicita el permiso de cámara de Android de forma visible. XIO no
lo concede por ADB ni captura imágenes en segundo plano.

El modelo se copia a `android/app/src/main/assets/efficientnet_lite0.tflite`. La app no
requiere red para inferir ni envía las imágenes. La persistencia local no debe tratarse
como base de datos oficial hasta definir retención, cifrado, exportación y revisión de
privacidad con RD.

### Build e instalación

Desde PowerShell, después de instalar el toolchain Android:

```powershell
pwsh -File android/tools/deploy_vision.ps1 -Device 8299e66f
```

El script valida el modelo y ejecuta `assembleDebug`. Por defecto no modifica el teléfono.
Después de una confirmación explícita para instalar en el Xiaomi, se añade `-Install`:

```powershell
pwsh -File android/tools/deploy_vision.ps1 -Device 8299e66f -Install
```

Con `-Install`, instala el APK y abre la demo.
No activa permisos, no envía datos y no inicia acciones sobre otras aplicaciones.

### Estado de verificación

- Código y asset preparados.
- Xiaomi visible y autorizado por ADB.
- APK aún pendiente de compilación hasta que Java/SDK queden disponibles en Windows.
- La primera ejecución sirve para validar el circuito técnico; EfficientNet-Lite0 es un
  clasificador genérico y no identifica por sí solo reactivos o sustancias de RD.
