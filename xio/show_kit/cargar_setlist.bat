@echo off
REM Carga setlist_festival_sentir.txt al foh_monitor. Doble click.
REM Edita el .txt primero (un tema por linea). Otro host: cargar_setlist.bat <IP>
cd /d "%~dp0"
set HOST=%1
if "%HOST%"=="" set HOST=192.168.127.125
py -c "import sys,urllib.request,json; txt=open('setlist_festival_sentir.txt',encoding='utf-8').read(); req=urllib.request.Request('http://%HOST%:5000/api/plugins/foh_monitor/setlist',data=json.dumps({'text':txt}).encode(),headers={'Content-Type':'application/json'}); r=json.load(urllib.request.urlopen(req,timeout=6)); print('OK' if r.get('ok') else 'FALLO', '-', r.get('total'), 'temas. Actual:', r.get('current'))"
pause
