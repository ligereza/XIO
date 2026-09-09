# Monitor de radio y enlace de XIO

Esta herramienta observa el sistema completo desde Windows sin modificar el
Xiaomi ni forzar 4G/5G:

1. `adb dumpsys telephony.registry`: operador, RAT actual, canal, ancho de
   banda, agregación, RSRP/RSRQ/SNR, disponibilidad NR/EN-DC y estimación de
   capacidad del módem.
2. `netsh wlan show interfaces`: BSSID, canal, banda, RSSI, señal y velocidad
   de enlace entre Windows y el hotspot.
3. `ping`: latencia y pérdida hacia el gateway local y hacia `1.1.1.1`.
4. `Get-NetAdapterStatistics`: bytes transmitidos/recibidos por adaptador,
   convertidos a tasas entre muestras.

El monitor no puede ver las antenas físicas ni probar un supuesto throttling
con una sola muestra. Sí deja evidencia temporal para separar:

```text
radio celular cambia   → reselección / CA / LTE↔NR
Wi-Fi cambia            → canal/BSSID o enlace Windows↔XIO
gateway sano, Internet mal → ruta móvil, congestión o política del operador
gateway mal             → enlace local, interferencia Wi-Fi o equipo anfitrión
```

## Ejecutar ahora

Con XIO conectado por USB y la depuración autorizada:

```powershell
python xio/radio_monitor.py --once
python xio/radio_monitor.py --interval 30
```

Si hay más de un dispositivo ADB:

```powershell
python xio/radio_monitor.py --serial 8299e66f --interval 30
```

La segunda orden toma muestras suaves cada 30 segundos y escribe dos archivos
por día en `xio/data/radio_monitor/`:

- `xio-radio-YYYYMMDD.jsonl`: registro anidado completo.
- `xio-radio-YYYYMMDD.csv`: columnas comparables para análisis.

Los eventos son deliberadamente conservadores: `cell_identity_or_rat_changed`,
`cell_aggregation_changed`, `hotspot_wifi_identity_changed` y saltos de señal.
No se etiqueta `throttling` automáticamente porque eso exigiría comparar
capacidad/latencia sostenidas con el estado de radio y con la hora.

## Verificación

Los parsers se prueban sin hardware:

```powershell
python -m pytest tests/test_radio_monitor.py
```
