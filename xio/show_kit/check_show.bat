@echo off
REM Chequeo pre-show GO/NO-GO. Doble click. Si el telefono no esta de hotspot,
REM correr en consola: py check_show.py <IP_DEL_TELEFONO>
cd /d "%~dp0"
py check_show.py %*
pause
