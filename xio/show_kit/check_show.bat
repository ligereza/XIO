@echo off
REM Chequeo pre-show GO/NO-GO. Doble click. Si el telefono no esta de hotspot,
REM por defecto descubre el gateway actual del hotspot; no guarda una IP
REM correr en consola con override si el sistema no publica su gateway:
REM py check_show.py <IP_DEL_TELEFONO>
cd /d "%~dp0"
py check_show.py %*
pause
