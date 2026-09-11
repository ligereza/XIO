@echo off
REM Carga setlist_festival_sentir.txt al foh_monitor. Doble click.
REM Edita el .txt primero (un tema por linea). Si no pasas IP, descubre el
REM gateway actual del hotspot; no conserva una IP historica.
cd /d "%~dp0"
set "HOST=%~1"
if not defined HOST (
  for /f "usebackq delims=" %%H in (`py "%~dp0discover_xio.py" --print-host 2^>nul`) do if not defined HOST set "HOST=%%H"
)
if not defined HOST (
  echo No se encontro XIO. Conecta este equipo al hotspot o usa cargar_setlist.bat ^<IP-XIO^>
  pause
  exit /b 2
)
py -c "import urllib.request,json; txt=open('setlist_festival_sentir.txt',encoding='utf-8').read(); req=urllib.request.Request('http://%HOST%:5000/api/plugins/foh_monitor/setlist',data=json.dumps({'text':txt}).encode(),headers={'Content-Type':'application/json'}); op=urllib.request.build_opener(urllib.request.ProxyHandler({})); r=json.load(op.open(req,timeout=6)); print('OK' if r.get('ok') else 'FALLO', '-', r.get('total'), 'temas. Actual:', r.get('current'))"
pause
