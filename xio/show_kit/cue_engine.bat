@echo off
REM Cue engine DREF: escucha /timecode :7001 y dispara clips en Resolume :7000.
REM Prueba sin Resolume: cue_engine.bat --dry-run
cd /d "%~dp0"
py cue_engine.py %*
pause
