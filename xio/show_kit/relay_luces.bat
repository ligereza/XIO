@echo off
REM Relay Art-Net/sACN: consola por cable -> WiFi -> xio. Ctrl+C pa salir.
REM Otro destino: relay_luces.bat <IP_DEL_TELEFONO>
cd /d "%~dp0"
py artnet_relay.py %*
pause
