# Adaptador Xiaomi

Este adaptador observa el dispositivo por ADB y deja evidencia local de cada captura
de estado. No cambia el operador, la banda ni el hotspot automáticamente.

## Estado radioeléctrico

```powershell
pwsh -NoProfile -File tools/collect_device_state.ps1 -Device 8299e66f
```

La salida JSON conserva operador, tecnología, canal, RSRP, RSRQ, RSSNR/SINR, versión de
Android y archivos crudos de diagnóstico. Los valores son instantáneas; para estudiar
horarios peak hay que acumular muestras con un intervalo definido y luego analizarlas.

## Visión

La visión offline vive en `../../vision/android` y usa el mismo teléfono como dispositivo
de ejecución. Se mantiene separada del servicio de arranque del hotspot.
