"""
FOH Monitor -- vigia pasivo de cabina (Front Of House) para show en vivo.

Que hace (TODO lectura, cero interferencia con el rig):
  - Listeners UDP pasivos en threads daemon:
      * Art-Net (6454)  -- valida header "Art-Net\\0", cuenta OpDmx
      * sACN   (5568)   -- valida root layer ACN; join multicast 239.255.u.u
                           best-effort (si HyperOS lo bloquea degrada a unicast
                           y lo anota en /status)
      * OSC    (7000)   -- parse minimo del address pattern (primer string \\0-pad)
      * Timecode: OSC con address que empiece por tc_address (default /timecode,
        puente LTC M-Audio -> Chataigne -> OSC) es un canal PROPIO: se parsea el
        primer arg (string "HH:MM:SS:FF" o float) y se trackea corriendo /
        congelado (mismo valor >tc_freeze_seconds con paquetes llegando) /
        caido (sin paquetes > active_window). IMPORTANTE: /timecode NO cuenta
        como actividad del canal osc/VISUAL -- un show con solo TC entrando no
        debe marcar "visuales activos".
    Por canal: last_seen, packets/s, activo si hubo paquetes en los ultimos
    N segundos (config active_window, default 5).
  - Audio best-effort via Termux:API: termux-microphone-record a chunks cortos
    + decodificacion con ffmpeg a PCM + RMS en python puro. Si falta
    termux-api o ffmpeg -> "audio: no disponible" SIN romper el resto.
  - Setlist: cargar lineas de texto, tema actual, /next (tap). Todo al registro.
  - Registro JSONL por dia: /sdcard/xio_termux/foh_logs/show_YYYYMMDD.jsonl
    (evento por linea: ts, tipo, detalle). GET /log lo descarga post-show.
  - Panel: GET /api/plugins/foh_monitor/panel -> HTML autocontenido fullscreen
    dark pensado pa la pantalla del Xiaomi en FOH (tiles grandes, boton NEXT
    gordo, auto-refresh 1s + TIMECODE interpolado suave local, wake-lock best-effort).

Seguridad: NINGUN endpoint en DANGEROUS_ENDPOINTS -- todo es lectura +
setlist next (inocuo). Los listeners solo hacen bind/recv, jamas envian.
"""

from plugins.base import PluginBase

import json
import math
import os
import re
import shutil
import socket
import struct
import subprocess
import threading
import time
from datetime import datetime

_ARTNET_HEADER = b"Art-Net\x00"
_ACN_PID = b"ASC-E1.17\x00\x00\x00"

# Lo que el operador puede decir EN VIVO sobre el tramo que esta corriendo.
# La distincion importa y no se puede reconstruir despues: el 2026-07-24 los
# tramos sin timecode eran CCTV, texto y conversacion con el publico -- o sea
# CONTENIDO -- y el panel los pintaba igual que una caida. Quien sabe cual es
# cual es quien esta ahi, en ese momento.
#   contenido -> ese tramo es su propio bloque; no es el tema anterior
#   falla     -> el tema siguio corriendo, lo que se cayo fue la señal
#   nota      -> cualquier otra cosa que valga anotar sin interpretarla
MARK_CLASSES = ("contenido", "falla", "nota")

# Direccion de disparo de clip de Resolume. `cue_map_dref.json` ya declara la
# plantilla: /composition/layers/{layer}/clips/{clip}/connect. En un show sin
# timecode este address es el unico reloj que ademas NOMBRA lo que sono.
_CLIP_ADDRESS = re.compile(
    r"/composition/layers?/(\d+)/clips?/(\d+)/(connect|select)\b", re.IGNORECASE)

# Panel autocontenido (sin assets externos: funciona offline en el hotspot).
# Fetch por URLs RELATIVAS asi el host/IP da igual.
_PANEL_HTML = """<!doctype html><html lang=es><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>FOH Monitor</title>
<link rel=manifest href=manifest.webmanifest>
<meta name=mobile-web-app-capable content=yes>
<meta name=apple-mobile-web-app-capable content=yes>
<meta name=theme-color content="#07090d">
<style>
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
html,body{height:100%}
body{font:16px/1.3 -apple-system,system-ui,Roboto,sans-serif;background:#07090d;color:#e8eaed;
 display:flex;flex-direction:column;padding:10px;gap:10px;user-select:none}
.tiles{display:flex;gap:10px}
.tile{flex:1;border-radius:14px;padding:12px 8px;text-align:center;border:2px solid #232838;background:#12151d;transition:background .3s}
.tile .nm{font-size:14px;font-weight:800;letter-spacing:.08em}
.tile .st{font-size:26px;font-weight:900;margin:4px 0}
.tile .meta{font-size:12px;opacity:.85}
.t-on{background:#0c2a17;border-color:#1e7a41}.t-on .st{color:#4ade80}
.t-off{background:#2a0d10;border-color:#8c2530}.t-off .st{color:#f87171}
.t-na{background:#1a1a20;border-color:#3a3a44}.t-na .st{color:#9aa0b0;font-size:18px}
.now{background:#12151d;border:2px solid #232838;border-radius:16px;padding:14px 12px 16px;text-align:center}
.now .nowtc{font:800 23px/1 ui-monospace,Menlo,Consolas,monospace;letter-spacing:.04em;color:#9aa0b0}
.now .nowlbl{font-size:10px;color:#8a92a6;text-transform:uppercase;letter-spacing:.12em;margin-top:3px}
.now .title{font-size:40px;font-weight:900;line-height:1.04;margin:12px 0;word-break:break-word}
.now .nxt{font-size:13px;color:#8a92a6;margin-top:10px}
.now.tc-run{border-color:#1e7a41}.now.tc-run .nowtc{color:#4ade80}
.now.tc-bad{border-color:#8c2530}.now.tc-bad .nowtc{color:#f87171}
.now.tc-na .nowtc{color:#9aa0b0}
.bar{position:relative;height:28px;background:#0d1016;border:1px solid #1c2130;border-radius:9px;overflow:hidden}
.bar>i{display:block;height:100%;width:0;background:linear-gradient(90deg,#1e7a41,#4ade80);transition:width .16s linear}
.bar .pct{position:absolute;top:0;left:0;right:0;line-height:28px;font:800 14px ui-monospace,monospace;color:#e6e9ef;text-shadow:0 1px 3px #000}
.row{display:flex;gap:10px;align-items:center;font-size:13px;color:#9aa0b0;justify-content:space-between}
.mk{flex:1;font:800 15px inherit;padding:15px 8px;border-radius:12px;background:#12151d;border:1px solid #334155;color:#cbd5e1;letter-spacing:.04em}
#mkc{color:#4ade80;border-color:#14532d}#mkf{color:#f87171;border-color:#7f1d1d}
.mk:active{filter:brightness(1.6)}
.feed{flex:1;overflow-y:auto;background:#0d1016;border:1px solid #1c2130;border-radius:12px;padding:8px}
.ev{font-size:13px;padding:5px 8px;border-left:3px solid #333;margin-bottom:4px;background:#12151d;border-radius:0 8px 8px 0}
.ev .t{color:#6b7280;font-size:11px;margin-right:6px}
.e-on{border-color:#4ade80}.e-off{border-color:#f87171}.e-set{border-color:#60a5fa}.e-au{border-color:#fbbf24}
.hot{color:#f87171;font-weight:800}
.ctx{background:#101827;border:1px solid #29405f;border-radius:12px;padding:9px 11px;color:#cbd5e1;font-size:13px}
.ctx a{color:#60a5fa;font-weight:800;text-decoration:none;float:right}
</style></head><body>
<div class=ctx id=ctx>FOH / ISKVW · contexto sin seleccionar <a href=context>EVENTO</a></div>
<div class=tiles id=tiles></div>
<div class="now tc-na" id=nowbox>
 <div class=nowtc id=tcval>--:--:--:--</div>
 <div class=nowlbl id=tclbl>TIMECODE</div>
 <div class=title id=cur>--</div>
 <div class=bar id=barwrap><i id=barfill></i><span class=pct id=barpct></span></div>
 <div class=nxt id=nx></div>
</div>
<div class=row><span id=batt></span><span><a href=mapping style="color:#60a5fa;font-weight:800;text-decoration:none;padding:6px 8px">MAPPING</a><a href=registro style="color:#60a5fa;font-weight:800;text-decoration:none;padding:6px 8px">REGISTRO &#9776;</a><a href=/raider?domain=foh style="color:#fbbf24;font-weight:800;text-decoration:none;padding:6px 8px">RAIDER</a></span><span id=sub>...</span></div>
<div class=row><button class=mk id=mkc>TRAMO: CONTENIDO</button><button class=mk id=mkf>FALLA</button></div>
<div class=row><span id=mkst style="font-size:12px">marcar en vivo: lo que el log no puede reconstruir despues</span></div>
<div class=feed id=feed></div>
<script>
function esc(s){return String(s).replace(/[&<>"]/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
function tile(nm,ch){
 if(ch&&ch.na)return '<div class="tile t-na"><div class=nm>'+nm+'</div><div class=st>N/D</div><div class=meta>'+esc(ch.reason||'')+'</div></div>';
 // nunca visto = gris N/D (esperado si ese canal no se cablea este show);
 // visto y perdido = rojo OFF (eso si es alerta)
 if(ch&&!ch.active&&ch.age==null)return '<div class="tile t-na"><div class=nm>'+nm+'</div><div class=st>N/D</div><div class=meta>sin se&ntilde;al aun</div></div>';
 var on=ch&&ch.active,ago=(ch&&ch.age!=null)?('hace '+ch.age+'s'):'nunca';
 var pps=(ch&&ch.pps!=null)?(ch.pps+' pps'):'';
 return '<div class="tile '+(on?'t-on':'t-off')+'"><div class=nm>'+nm+'</div><div class=st>'+(on?'ON':'OFF')+'</div><div class=meta>'+ago+(pps?' &middot; '+pps:'')+'</div></div>';
}
function evcls(t){return t.indexOf('senal_on')>=0?'e-on':(t.indexOf('off')>=0||t.indexOf('silencio')>=0?'e-off':(t.indexOf('setlist')>=0?'e-set':'e-au'))}
function tick(){
 fetch('status',{cache:'no-store'}).then(function(r){return r.json()}).then(function(s){
  var luces=s.channels.artnet.active?s.channels.artnet:s.channels.sacn;
  luces={active:s.channels.artnet.active||s.channels.sacn.active,
   age:Math.min(s.channels.artnet.age==null?1e9:s.channels.artnet.age,s.channels.sacn.age==null?1e9:s.channels.sacn.age),
   pps:(s.channels.artnet.pps||0)+(s.channels.sacn.pps||0)};
  if(luces.age>=1e9)luces.age=null;
  var au=s.audio&&s.audio.available?{active:s.audio.active,age:s.audio.age,pps:null}:{na:1,reason:(s.audio&&s.audio.reason)||'no disponible'};
  document.getElementById('tiles').innerHTML=tile('LUCES',luces)+tile('VISUAL',s.channels.osc)+tile('AUDIO',au);
  var tc=s.timecode||{},box=document.getElementById('nowbox');
  var st=tc.state||'sin_senal',run=st=='corriendo';
  box.className='now '+(run?'tc-run':(st=='sin_senal'?'tc-na':'tc-bad'));
  // guarda la base pal interpolador local (paintTc/paintBar); NO escribe aca.
  var base=(tc.value!=null&&!isNaN(parseFloat(tc.value)))?parseFloat(tc.value):null;
  TC={base:base,state:st,at:performance.now(),fps:tc.fps||30,
      disp:(tc.display!=null?tc.display:tc.value)};
  document.getElementById('tclbl').textContent='TIMECODE '+st.toUpperCase().replace('_',' ')+(tc.age!=null?' · hace '+tc.age+'s':'');
  var sl=s.setlist||{};
  SL={start:(sl.start_sec!=null?sl.start_sec:null),dur:(sl.dur||null)};
  document.getElementById('cur').textContent=sl.current_name||'(sin setlist)';
  document.getElementById('nx').textContent=sl.next_name?('sigue: '+sl.next_name):'';
  var b=s.battery||{};var bp=[];
  if(b.level!=null)bp.push('BAT '+b.level+'%'+(b.charging?' &#9889;':''));
  if(b.temperature)bp.push((b.temperature>=45?'<span class=hot>':'')+b.temperature+'&deg;C'+(b.temperature>=45?'</span>':''));
  document.getElementById('batt').innerHTML=bp.join(' &middot; ');
  var cx=s.context||{},ce=cx.current;
  document.getElementById('ctx').innerHTML=ce?
   'FOH / ISKVW · '+esc(ce.name||ce.eventKey)+' · '+esc(ce.dateIso||ce.dateRaw||'fecha por confirmar')+
   ' · '+esc(ce.venueName||'venue por confirmar')+' <a href=context>CAMBIAR</a>':
   'FOH / ISKVW · contexto sin seleccionar <a href=context>SELECCIONAR</a>';
  return fetch('events?limit=10',{cache:'no-store'});
 }).then(function(r){return r.json()}).then(function(ev){
  document.getElementById('feed').innerHTML=(ev&&ev.length)?ev.slice().reverse().map(function(x){
   return '<div class="ev '+evcls(x.tipo||'')+'"><span class=t>'+esc((x.ts||'').slice(11,19))+'</span>'+esc(x.tipo)+' '+esc(typeof x.detalle=='string'?x.detalle:JSON.stringify(x.detalle))+'</div>';
  }).join(''):'<div class=ev>sin eventos</div>';
  document.getElementById('sub').textContent='upd '+new Date().toLocaleTimeString();
 }).catch(function(e){document.getElementById('sub').textContent='ERR '+e});
}
// interpolador local del TIMECODE: cuenta suave en tiempo real entre polls
// (LTC = tiempo real, 1s wall = 1s TC), re-sincroniza en cada tick. SOLO
// cuando el estado es 'corriendo'; si esta congelado/caido/sin senal muestra
// el valor del server tal cual (un freeze real se ve, no sigue contando).
var TC={base:null,state:'sin_senal',at:0,fps:30,disp:null};
var SL={start:null,dur:null};
function fmtTc(sec,fps){if(sec<0)sec=0;var h=Math.floor(sec/3600),m=Math.floor((sec%3600)/60),s=Math.floor(sec%60),f=Math.floor((sec-Math.floor(sec))*fps);if(f>=fps)f=fps-1;function p(n){return(n<10?'0':'')+n}return p(h)+':'+p(m)+':'+p(s)+':'+p(f)}
function tcNow(){return (TC.state=='corriendo'&&TC.base!=null)?TC.base+(performance.now()-TC.at)/1000:TC.base}
function paintTc(){var el=document.getElementById('tcval');if(!el)return;
 if(TC.state=='corriendo'&&TC.base!=null){el.textContent=fmtTc(TC.base+(performance.now()-TC.at)/1000,TC.fps);}
 else{el.textContent=TC.disp!=null?TC.disp:(TC.state=='sin_senal'?'--:--:--:--':'?');}}
function paintBar(){var w=document.getElementById('barwrap'),fi=document.getElementById('barfill'),pc=document.getElementById('barpct');if(!w)return;
 // barra solo si hay duracion (visual) y TC corriendo/congelado; sin visual -> sin barra.
 if(SL.dur&&SL.start!=null&&TC.base!=null&&(TC.state=='corriendo'||TC.state=='congelado')){
  var p=(tcNow()-SL.start)/SL.dur;if(p<0)p=0;if(p>1)p=1;
  w.style.display='';fi.style.width=(p*100).toFixed(1)+'%';pc.textContent=Math.round(p*100)+'%';
 }else{w.style.display='none';}}
setInterval(function(){paintTc();paintBar();},50);
// wake-lock best-effort (requiere gesto en algunos Android)
var wl=null;function lock(){if(navigator.wakeLock&&!wl)navigator.wakeLock.request('screen').then(function(l){wl=l;l.addEventListener('release',function(){wl=null})}).catch(function(){})}
document.addEventListener('click',lock);document.addEventListener('visibilitychange',function(){if(!document.hidden)lock()});lock();
// marca en vivo: un toque dice si este tramo es contenido o es falla. Sin
// esto, el log de un tramo sin timecode se lee igual en los dos casos.
function mark(c,btn){var label=btn.textContent;btn.textContent='...';
 fetch('mark',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({clase:c})})
 .then(function(r){return r.json()}).then(function(d){
  document.getElementById('mkst').textContent=d.ok?('marcado '+c+(d.tc!=null?(' \u00b7 tc '+d.tc):' \u00b7 sin tc')):('no se pudo marcar: '+esc(d.error||''));
  btn.textContent=label;tick()})
 .catch(function(e){document.getElementById('mkst').textContent='ERR '+esc(e);btn.textContent=label})}
document.getElementById('mkc').onclick=function(){mark('contenido',this)};
document.getElementById('mkf').onclick=function(){mark('falla',this)};
tick();setInterval(tick,1000);
</script></body></html>"""


# Contexto de evento VJ/FOH. Es una seleccion exacta sobre el read model
# existente de FLUJO; no conoce ni acepta eventRef de RD.
_CONTEXT_HTML = """<!doctype html><html lang=es><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,maximum-scale=1">
<title>FOH Evento</title>
<style>
*{box-sizing:border-box}body{font:16px/1.35 -apple-system,system-ui,Roboto,sans-serif;background:#07090d;color:#e8eaed;padding:14px;max-width:720px;margin:0 auto}
h1{font-size:20px;margin:0 0 4px}.sub{color:#8a92a6;font-size:12px;margin-bottom:14px}.card{background:#12151d;border:1px solid #293247;border-radius:14px;padding:14px;margin:10px 0}
label{display:block;color:#9aa0b0;font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:.08em;margin:12px 0 5px}
select,button{width:100%;font:inherit;border-radius:10px;padding:11px;background:#0d1016;color:#e8eaed;border:1px solid #334155}
button{background:#1d4ed8;border-color:#2563eb;font-weight:800;margin-top:12px}button.secondary{background:#12151d;border-color:#334155;color:#cbd5e1}
.ok{color:#4ade80}.warn{color:#fbbf24}.err{color:#f87171}.meta{color:#cbd5e1;margin-top:8px}.key{font:12px ui-monospace,Menlo,Consolas,monospace;color:#93c5fd;word-break:break-all}
a{color:#60a5fa;font-weight:800;text-decoration:none}ul{padding-left:18px;color:#cbd5e1}li{margin:5px 0}
</style></head><body>
<h1>FOH / ISKVW · evento</h1><div class=sub>Contexto del rubro VJ artistico. No es la superficie RD y no acepta datos de muestras.</div>
<div class=card id=state>cargando catalogo VJ...</div>
<div class=card><label for=event>Evento exacto del catalogo VJ</label><select id=event disabled><option>Cargando...</option></select>
<button id=save disabled>Usar este evento en FOH</button><button class=secondary id=clear disabled>Quitar contexto actual</button></div>
<div class=card><a href=panel>← volver al panel FOH</a></div>
<script>
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
var data=null;
function kitText(c){var k=c&&c.showKit;if(!k)return '<div class=meta>Kit FOH: sin enlace explicito</div>';
 var files=[k.cueMap,k.setlist,k.durations].filter(Boolean).join(' · ');
 return '<div class=meta><span class=ok>Kit FOH enlazado</span> · '+esc(k.root||'xio/show_kit')+(files?'<br>'+esc(files):'')+'</div>';}
function currentText(c){if(!c)return '<span class=warn>Sin evento seleccionado. El registro FOH seguira funcionando, pero no tendra contexto VJ.</span>';
 return '<span class=ok>Contexto activo</span><div class=meta>'+esc(c.name)+'<br>'+esc(c.dateIso||c.dateRaw||'fecha por confirmar')+' · '+esc(c.venueName||'venue por confirmar')+'<br><span class=key>'+esc(c.eventKey)+'</span></div>'+kitText(c);}
function load(){fetch('context/data',{cache:'no-store'}).then(function(r){return r.json()}).then(function(d){
 data=d;var st=document.getElementById('state');
 if(!d.catalogAvailable){st.innerHTML='<span class=err>Catalogo VJ no disponible.</span><div class=meta>'+esc(d.error||'Instala el read model foh_vj_context.json generado desde FLUJO.')+'</div>';return;}
 st.innerHTML=currentText(d.current)+'<div class=meta>'+d.events.length+' eventos conocidos · solo lectura de catalogo</div>';
 var sel=document.getElementById('event');sel.innerHTML='<option value="">Seleccionar...</option>'+d.events.map(function(e){return '<option value="'+esc(e.eventKey)+'">'+esc(e.name)+' · '+esc(e.dateIso||e.dateRaw||'sin fecha')+'</option>';}).join('');
 if(d.current)sel.value=d.current.eventKey;sel.disabled=false;document.getElementById('save').disabled=false;document.getElementById('clear').disabled=false;
 }).catch(function(e){document.getElementById('state').innerHTML='<span class=err>Error de lectura: '+esc(e)+'</span>';})}
document.getElementById('save').onclick=function(){var k=document.getElementById('event').value;if(!k)return;
 fetch('context',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({eventKey:k})}).then(function(r){return r.json().then(function(d){return {ok:r.ok,data:d}})}).then(function(x){if(!x.ok)throw x.data.error||'no se pudo seleccionar';load()}).catch(function(e){document.getElementById('state').innerHTML='<span class=err>'+esc(e)+'</span>'})};
document.getElementById('clear').onclick=function(){fetch('context',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({clear:true})}).then(function(){load()})};
load();
</script></body></html>"""


# Registro legible del dia (mobile-first, misma estetica que el panel).
# Lee el JSONL del dia via fetch relativo a 'log' y lo pinta como tabla
# filtrable. ?date=YYYYMMDD pa dias anteriores. Sin dependencias externas.
_REGISTRO_HTML = """<!doctype html><html lang=es><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,maximum-scale=1">
<title>FOH Registro</title>
<link rel=manifest href=manifest.webmanifest>
<meta name=mobile-web-app-capable content=yes>
<meta name=apple-mobile-web-app-capable content=yes>
<meta name=theme-color content="#07090d">
<style>
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
body{font:14px/1.35 -apple-system,system-ui,Roboto,sans-serif;background:#07090d;color:#e8eaed;
 padding:10px;max-width:720px;margin:0 auto}
.top{display:flex;align-items:center;gap:8px;margin-bottom:10px}
h1{font-size:17px;font-weight:900;letter-spacing:.05em;flex:1}
.top a{color:#60a5fa;font-weight:800;text-decoration:none;padding:6px 10px;border:1px solid #1c2130;border-radius:10px}
.sub{color:#8a92a6;font-size:11px}
.chips{display:flex;gap:6px;margin-bottom:10px;overflow-x:auto;padding-bottom:2px}
.chip{flex-shrink:0;padding:8px 14px;border-radius:20px;border:1px solid #232838;background:#12151d;
 color:#9aa0b0;font-size:13px;font-weight:700}
.chip.on{background:#1d3a8a;border-color:#2563eb;color:#fff}
table{width:100%;border-collapse:collapse}
th{font-size:10px;color:#8a92a6;text-transform:uppercase;letter-spacing:.08em;text-align:left;
 padding:4px 6px;position:sticky;top:0;background:#07090d}
td{padding:6px;border-top:1px solid #161a24;vertical-align:top}
.hora{color:#6b7280;font-size:12px;white-space:nowrap}
.tc{font:700 12px ui-monospace,Menlo,Consolas,monospace;color:#9aa0b0;white-space:nowrap}
.tipo{font-weight:800;font-size:12px;white-space:nowrap}
.det{color:#c9cdd6;font-size:13px;word-break:break-word}
.t-bad{color:#f87171}.t-ok{color:#4ade80}.t-set{color:#60a5fa}.t-sys{color:#9aa0b0}
.empty{color:#6b7280;padding:16px;text-align:center}
</style></head><body>
<div class=top><h1>REGISTRO <span class=sub id=fecha></span></h1><a href=panel>PANEL &#9654;</a></div>
<div class=chips id=chips></div>
<table><thead><tr><th>Hora</th><th>TC</th><th>Tipo</th><th>Detalle</th></tr></thead>
<tbody id=tb><tr><td colspan=4 class=empty>cargando...</td></tr></tbody></table>
<div class=sub id=sub style="text-align:center;padding:10px"></div>
<script>
var FILTROS={todos:null,
 senales:['senal_on','senal_off','audio_silencio'],
 TC:['tc_freeze','tc_resume'],
 setlist:['setlist_next'],
 sistema:['heartbeat','bateria']};
var filtro='todos';
var qd=new URLSearchParams(location.search).get('date');
document.getElementById('fecha').textContent=qd?qd:'hoy';
function esc(s){return String(s).replace(/[&<>"]/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
function cls(t){
 if(t=='senal_off'||t=='tc_freeze'||t=='audio_silencio')return 't-bad';
 if(t=='senal_on'||t=='tc_resume')return 't-ok';
 if(t=='setlist_next')return 't-set';
 return 't-sys';}
function compacto(t,d){
 if(typeof d!='object'||d==null)return esc(String(d));
 if(t=='senal_on')return esc((d.canal||'')+' ON'+(d.info?' ('+d.info+')':'')+(d.pps?' '+d.pps+'pps':''));
 if(t=='senal_off')return esc((d.canal||'')+' OFF'+(d.ultimo?' (ultimo '+String(d.ultimo).slice(11)+')':''));
 if(t=='tc_freeze')return esc('TC '+(d.estado||'')+' en '+(d.valor||'?'));
 if(t=='tc_resume')return esc('TC corre de nuevo'+(d.valor?' ('+d.valor+')':''));
 if(t=='setlist_next')return esc((d.accion?d.accion+': ':'')+(d.actual||'')+(d.n?' ('+d.n+'/'+d.de+')':''));
 if(t=='audio_silencio')return esc('silencio'+(d.level_db!=null?' ('+d.level_db+' dBFS)':''));
 if(t=='bateria')return esc((d.nivel!=null?d.nivel+'%':'')+(d.cargando?' cargando':' sin cargar')+(d.temp?' '+d.temp+'C':''));
 if(t=='heartbeat'){if(d.msg)return esc(d.msg);var a=d.activos||{};var on=[];for(var k in a)if(a[k]===true||a[k]=='corriendo')on.push(k);
  return esc('vivo; activos: '+(on.join(', ')||'ninguno')+(d.bateria!=null?' | bat '+d.bateria+'%':''))}
 return esc(JSON.stringify(d));}
function chips(){var h='';for(var f in FILTROS)h+='<div class="chip'+(f==filtro?' on':'')+'" data-f="'+f+'">'+f+'</div>';
 var el=document.getElementById('chips');el.innerHTML=h;
 el.querySelectorAll('.chip').forEach(function(c){c.addEventListener('click',function(){filtro=c.dataset.f;chips();render()})})}
var rows=[];
function render(){
 var keep=FILTROS[filtro];
 var vis=rows.filter(function(r){return !keep||keep.indexOf(r.tipo)>=0});
 var tb=document.getElementById('tb');
 if(!vis.length){tb.innerHTML='<tr><td colspan=4 class=empty>sin eventos'+(filtro!='todos'?' de '+filtro:'')+'</td></tr>';return}
 tb.innerHTML=vis.slice().reverse().map(function(r){
  return '<tr><td class=hora>'+esc((r.ts||'').slice(11,19))+'</td><td class=tc>'+(r.tc?esc(r.tc):'--')+
   '</td><td class="tipo '+cls(r.tipo)+'">'+esc(r.tipo)+'</td><td class=det>'+compacto(r.tipo,r.detalle)+'</td></tr>'}).join('')}
function tick(){
 fetch('log'+(qd?'?date='+qd:''),{cache:'no-store'}).then(function(r){
  if(r.status==404)throw 'sin registro pa este dia';
  if(!r.ok)throw 'HTTP '+r.status;return r.text()})
 .then(function(txt){
  rows=txt.split('\\n').filter(Boolean).map(function(l){try{return JSON.parse(l)}catch(e){return null}}).filter(Boolean);
  render();document.getElementById('sub').textContent=rows.length+' eventos | upd '+new Date().toLocaleTimeString();
 }).catch(function(e){document.getElementById('tb').innerHTML='<tr><td colspan=4 class=empty>'+esc(e)+'</td></tr>';
  document.getElementById('sub').textContent=''});}
chips();tick();setInterval(tick,3000);
</script></body></html>"""


class _Channel:
    """Estado de un canal de senal (thread-safe por GIL: solo ints/floats)."""

    def __init__(self, name):
        self.name = name
        self.last_seen = 0.0     # epoch del ultimo paquete valido
        self.total = 0           # paquetes validos acumulados
        self.other = 0           # paquetes en el puerto que NO validaron
        self.buckets = {}        # segundo(int) -> count, pa packets/s
        self.info = ""           # detalle libre (universo, address, etc.)
        self.error = ""          # error de bind/listener si lo hubo
        # De QUE maquina llega la señal. `recvfrom` ya lo entrega y se estaba
        # tirando. Sirve para dos cosas que hoy no existen: saber que notebook
        # manda cada canal (post-show), y ver un cambio de fuente EN VIVO --
        # el 2026-07-24 el venue cambio la IP por DHCP, y eso es exactamente lo
        # que rompe Chataigne a mitad de show.
        self.source = ""
        self.sources = {}        # ip -> paquetes validos desde ahi
        self.source_changes = 0

    def hit(self, info="", source=""):
        now = time.time()
        self.last_seen = now
        self.total += 1
        sec = int(now)
        self.buckets[sec] = self.buckets.get(sec, 0) + 1
        if len(self.buckets) > 12:
            cutoff = sec - 10
            for k in [k for k in self.buckets if k < cutoff]:
                self.buckets.pop(k, None)
        if info:
            self.info = info
        if source:
            if self.source and source != self.source:
                self.source_changes += 1
            self.source = source
            self.sources[source] = self.sources.get(source, 0) + 1

    def pps(self):
        """Promedio de paquetes/s sobre los ultimos 3 segundos completos."""
        now = int(time.time())
        n = sum(self.buckets.get(now - i, 0) for i in (1, 2, 3))
        return round(n / 3.0, 1)

    def snapshot(self, window):
        age = None if not self.last_seen else round(time.time() - self.last_seen, 1)
        return {
            "active": bool(self.last_seen and age is not None and age <= window),
            "last_seen": (datetime.fromtimestamp(self.last_seen).isoformat(timespec="seconds")
                          if self.last_seen else None),
            "age": age,
            "pps": self.pps(),
            "packets_total": self.total,
            "invalid_packets": self.other,
            "source": self.source or None,
            "sources": dict(sorted(self.sources.items(), key=lambda kv: -kv[1])[:4]) or None,
            "source_changes": self.source_changes,
            "info": self.info,
            "error": self.error,
        }


class FohMonitorPlugin(PluginBase):
    plugin_id = "foh_monitor"
    name = "FOH Monitor"
    version = "1.0.0"
    description = "Vigia pasivo de cabina: Art-Net/sACN/OSC + audio + setlist + registro JSONL del show."
    author = "Cauce"
    icon = "activity"
    category = "network"
    permissions = ["network"]

    DEFAULTS = {
        "artnet_port": 6454,
        "sacn_port": 5568,
        "osc_port": 7000,
        "active_window": 5,        # seg sin paquetes => canal OFF
        "sacn_universes": "1-16",  # universos pa join multicast best-effort
        # Enlace por el que unirse a los grupos sACN. Vacio = automatico
        # (prefiere wlan1, el AP del Xiaomi). Ver _multicast_interface.
        "sacn_interface": "",
        "audio_enabled": True,
        "audio_chunk_seconds": 2,  # duracion de cada muestra de mic
        "audio_threshold_db": -50, # RMS dBFS: por encima => hay audio
        "heartbeat_seconds": 60,
        "battery_poll_seconds": 15,  # cada cuanto el loop refresca bateria (shell); /status usa cache
        "tc_address": "/timecode",  # prefijo OSC del timecode (LTC->Chataigne->OSC)
        "tc_fps": 30,               # fps del LTC, pa convertir segundos->HH:MM:SS:FF en el tile
        "tc_drives_setlist": True,  # el TC entrante mueve solo el tema actual del setlist
        "tc_freeze_seconds": 2,     # mismo valor este tiempo con paquetes => congelado
        "log_dir": "/sdcard/xio_termux/foh_logs",
        "battery_delta": 5,        # loguea bateria al cambiar >= esto (%)
        # Read model VJ generado desde FLUJO. No se comparte con RD.
        "foh_context_file": "",
    }

    def __init__(self, context):
        super().__init__(context)
        self._stop = threading.Event()
        self._sockets = []
        self._channels = {
            "artnet": _Channel("artnet"),
            "sacn": _Channel("sacn"),
            "osc": _Channel("osc"),
        }
        self._sacn_mode = "desconocido"  # multicast | unicast (join fallo)
        self._sacn_interface = None  # enlace por el que se unio a los grupos
        # Timecode: canal propio, excluido del canal osc/VISUAL.
        self._tc = {"value": None, "last_seen": 0.0, "last_change": 0.0,
                    "total": 0, "state": "sin_senal"}
        self._tc_buckets = {}  # segundo -> count (pps del TC)
        self._tc_song_index = -1  # ultimo tema auto-detectado por TC (evita re-loguear)
        self._clip_last = None  # ultimo (capa, clip) logueado: solo se registra el cambio
        self._audio = {"available": False, "reason": "no evaluado", "level_db": None,
                       "active": False, "last_seen": 0.0}
        self._setlist = {"songs": [], "durations": [], "index": -1,
                         "loaded_at": None, "advanced_at": None,
                         "fohEventKey": None}
        self._events = []          # ring pa el panel (el JSONL es la verdad)
        self._prev_active = {}     # canal -> bool (deteccion de transiciones)
        self._prev_batt = {}       # ultimo estado de bateria logueado
        self._last_heartbeat = 0.0
        # bateria CACHEADA: el shell (dumpsys) lo hace el loop _tick cada
        # battery_poll_seconds; /status sirve el cache -> nunca toca shell en
        # el request (evita el pile-up de latencia ~25s con varios que miran).
        self._batt_cache = {"level": None, "charging": False,
                            "status": "unknown", "temperature": None}
        self._batt_at = 0.0
        self._log_lock = threading.Lock()
        self._log_dir_real = None  # resuelto en on_load
        self._foh_context_catalog = {"schema": "xio-foh-vj-context-v1", "source": {}, "events": []}
        self._foh_context_current = None
        self._foh_context_file = None
        self._foh_context_current_file = None

    # ── lifecycle ────────────────────────────────────────────────────
    def on_load(self):
        for k, v in self.DEFAULTS.items():
            if self.get_config(k, None) is None:
                self.set_config(k, v)

        self.register_route("/status", self._api_status, methods=["GET"])
        self.register_route("/view", self._api_view, methods=["GET"])
        self.register_route("/raider", self._api_raider, methods=["GET"])
        self.register_route("/panel", self._api_panel, methods=["GET"])
        self.register_route("/registro", self._api_registro, methods=["GET"])
        self.register_route("/resumen", self._api_summary, methods=["GET"])
        self.register_route("/context", self._api_context_page, methods=["GET"])
        self.register_route("/context/data", self._api_context_get, methods=["GET"])
        self.register_route("/context", self._api_context_post, methods=["POST"])
        self.register_route("/mapping", self._api_mapping, methods=["GET"])
        self.register_route("/manifest.webmanifest", self._api_manifest, methods=["GET"])
        self.register_route("/events", self._api_events, methods=["GET"])
        self.register_route("/setlist", self._api_setlist_get, methods=["GET"])
        self.register_route("/setlist", self._api_setlist_post, methods=["POST"])
        self.register_route("/next", self._api_next, methods=["POST"])
        self.register_route("/prev", self._api_prev, methods=["POST"])
        self.register_route("/log", self._api_log, methods=["GET"])
        self.register_route("/logs", self._api_logs, methods=["GET"])
        self.register_route("/mark", self._api_mark, methods=["POST"])
        self.register_route("/ingest", self._api_ingest, methods=["POST"])
        self.register_route("/config", self._api_get_config, methods=["GET"])
        self.register_route("/config", self._api_set_config, methods=["POST"])

        self._resolve_log_dir()
        self._load_foh_context()
        self._load_setlist()  # sobrevivir restarts del server en pleno show
        self._start_listener("artnet", int(self._cfg("artnet_port")), self._parse_artnet)
        self._start_sacn()
        self._start_listener("osc", int(self._cfg("osc_port")), self._parse_osc_pkt)
        self._probe_audio()
        if self._audio["available"] and self._cfg("audio_enabled"):
            t = threading.Thread(target=self._audio_loop, daemon=True, name="foh-audio")
            t.start()
        self.context.schedule("foh_tick", self._tick, interval_seconds=1)
        self._log_event("heartbeat", {"msg": "foh_monitor cargado",
                                      "sacn_mode": self._sacn_mode,
                                      "audio": self._audio["reason"] if not self._audio["available"] else "ok"})
        self.logger.info("FOH Monitor loaded (artnet=%s sacn=%s[%s] osc=%s audio=%s)" % (
            self._cfg("artnet_port"), self._cfg("sacn_port"), self._sacn_mode,
            self._cfg("osc_port"),
            "ok" if self._audio["available"] else self._audio["reason"]))

    def on_unload(self):
        self._stop.set()
        self.context.cancel_schedule("foh_tick")
        for s in self._sockets:
            try:
                s.close()
            except Exception:
                pass

    def _cfg(self, key):
        return self.get_config(key, self.DEFAULTS.get(key))

    # ── registro JSONL ───────────────────────────────────────────────
    def _resolve_log_dir(self):
        # The launcher may pin logs to a durable host directory.  Environment
        # wins over a stale config.json copied with an older runtime.
        d = os.environ.get("XIO_FOH_LOG_DIR", "").strip() or str(self._cfg("log_dir"))
        try:
            os.makedirs(d, exist_ok=True)
            probe = os.path.join(d, ".probe")
            with open(probe, "w") as f:
                f.write("ok")
            os.remove(probe)
        except Exception:
            d = str(self.data_dir / "foh_logs")
            os.makedirs(d, exist_ok=True)
        self._log_dir_real = d

    def _resolve_foh_context_file(self):
        # The deployment env wins over a copied config value; the catalog itself
        # is a read-only snapshot generated from FLUJO before the field session.
        configured = (os.environ.get("XIO_FOH_CONTEXT_FILE", "").strip()
                      or str(self._cfg("foh_context_file") or "").strip())
        if configured:
            return os.path.expanduser(configured)
        return os.path.join(os.path.dirname(__file__), "foh_vj_context.json")

    def _load_foh_context(self):
        """Load the VJ read model and the current exact FOH selection.

        The catalog is immutable during the operation. Only the selected
        event key is persisted, and only when that exact key exists in the
        catalog. It never reads or writes RD ``eventRef``.
        """
        self._foh_context_file = self._resolve_foh_context_file()
        self._foh_context_current_file = os.path.join(
            self._log_dir_real, "context_actual.json")
        try:
            with open(self._foh_context_file, encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, dict) or raw.get("schema") != "xio-foh-vj-context-v1":
                raise ValueError("schema VJ/FOH invalido")
            events = []
            seen = set()
            for event in raw.get("events") or []:
                if not isinstance(event, dict):
                    continue
                key = str(event.get("eventKey") or "").strip()
                if not key or key in seen:
                    continue
                seen.add(key)
                events.append(dict(event))
            self._foh_context_catalog = {
                "schema": "xio-foh-vj-context-v1",
                "source": raw.get("source") if isinstance(raw.get("source"), dict) else {},
                "events": events,
            }
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            self._foh_context_catalog = {
                "schema": "xio-foh-vj-context-v1", "source": {}, "events": []
            }
            self.logger.warning(f"foh VJ context unavailable: {exc}")
        try:
            with open(self._foh_context_current_file, encoding="utf-8") as f:
                current = json.load(f)
            key = str(current.get("eventKey") or "").strip() if isinstance(current, dict) else ""
            self._foh_context_current = next(
                (dict(e) for e in self._foh_context_catalog["events"]
                 if e.get("eventKey") == key),
                None,
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            self._foh_context_current = None

    def _save_foh_context(self):
        if not self._foh_context_current_file:
            return
        target = self._foh_context_current_file
        temporary = target + ".tmp"
        if self._foh_context_current is None:
            try:
                os.remove(target)
            except FileNotFoundError:
                pass
            return
        with open(temporary, "w", encoding="utf-8") as f:
            json.dump({"schema": "xio-foh-vj-context-selection-v1",
                       "eventKey": self._foh_context_current["eventKey"]}, f,
                      ensure_ascii=False, indent=2)
        os.replace(temporary, target)

    def _foh_context_view(self):
        return {
            "ok": True,
            "domain": "vj_foh",
            "catalogAvailable": bool(self._foh_context_catalog.get("events")),
            "catalogFile": self._foh_context_file,
            "selectionFile": self._foh_context_current_file,
            "source": self._foh_context_catalog.get("source", {}),
            "current": self._foh_context_current,
            "events": self._foh_context_catalog.get("events", []),
            "setlistBinding": self._setlist_binding_view(),
            "event_policy": "fohEventKey_must_exist_in_vj_catalog",
            "rd_is_separate": True,
        }

    # ── persistencia del setlist (restart del server NO borra el show) ─
    def _setlist_file(self):
        return os.path.join(self._log_dir_real, "setlist_actual.json")

    def _save_setlist(self):
        try:
            with open(self._setlist_file(), "w", encoding="utf-8") as f:
                json.dump(self._setlist, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error(f"foh setlist save failed: {e}")

    def _load_setlist(self):
        """Recarga songs + index al arrancar: un restart de watchdog/reboot en
        pleno show retoma en el tema vigente, no en el tema 1."""
        try:
            with open(self._setlist_file(), encoding="utf-8") as f:
                data = json.load(f)
            songs = [str(s) for s in data.get("songs", []) if str(s).strip()]
            if not songs:
                return
            idx = int(data.get("index", 0))
            durations = self._norm_durations(data.get("durations"), len(songs))
            self._setlist = {
                "songs": songs,
                "durations": durations,
                "index": max(-1, min(idx, len(songs) - 1)),
                "loaded_at": data.get("loaded_at"),
                "advanced_at": data.get("advanced_at"),
                "fohEventKey": str(data.get("fohEventKey") or "").strip() or None,
            }
            self.logger.info(f"foh setlist recargado: {len(songs)} temas, index {self._setlist['index']}")
        except FileNotFoundError:
            pass
        except Exception as e:
            self.logger.error(f"foh setlist load failed: {e}")

    def _setlist_binding_view(self):
        """Describe the exact relationship between setlist and FOH context."""
        setlist = getattr(self, "_setlist", {}) or {}
        owner = str(setlist.get("fohEventKey") or "").strip()
        current = str((self._foh_context_current or {}).get("eventKey") or "").strip()
        if not setlist.get("songs"):
            status = "not_loaded"
        elif owner and owner == current:
            status = "bound"
        elif owner:
            status = "conflict"
        else:
            status = "unbound"
        return {"status": status, "fohEventKey": owner or None,
                "contextMatch": bool(owner and current and owner == current),
                "songs": len(setlist.get("songs") or [])}

    def _bind_unowned_setlist_to_context(self, selected):
        """Bind an unowned setlist after explicit exact-event selection.

        Existing songs, index, durations and timestamps are preserved. A
        different existing owner is never silently overwritten.
        """
        setlist = getattr(self, "_setlist", {}) or {}
        key = str((selected or {}).get("eventKey") or "").strip()
        owner = str(setlist.get("fohEventKey") or "").strip()
        if not setlist.get("songs"):
            return {"status": "not_loaded", "fohEventKey": owner or None}
        if owner:
            return {"status": "already" if owner == key else "conflict",
                    "fohEventKey": owner}
        kit = (selected or {}).get("showKit") or {}
        setlist_ref = str(kit.get("setlist") or "").strip() if isinstance(kit, dict) else ""
        if not setlist_ref:
            return {"status": "no_kit", "fohEventKey": None}
        setlist["fohEventKey"] = key
        self._setlist = setlist
        self._save_setlist()
        self._log_event("setlist_context_bound", {
            "fohEventKey": key, "setlist": setlist_ref,
            "reason": "exact_context_selected_for_unowned_setlist",
        }, key)
        return {"status": "bound", "fohEventKey": key, "setlist": setlist_ref}

    def _log_path(self, date_str=None):
        date_str = date_str or datetime.now().strftime("%Y%m%d")
        return os.path.join(self._log_dir_real, f"show_{date_str}.jsonl")

    def _log_event(self, tipo, detalle, event_key=None):
        """Una linea JSON al archivo del dia (rotacion implicita por nombre)."""
        # cada evento lleva el ultimo timecode vigente pa correlacion post-show
        current_key = event_key if event_key is not None else (self._foh_context_current or {}).get("eventKey")
        ev = {"ts": datetime.now().isoformat(timespec="seconds"), "tipo": tipo,
              "detalle": detalle, "tc": self._tc_current(), "domain": "vj_foh",
              "fohEventKey": current_key}
        self._events.append(ev)
        self._events = self._events[-200:]
        try:
            with self._log_lock:
                with open(self._log_path(), "a", encoding="utf-8") as f:
                    f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        except Exception as e:
            self.logger.error(f"foh log write failed: {e}")

    # ── listeners UDP pasivos ────────────────────────────────────────
    def _bind_udp(self, port):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.settimeout(1.0)
        s.bind(("0.0.0.0", port))
        self._sockets.append(s)
        return s

    def _start_listener(self, key, port, parser):
        ch = self._channels[key]
        try:
            sock = self._bind_udp(port)
        except Exception as e:
            ch.error = f"bind {port} fallo: {e}"
            self.logger.error(f"foh {key}: {ch.error}")
            return
        t = threading.Thread(target=self._recv_loop, args=(sock, ch, parser),
                             daemon=True, name=f"foh-{key}")
        t.start()

    # Nombres del enlace del show, en orden de preferencia. wlan1 es el AP en
    # este Xiaomi; wlan0 seria el WiFi cliente; ap0/swlan0 aparecen en otros
    # vendors. Se PREGUNTA por nombre porque Android no deja enumerar.
    SHOW_INTERFACES = ("wlan1", "ap0", "swlan0", "wlan0")

    def _multicast_interface(self):
        """El enlace por el que hay que unirse a los grupos sACN.

        `IP_ADD_MEMBERSHIP` con la interfaz en 0.0.0.0 deja que el kernel elija,
        y elige la ruta por OMISION. En el Xiaomi eso es la red celular
        (`rmnet_data2`), no el hotspot (`wlan1`), asi que el join tenia exito y
        no llegaba nada.

        Medido el 2026-09-17 sobre este mismo plugin corriendo en el telefono:
        uniendose por la ruta por omision, 12 paquetes multicast dieron CERO;
        uniendose explicitamente por wlan1, llegaron los 12 -- y SIN que nadie
        tuviera el MulticastLock del WiFi, con la APK detenida. Antes se le
        habia echado la culpa a ese lock, y era falso: tomarlo no cambio nada.
        O sea que sACN por multicast SI funciona en este aparato, al contrario
        de lo que decia el runbook.

        Y no se enumera: en Android `socket.if_nameindex()` levanta
        PermissionError -- enumerar interfaces esta restringido desde Android 11
        -- mientras que `socket.if_nametoindex("wlan1")` SI funciona y devuelve
        su indice. Medido en el telefono el 2026-09-17. En un PC la enumeracion
        funciona y el defecto no se nota, asi que se pregunta por nombre y la
        enumeracion queda solo como camino secundario.
        """
        def indice(nombre):
            try:
                return socket.if_nametoindex(nombre)
            except Exception:
                return 0

        wanted = str(self._cfg("sacn_interface") or "").strip()
        if wanted:
            return wanted if indice(wanted) else None
        for nombre in self.SHOW_INTERFACES:
            if indice(nombre):
                return nombre
        try:
            for _, nombre in socket.if_nameindex():
                if nombre.startswith("wlan") or nombre.startswith("ap"):
                    return nombre
        except Exception:
            pass
        return None

    def _start_sacn(self):
        ch = self._channels["sacn"]
        port = int(self._cfg("sacn_port"))
        try:
            sock = self._bind_udp(port)
        except Exception as e:
            ch.error = f"bind {port} fallo: {e}"
            self.logger.error(f"foh sacn: {ch.error}")
            return
        # Join multicast por universo (239.255.hi.lo), POR EL ENLACE DEL SHOW.
        # No hace falta ningun MulticastLock: medido el 2026-09-17, este
        # proceso recibio 12 de 12 con la APK detenida. Lo que hacia falta era
        # unirse por el enlace correcto.
        link = self._multicast_interface()
        index = 0
        if link:
            try:
                index = socket.if_nametoindex(link)
            except Exception:
                index = 0
        self._sacn_interface = link if index else None
        joined = 0
        for u in self._parse_universes(str(self._cfg("sacn_universes"))):
            try:
                grp = socket.inet_aton(f"239.255.{(u >> 8) & 0xFF}.{u & 0xFF}")
                if index:
                    # ip_mreqn: grupo, direccion local, indice de interfaz.
                    mreq = struct.pack("4s4si", grp, socket.inet_aton("0.0.0.0"), index)
                else:
                    mreq = struct.pack("4s4s", grp, socket.inet_aton("0.0.0.0"))
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
                joined += 1
            except Exception:
                pass
        if joined and link:
            self._sacn_mode = f"multicast({joined} joins por {link})"
        elif joined:
            self._sacn_mode = (f"multicast({joined} joins por la ruta por omision: "
                               "puede no ser el enlace del show)")
        else:
            self._sacn_mode = "unicast (join multicast fallo/bloqueado)"
        t = threading.Thread(target=self._recv_loop, args=(sock, ch, self._parse_sacn),
                             daemon=True, name="foh-sacn")
        t.start()

    @staticmethod
    def _parse_universes(spec):
        out = set()
        for part in spec.replace(" ", "").split(","):
            if not part:
                continue
            try:
                if "-" in part:
                    a, b = part.split("-", 1)
                    out.update(range(int(a), min(int(b), 63999) + 1))
                else:
                    out.add(int(part))
            except Exception:
                continue
        return sorted(out)[:64]  # tope sano de joins

    def _recv_loop(self, sock, ch, parser):
        while not self._stop.is_set():
            try:
                data, addr = sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break  # socket cerrado en unload
            try:
                info = parser(data)
            except Exception:
                info = None
            if info is False:
                continue  # manejado por otro canal (p.ej. timecode)
            if info is None:
                ch.other += 1
            else:
                source = addr[0] if isinstance(addr, tuple) and addr else ""
                previous = ch.source
                ch.hit(info, source)
                # Un cambio de fuente en vivo se registra: el enlace se cae (o
                # cambia de IP) ANTES de que se noten los datos, y con esto el
                # log lo dice en el momento en vez de dejarlo para deducir.
                if source and previous and source != previous:
                    self._log_event("fuente_cambio", {
                        "canal": ch.name, "antes": previous, "ahora": source,
                        "cambios": ch.source_changes})

    # parsers: devuelven str info si el paquete es valido, None si no
    @staticmethod
    def _parse_artnet(data):
        if len(data) < 12 or not data.startswith(_ARTNET_HEADER):
            return None
        opcode = data[8] | (data[9] << 8)
        if opcode == 0x5000 and len(data) >= 18:  # OpDmx
            payload_length = (data[16] << 8) | data[17]
            if payload_length > 512 or len(data) < 18 + payload_length:
                return None
            uni = data[14] | (data[15] << 8)
            return f"OpDmx uni {uni}"
        return f"op 0x{opcode:04x}"

    @staticmethod
    def _parse_sacn(data):
        if len(data) < 126 or data[4:16] != _ACN_PID:
            return None
        uni = (data[113] << 8) | data[114]
        return f"E1.31 uni {uni}"

    def _parse_osc_pkt(self, data):
        """Parser del listener OSC. Los mensajes cuyo address empieza por
        tc_address alimentan el canal TIMECODE y devuelven False (NO cuentan
        como actividad del canal osc/VISUAL -- un show con solo TC entrando
        no debe marcar visuales activos)."""
        messages = self._osc_messages(data)
        if not messages:
            return None
        tc_address = str(self._cfg("tc_address"))
        visual_addresses = []
        for message in messages:
            address = self._parse_osc(message)
            if isinstance(address, str) and address.startswith(tc_address):
                self._tc_hit(message)
            elif address:
                visual_addresses.append(address)
                self._note_clip_trigger(address)
        if messages and not visual_addresses:
            return False
        return visual_addresses[0] if visual_addresses else None

    def _note_clip_trigger(self, address):
        """Record WHICH clip was triggered, once per change.

        Resolume manda muchos mensajes por segundo, asi que se registra solo el
        cambio de (capa, clip) -- igual que el avance automatico por timecode
        actua solo al cambiar el frame. El address ya venia parseado y se usaba
        nada mas que para prender el tile VISUAL; su contenido, que es lo unico
        que dice QUE se vio, no se guardaba en ninguna parte.
        """
        match = _CLIP_ADDRESS.search(address or "")
        if not match:
            return
        pair = (int(match.group(1)), int(match.group(2)))
        if pair == self._clip_last:
            return
        self._clip_last = pair
        self._log_event("clip_trigger", {"layer": pair[0], "clip": pair[1],
                                         "address": str(address)[:120]})

    def _tc_hit(self, data):
        """Registra un paquete de timecode: primer arg string o float."""
        self._record_tc_value(self._osc_first_arg(data))

    def _record_tc_value(self, val):
        """Registra TC recibido por OSC o por el puente APK sin contar visuales."""
        if val is None:
            return
        now = time.time()
        tc = self._tc
        tc["total"] += 1
        tc["last_seen"] = now
        if val is not None and val != tc["value"]:
            tc["value"] = val
            tc["last_change"] = now
            self._auto_setlist_por_tc(val)  # solo al cambiar el frame
        sec = int(now)
        self._tc_buckets[sec] = self._tc_buckets.get(sec, 0) + 1
        if len(self._tc_buckets) > 12:
            cutoff = sec - 10
            for k in [k for k in self._tc_buckets if k < cutoff]:
                self._tc_buckets.pop(k, None)

    @staticmethod
    def _tc_str_a_segundos(tcstr, fps):
        """'HH:MM:SS:FF' o segundos-en-string -> segundos (float). None si no
        parsea. Acepta el mismo formato que el prefijo del setlist y el valor
        crudo del OSC."""
        if tcstr is None:
            return None
        s = str(tcstr).strip()
        if ":" in s:
            parts = s.split(":")
            try:
                h = int(parts[0]); m = int(parts[1]); sec = int(parts[2])
                f = int(parts[3]) if len(parts) > 3 else 0
            except (ValueError, IndexError):
                return None
            return h * 3600 + m * 60 + sec + (f / fps if fps else 0.0)
        try:
            return float(s)
        except (TypeError, ValueError):
            return None

    def _auto_setlist_por_tc(self, raw_value):
        """Mueve el tema actual del setlist segun el TC entrante: el tema
        vigente es el ULTIMO cuyo timecode de inicio (prefijo 'HH:MM:SS:FF  '
        de cada linea) es <= el TC actual. Loguea el cambio una sola vez.
        No-op si esta desactivado, sin setlist, o el setlist no trae timecodes."""
        if not self._cfg("tc_drives_setlist"):
            return
        songs = self._setlist["songs"]
        if not songs:
            return
        fps = int(self._cfg("tc_fps"))
        ahora = self._tc_str_a_segundos(raw_value, fps)
        if ahora is None:
            return
        idx = -1
        for i, linea in enumerate(songs):
            prefijo = linea.split(None, 1)[0] if linea.split(None, 1) else ""
            inicio = self._tc_str_a_segundos(prefijo, fps)
            if inicio is None:
                return  # setlist sin timecodes: no auto-avanzar (modo manual)
            if inicio <= ahora:
                idx = i
            else:
                break  # starts ordenados: el primero mayor corta
        if idx < 0 or idx == self._tc_song_index:
            return
        self._tc_song_index = idx
        self._setlist["index"] = idx
        self._setlist["advanced_at"] = datetime.now().isoformat(timespec="seconds")
        self._save_setlist()
        durs = self._setlist.get("durations") or []
        sin_visual = not (0 <= idx < len(durs) and durs[idx])
        self._log_event("setlist_next", {"accion": "auto-tc", "actual": songs[idx],
                                         "n": idx + 1, "de": len(songs),
                                         "sin_visual": sin_visual})

    @staticmethod
    def _osc_first_arg(data):
        """Primer argumento de un mensaje OSC como string. Flexible: 's' tal
        cual, 'f'/'d' formateado, 'i'/'h' entero. None si no hay args."""
        try:
            end = data.find(b"\x00")
            if end <= 0:
                return None
            pos = (end + 4) & ~3  # address con padding a 4
            if pos >= len(data) or data[pos:pos + 1] != b",":
                return None
            tend = data.find(b"\x00", pos)
            if tend < 0:
                return None
            tags = data[pos + 1:tend].decode("ascii", "replace")
            pos = (tend + 4) & ~3
            if not tags:
                return None
            t = tags[0]
            if t == "s":
                send = data.find(b"\x00", pos)
                if send < 0:
                    return None
                return data[pos:send].decode("utf-8", "replace")
            if t == "f":
                return str(round(struct.unpack(">f", data[pos:pos + 4])[0], 3))
            if t == "d":
                return str(round(struct.unpack(">d", data[pos:pos + 8])[0], 3))
            if t == "i":
                return str(struct.unpack(">i", data[pos:pos + 4])[0])
            if t == "h":
                return str(struct.unpack(">q", data[pos:pos + 8])[0])
            return None
        except Exception:
            return None

    def _fmt_tc_display(self, raw):
        """Valor legible HH:MM:SS:FF pal tile. Chataigne manda el LTC como
        SEGUNDOS (float en string, ej '23529.267578125'); se convierte a
        frames con tc_fps. Si ya viniera formateado (trae ':') se muestra tal
        cual; si no es numerico, crudo. El valor CRUDO se conserva aparte pal
        JSONL (precision forense)."""
        if raw is None:
            return None
        s = str(raw)
        if ":" in s:
            return s
        try:
            total = float(s)
        except (TypeError, ValueError):
            return s
        if total < 0:
            total = 0.0
        fps = int(self._cfg("tc_fps"))
        h = int(total // 3600)
        m = int((total % 3600) // 60)
        sec = int(total % 60)
        frames = int(round((total - int(total)) * fps))
        if frames >= fps:  # el redondeo puede empujar a fps: normalizar
            frames = fps - 1
        return "%02d:%02d:%02d:%02d" % (h, m, sec, frames)

    def _tc_state(self):
        """Estado del timecode + valor vigente (pa /status, panel y JSONL)."""
        tc = self._tc
        now = time.time()
        window = int(self._cfg("active_window"))
        freeze = float(self._cfg("tc_freeze_seconds"))
        if not tc["last_seen"]:
            state, age = "sin_senal", None
        else:
            age = round(now - tc["last_seen"], 1)
            if age > window:
                state = "caido"
            elif tc["value"] is not None and (now - tc["last_change"]) > freeze:
                state = "congelado"
            else:
                state = "corriendo"
        nsec = int(now)
        pps = round(sum(self._tc_buckets.get(nsec - i, 0) for i in (1, 2, 3)) / 3.0, 1)
        return {"value": tc["value"], "display": self._fmt_tc_display(tc["value"]),
                "fps": int(self._cfg("tc_fps")),
                "state": state, "age": age, "pps": pps,
                "packets_total": tc["total"], "address": str(self._cfg("tc_address"))}

    def _tc_current(self):
        """Ultimo timecode VIGENTE pa correlacion en el JSONL (null si no hay
        senal o si el TC esta caido -- un valor viejo correlaciona mal)."""
        st = self._tc_state()
        return st["value"] if st["state"] in ("corriendo", "congelado") else None

    @staticmethod
    def _parse_osc(data):
        if data.startswith(b"#bundle"):
            return "#bundle"
        if not data.startswith(b"/"):
            return None
        end = data.find(b"\x00")
        if end <= 0:
            return None
        try:
            return data[:end].decode("ascii", "replace")
        except Exception:
            return None

    @classmethod
    def _osc_messages(cls, data, _depth=0):
        """Return OSC messages contained in one packet or nested bundle.

        FOH only needs the address and first argument, so this intentionally
        parses bundle framing without becoming a general OSC decoder. A depth
        limit prevents malformed recursive bundles from consuming the listener.
        """
        if not isinstance(data, (bytes, bytearray)) or _depth > 4:
            return []
        data = bytes(data)
        if not data.startswith(b"#bundle\x00"):
            return [data] if cls._parse_osc(data) else []
        if len(data) < 16:
            return []
        messages = []
        pos = 16  # '#bundle\\0' + 8-byte NTP timetag
        while pos + 4 <= len(data):
            size = struct.unpack(">I", data[pos:pos + 4])[0]
            pos += 4
            end = pos + size
            if size == 0 or end > len(data):
                return []
            messages.extend(cls._osc_messages(data[pos:end], _depth + 1))
            pos = end
        return messages if pos == len(data) else []

    # ── audio best-effort (Termux:API + ffmpeg) ──────────────────────
    def _probe_audio(self):
        if not self._cfg("audio_enabled"):
            self._audio.update(available=False, reason="deshabilitado por config")
            return
        rec = shutil.which("termux-microphone-record")
        if not rec:
            self._audio.update(available=False, reason="termux-microphone-record no instalado (pkg install termux-api + app Termux:API)")
            return
        ff = shutil.which("ffmpeg")
        if not ff:
            self._audio.update(available=False, reason="ffmpeg no instalado (pkg install ffmpeg) -- sin decodificador no hay RMS")
            return
        self._audio.update(available=True, reason="")

    def _audio_loop(self):
        """Graba chunks cortos, decodifica a PCM s16le mono y calcula RMS dBFS.
        Cualquier fallo apaga el canal con motivo honesto; nunca tumba el plugin."""
        tmp = str(self.data_dir / "foh_mic.m4a")
        fails = 0
        while not self._stop.is_set():
            secs = max(1, int(self._cfg("audio_chunk_seconds")))
            try:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                subprocess.run(["termux-microphone-record", "-f", tmp, "-l", str(secs)],
                               capture_output=True, timeout=15)
                # esperar la duracion + margen y cerrar la grabacion
                self._stop.wait(secs + 0.5)
                subprocess.run(["termux-microphone-record", "-q"], capture_output=True, timeout=10)
                if not os.path.exists(tmp) or os.path.getsize(tmp) < 100:
                    raise RuntimeError("grabacion vacia (mic ocupado o permiso denegado)")
                p = subprocess.run(["ffmpeg", "-v", "error", "-i", tmp, "-f", "s16le",
                                    "-ac", "1", "-ar", "8000", "-"],
                                   capture_output=True, timeout=20)
                raw = p.stdout
                if len(raw) < 2:
                    raise RuntimeError("decodificacion vacia")
                db = self._rms_dbfs(raw)
                self._audio["level_db"] = db
                if db >= float(self._cfg("audio_threshold_db")):
                    self._audio["active"] = True
                    self._audio["last_seen"] = time.time()
                else:
                    window = int(self._cfg("active_window"))
                    if time.time() - self._audio["last_seen"] > window:
                        self._audio["active"] = False
                fails = 0
            except Exception as e:
                fails += 1
                if fails >= 3:
                    self._audio.update(available=False, active=False,
                                       reason=f"mic fallo {fails}x: {e}")
                    self.logger.error(f"foh audio OFF: {e}")
                    return
                self._stop.wait(3)

    @staticmethod
    def _rms_dbfs(raw):
        import array
        samples = array.array("h")
        samples.frombytes(raw[: len(raw) - (len(raw) % 2)])
        if not samples:
            return -120.0
        acc = 0
        for v in samples:
            acc += v * v
        rms = math.sqrt(acc / len(samples))
        if rms < 1:
            return -120.0
        return round(20 * math.log10(rms / 32768.0), 1)

    # ── tick: transiciones + heartbeat + bateria ─────────────────────
    def _battery(self):
        """Bateria CACHEADA (sin shell). El refresh real lo hace _refresh_battery
        desde el loop _tick; /status y el panel sirven este cache -> el request
        nunca se serializa en el shell-lock (fin del pile-up de ~25s)."""
        return self._batt_cache

    def _refresh_battery(self):
        """Lee la bateria real (shell/dumpsys) y actualiza el cache. Solo lo
        llama el loop _tick, nunca un request."""
        try:
            self._batt_cache = self.controller.battery_status()
        except Exception:
            self._batt_cache = {"level": None, "charging": False,
                                "status": "unknown", "temperature": None}
        self._batt_at = time.time()

    def _tick(self):
        window = int(self._cfg("active_window"))
        now = time.time()
        # transiciones de senal
        for key, ch in self._channels.items():
            active = bool(ch.last_seen and (now - ch.last_seen) <= window)
            was = self._prev_active.get(key)
            if was is None:
                self._prev_active[key] = active
                continue
            if active and not was:
                self._log_event("senal_on", {"canal": key, "info": ch.info, "pps": ch.pps()})
            elif was and not active:
                self._log_event("senal_off", {"canal": key,
                                              "ultimo": datetime.fromtimestamp(ch.last_seen).isoformat(timespec="seconds") if ch.last_seen else None})
            self._prev_active[key] = active
        # audio silencio (solo si el canal esta vivo)
        if self._audio["available"]:
            a_act = self._audio["active"]
            was = self._prev_active.get("_audio")
            if was is None:
                self._prev_active["_audio"] = a_act
            else:
                if was and not a_act:
                    self._log_event("audio_silencio", {"level_db": self._audio["level_db"]})
                elif a_act and not was:
                    self._log_event("senal_on", {"canal": "audio", "level_db": self._audio["level_db"]})
                self._prev_active["_audio"] = a_act
        # timecode: transiciones corriendo <-> congelado/caido (alerta)
        tcs = self._tc_state()
        prev_tc = self._prev_active.get("_tc")
        if tcs["state"] != "sin_senal":
            if prev_tc is None:
                self._prev_active["_tc"] = tcs["state"]
            elif tcs["state"] != prev_tc:
                if tcs["state"] in ("congelado", "caido") and prev_tc == "corriendo":
                    self._log_event("tc_freeze", {"estado": tcs["state"],
                                                  "valor": self._tc["value"],
                                                  "pps": tcs["pps"]})
                elif tcs["state"] == "corriendo" and prev_tc in ("congelado", "caido"):
                    self._log_event("tc_resume", {"valor": self._tc["value"]})
                elif tcs["state"] == "caido" and prev_tc == "congelado":
                    self._log_event("tc_freeze", {"estado": "caido",
                                                  "valor": self._tc["value"], "pps": 0})
                self._prev_active["_tc"] = tcs["state"]
        # bateria: refresco real (shell) por intervalo, EN el loop -> /status usa cache
        if now - self._batt_at >= int(self._cfg("battery_poll_seconds")):
            self._refresh_battery()
        # heartbeat + bateria
        hb = int(self._cfg("heartbeat_seconds"))
        if now - self._last_heartbeat >= hb:
            self._last_heartbeat = now
            bat = self._battery()
            snap = {k: c.snapshot(window)["active"] for k, c in self._channels.items()}
            snap["audio"] = self._audio["active"] if self._audio["available"] else None
            snap["tc"] = self._tc_state()["state"]
            self._log_event("heartbeat", {"activos": snap, "bateria": bat.get("level"),
                                          "cargando": bat.get("charging")})
            lvl = bat.get("level")
            prev_lvl = self._prev_batt.get("level")
            if lvl is not None and (prev_lvl is None
                                    or abs(lvl - prev_lvl) >= int(self._cfg("battery_delta"))
                                    or bat.get("charging") != self._prev_batt.get("charging")):
                self._log_event("bateria", {"nivel": lvl, "cargando": bat.get("charging"),
                                            "temp": bat.get("temperature")})
                self._prev_batt = {"level": lvl, "charging": bat.get("charging")}

    # ── API ──────────────────────────────────────────────────────────
    def _host_domain(self):
        """Which surface this host declares itself to be."""
        return os.environ.get("XIO_HOST_DOMAIN", "all").strip().lower() or "all"

    def _port_ownership(self):
        """Say out loud who may own the show ports on this host.

        `xio/new/server.py` no carga este plugin cuando el host se declara RD,
        y ahi la APK nativa es la dueña de 6454/5568/7000. Pero el valor por
        omision de XIO_HOST_DOMAIN es "all": en un host sin dominio declarado
        este plugin SI bindea, y como los sockets se abren con SO_REUSEADDR un
        doble bind no falla -- se reparte los paquetes en silencio, que es peor
        que un error. No se cambia el comportamiento aca (el flujo de prueba en
        PC depende de que estos listeners funcionen sin declarar dominio); se
        declara, para que un monitor a medias no se lea como un monitor sano.

        El README de `projects/foh-monitor` decia que esto lo resolvia un
        `listener_mode=auto` con modos `server` y `app_proxy`. Ese ajuste no
        existe en el codigo: la separacion real es XIO_HOST_DOMAIN.
        """
        domain = self._host_domain()
        owned = domain in ("foh", "iskvw")
        return {
            "declared_by": "XIO_HOST_DOMAIN",
            "host_domain": domain,
            "foh_declared": owned,
            "warning": None if owned else (
                f"este host se declara '{domain}' y no 'foh': si la APK nativa "
                "esta escuchando en el mismo aparato, los dos procesos bindean "
                "6454/5568/7000 con SO_REUSEADDR y el reparto de paquetes queda "
                "indefinido. Declarar XIO_HOST_DOMAIN=foh, o dejar la escucha a "
                "la APK."),
        }

    def _api_status(self):
        from flask import jsonify
        window = int(self._cfg("active_window"))
        audio = dict(self._audio)
        if audio.get("last_seen"):
            audio["age"] = round(time.time() - audio["last_seen"], 1)
        else:
            audio["age"] = None
        audio.pop("last_seen", None)
        return jsonify({
            "domain": "vj_foh",
            "host_domain": self._host_domain(),
            "port_ownership": self._port_ownership(),
            "channels": {k: c.snapshot(window) for k, c in self._channels.items()},
            "timecode": self._tc_state(),
            "sacn_mode": self._sacn_mode,
            "sacn_interface": self._sacn_interface,
            "audio": audio,
            "setlist": self._setlist_view(),
            "context": self._foh_context_current,
            "battery": self._battery(),
            "active_window": window,
            "log_file": self._log_path(),
            "log_dir": self._log_dir_real,
        })

    def _api_panel(self):
        from flask import Response
        return Response(_PANEL_HTML, mimetype="text/html")

    def _api_registro(self):
        """GET /registro[?date=YYYYMMDD] -- registro del dia legible, mobile-first."""
        from flask import Response
        return Response(_REGISTRO_HTML, mimetype="text/html")

    def _api_view(self):
        """Serve the self-contained FOH/ISKVW hub used by the native client."""
        from flask import Response, send_file
        path = os.path.join(os.path.dirname(__file__), "static", "hub.html")
        if not os.path.isfile(path):
            return Response("hub FOH no desplegado", status=404, mimetype="text/plain")
        return send_file(path, mimetype="text/html", conditional=True)

    def _api_raider(self):
        """Serve the FOH/ISKVW RAIDER without exposing RD surfaces."""
        from flask import send_file
        path = os.path.join(os.path.dirname(__file__), "static", "raider.html")
        if not os.path.isfile(path):
            return Response("RAIDER FOH no desplegado", status=404, mimetype="text/plain")
        return send_file(path, mimetype="text/html", conditional=True)

    def _api_ingest(self):
        """Accept throttled signal records forwarded by the native FOH client."""
        from flask import jsonify, request
        data = request.get_json(silent=True) or {}
        if any(key in data for key in ("eventRef", "rdEventRef", "rd_event_ref")):
            return jsonify({"ok": False, "domain": "vj_foh",
                            "error": "FOH usa eventKey; no acepta identidad RD eventRef"}), 422
        protocol = str(data.get("protocol") or "").strip()
        detail = str(data.get("detail") or "").strip()
        event_key = str(data.get("eventKey") or "").strip()
        if protocol not in ("Art-Net", "sACN", "OSC / TC") or not detail:
            return jsonify({"ok": False, "error": "protocol y detail son obligatorios"}), 400
        if event_key and not any(e.get("eventKey") == event_key
                                 for e in self._foh_context_catalog.get("events", [])):
            return jsonify({"ok": False, "error": "eventKey no existe en el catalogo VJ/FOH"}), 409
        if protocol == "OSC / TC" and detail.startswith("timecode="):
            self._record_tc_value(detail.split("=", 1)[1])
        else:
            channel_name = {"Art-Net": "artnet", "sACN": "sacn", "OSC / TC": "osc"}[protocol]
            self._channels[channel_name].hit(f"APK {detail}")
        self._log_event("app_signal", {
            "source": "xio_foh_apk", "protocol": protocol, "detail": detail,
        }, event_key or None)
        return jsonify({"ok": True, "domain": "vj_foh", "source": "xio_foh_apk",
                        "eventKey": event_key or (self._foh_context_current or {}).get("eventKey")})

    def _api_summary(self):
        """Return a read-only summary of persisted FOH evidence for one event."""
        from flask import jsonify, request, send_file
        event_key = str(request.args.get("eventKey") or "").strip()
        if not event_key:
            path = os.path.join(os.path.dirname(__file__), "static", "resumen.html")
            if not os.path.isfile(path):
                return jsonify({"ok": False, "domain": "vj_foh",
                                "error": "resumen FOH no disponible"}), 404
            return send_file(path, mimetype="text/html", conditional=True)
        selected = next((dict(e) for e in self._foh_context_catalog.get("events", [])
                         if e.get("eventKey") == event_key), None)
        if selected is None:
            return jsonify({"ok": False, "domain": "vj_foh",
                            "error": "eventKey no existe en el catalogo VJ/FOH"}), 409
        rows = []
        try:
            files = sorted(f for f in os.listdir(self._log_dir_real)
                           if f.startswith("show_") and f.endswith(".jsonl"))
        except Exception:
            files = []
        for filename in files:
            try:
                with open(os.path.join(self._log_dir_real, filename), encoding="utf-8") as handle:
                    for line in handle:
                        try:
                            row = json.loads(line)
                        except (TypeError, ValueError):
                            continue
                        if isinstance(row, dict) and row.get("fohEventKey") == event_key:
                            rows.append(row)
            except OSError:
                continue
        rows.sort(key=lambda row: str(row.get("ts") or ""))
        by_type = {}
        dates = set()
        for row in rows:
            by_type[str(row.get("tipo") or "sin_tipo")] = by_type.get(str(row.get("tipo") or "sin_tipo"), 0) + 1
            timestamp = str(row.get("ts") or "")
            if len(timestamp) >= 10:
                dates.add(timestamp[:10])
        return jsonify({"ok": True, "domain": "vj_foh", "eventKey": event_key,
                        "context": selected, "summary": {
                            "total": len(rows), "signalTypes": len(by_type),
                            "byType": by_type, "dates": sorted(dates),
                            "firstTs": rows[0].get("ts") if rows else None,
                            "lastTs": rows[-1].get("ts") if rows else None,
                        }, "rows": rows[-200:], "readOnly": True,
                        "interpretation": "descriptive_signal_counts_only"})

    def _api_context_get(self):
        from flask import jsonify
        return jsonify(self._foh_context_view())

    def _api_context_page(self):
        from flask import Response
        return Response(_CONTEXT_HTML, mimetype="text/html")

    def _api_mapping(self):
        """Serve the existing self-contained Mapping LED tool offline."""
        from flask import Response, send_file
        path = os.path.join(os.path.dirname(__file__), "static", "mapping.html")
        if not os.path.isfile(path):
            return Response("Mapping LED no disponible en este despliegue", status=404,
                            mimetype="text/plain")
        return send_file(path, mimetype="text/html", conditional=True)

    def _api_context_post(self):
        """Select or clear the exact VJ/FOH show context."""
        from flask import request, jsonify
        data = request.get_json(silent=True) or {}
        if data.get("clear"):
            previous = self._foh_context_current
            self._foh_context_current = None
            self._save_foh_context()
            self._log_event("foh_context_cleared", {
                "previousFohEventKey": (previous or {}).get("eventKey")
            })
            return jsonify(self._foh_context_view())
        key = str(data.get("eventKey") or "").strip()
        if not key:
            return jsonify({"ok": False, "domain": "vj_foh",
                            "error": "eventKey es obligatorio; no se crea un evento implicito"}), 400
        selected = next((dict(e) for e in self._foh_context_catalog.get("events", [])
                         if e.get("eventKey") == key), None)
        if selected is None:
            return jsonify({"ok": False, "domain": "vj_foh",
                            "error": "eventKey no existe en el catalogo VJ/FOH"}), 409
        self._foh_context_current = selected
        self._save_foh_context()
        self._log_event("foh_context_selected", {
            "fohEventKey": selected.get("eventKey"),
            "producerSlug": selected.get("producerSlug"),
            "dateIso": selected.get("dateIso"),
            "venueName": selected.get("venueName"),
        })
        binding = self._bind_unowned_setlist_to_context(selected)
        return jsonify({**self._foh_context_view(), "setlistBinding": binding})

    def _api_mark(self):
        """Label the block that is running, while it is running.

        Es escritura, pero al propio registro del plugin y nada mas: no toca el
        rig, no manda un paquete y no cambia el setlist. Queda en la misma
        familia inocua que `next`, no en DANGEROUS_ENDPOINTS.
        """
        from flask import request, jsonify
        data = request.get_json(silent=True) or {}
        clase = str(data.get("clase") or "").strip().lower()
        if clase not in MARK_CLASSES:
            return jsonify({
                "ok": False, "domain": "vj_foh",
                "error": "clase debe ser una de: " + ", ".join(MARK_CLASSES),
            }), 400
        songs = self._setlist.get("songs") or []
        index = self._setlist.get("index", -1)
        current = songs[index] if 0 <= index < len(songs) else None
        detalle = {
            "clase": clase,
            "texto": " ".join(str(data.get("texto") or "").split())[:280],
            # Lo que el setlist estaba mostrando. Es contexto, no una
            # afirmacion de que la marca pertenezca a ese tema.
            "tema_en_pantalla": current,
            "tc_estado": self._tc_state()["state"],
        }
        self._log_event("marca", detalle)
        return jsonify({"ok": True, "domain": "vj_foh", "marca": detalle,
                        "tc": self._tc_current()})

    def _api_manifest(self):
        """PWA manifest: 'Agregar a pantalla de inicio' abre el panel fullscreen
        como app (sin APK). Icono = emoji en SVG data-uri, cero assets externos."""
        from flask import Response
        icon = ("data:image/svg+xml,"
                "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E"
                "%3Crect width='100' height='100' rx='20' fill='%2307090d'/%3E"
                "%3Ctext x='50' y='62' font-size='52' text-anchor='middle'%3E%F0%9F%8E%9A%3C/text%3E"
                "%3C/svg%3E")
        body = json.dumps({
            "name": "FOH xio",
            "short_name": "FOH",
            "display": "fullscreen",
            "orientation": "portrait",
            "start_url": "panel",
            "scope": "./",
            "background_color": "#07090d",
            "theme_color": "#07090d",
            "icons": [{"src": icon, "sizes": "any", "type": "image/svg+xml"}],
        })
        return Response(body, mimetype="application/manifest+json")

    def _api_events(self):
        from flask import request, jsonify
        limit = max(1, min(int(request.args.get("limit", 20)), 200))
        return jsonify(self._events[-limit:])

    # setlist
    @staticmethod
    def _norm_durations(raw, n):
        """Lista de duraciones alineada a n temas: float>0 seg, o None (sin
        visual). Rellena con None y recorta a n."""
        out = []
        if isinstance(raw, list):
            for v in raw:
                try:
                    f = float(v)
                    out.append(f if f > 0 else None)
                except (TypeError, ValueError):
                    out.append(None)
        return out[:n] + [None] * (n - len(out))

    def _song_name(self, linea):
        """Nombre del tema sin el prefijo 'HH:MM:SS:FF  ' (pal titulo grande)."""
        if not linea:
            return linea
        parts = linea.split(None, 1)
        if (len(parts) == 2 and ":" in parts[0]
                and self._tc_str_a_segundos(parts[0], int(self._cfg("tc_fps"))) is not None):
            return parts[1]
        return linea

    def _setlist_view(self):
        songs = self._setlist["songs"]
        durs = self._setlist.get("durations") or []
        i = self._setlist["index"]
        fps = int(self._cfg("tc_fps"))
        cur = songs[i] if 0 <= i < len(songs) else None
        nxt = songs[i + 1] if 0 <= i + 1 < len(songs) else None
        start_sec = None
        if cur is not None:
            p = cur.split(None, 1)
            if p:
                start_sec = self._tc_str_a_segundos(p[0], fps)
        return {
            "songs": songs,
            "index": i,
            "current": cur,
            "current_name": self._song_name(cur) if cur else None,
            "next": nxt,
            "next_name": self._song_name(nxt) if nxt else None,
            "start_sec": start_sec,
            "dur": durs[i] if 0 <= i < len(durs) else None,
            "total": len(songs),
            "loaded_at": self._setlist["loaded_at"],
            "advanced_at": self._setlist["advanced_at"],
            "fohEventKey": self._setlist.get("fohEventKey"),
            "context_match": bool(
                self._setlist.get("fohEventKey")
                and self._setlist.get("fohEventKey") == (self._foh_context_current or {}).get("eventKey")
            ),
        }

    def _api_setlist_get(self):
        from flask import jsonify
        return jsonify(self._setlist_view())

    def _api_setlist_post(self):
        """POST {"text": "tema1\\ntema2"} o {"songs": [...]} + opcional
        "durations": [...] (seg o null, alineadas por indice). Reinicia al tema 0."""
        from flask import request, jsonify
        data = request.get_json(silent=True) or {}
        if isinstance(data.get("songs"), list):
            songs = [str(s).strip() for s in data["songs"] if str(s).strip()]
        else:
            text = data.get("text") or request.get_data(as_text=True) or ""
            songs = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if not songs:
            return jsonify({"ok": False, "error": "setlist vacia: manda 'text' (lineas) o 'songs' (lista)"}), 400
        durations = self._norm_durations(data.get("durations"), len(songs))
        self._setlist = {"songs": songs, "durations": durations, "index": 0,
                         "loaded_at": datetime.now().isoformat(timespec="seconds"),
                         "advanced_at": None,
                         "fohEventKey": (self._foh_context_current or {}).get("eventKey")}
        self._tc_song_index = -1  # re-dispara la auto-deteccion por TC
        self._save_setlist()
        self._log_event("setlist_next", {"accion": "cargada", "temas": len(songs), "actual": songs[0]})
        return jsonify({"ok": True, **self._setlist_view()})

    def _api_next(self):
        from flask import jsonify
        songs = self._setlist["songs"]
        if not songs:
            return jsonify({"ok": False, "error": "sin setlist cargada"}), 400
        if (self._setlist.get("fohEventKey")
                and self._setlist.get("fohEventKey") != (self._foh_context_current or {}).get("eventKey")):
            return jsonify({"ok": False, "domain": "vj_foh",
                            "error": "setlist ligado a otro fohEventKey; selecciona el evento correcto"}), 409
        if self._setlist["index"] < len(songs) - 1:
            self._setlist["index"] += 1
        self._setlist["advanced_at"] = datetime.now().isoformat(timespec="seconds")
        cur = songs[self._setlist["index"]]
        self._save_setlist()
        self._log_event("setlist_next", {"actual": cur, "n": self._setlist["index"] + 1,
                                         "de": len(songs)})
        return jsonify({"ok": True, **self._setlist_view()})

    def _api_prev(self):
        from flask import jsonify
        if not self._setlist["songs"]:
            return jsonify({"ok": False, "error": "sin setlist cargada"}), 400
        if (self._setlist.get("fohEventKey")
                and self._setlist.get("fohEventKey") != (self._foh_context_current or {}).get("eventKey")):
            return jsonify({"ok": False, "domain": "vj_foh",
                            "error": "setlist ligado a otro fohEventKey; selecciona el evento correcto"}), 409
        if self._setlist["index"] > 0:
            self._setlist["index"] -= 1
        cur = self._setlist["songs"][self._setlist["index"]]
        self._save_setlist()
        self._log_event("setlist_next", {"accion": "prev", "actual": cur})
        return jsonify({"ok": True, **self._setlist_view()})

    # log download
    def _api_logs(self):
        from flask import jsonify
        try:
            files = sorted(f for f in os.listdir(self._log_dir_real)
                           if f.startswith("show_") and f.endswith(".jsonl"))
        except Exception:
            files = []
        return jsonify({"dir": self._log_dir_real, "files": files})

    def _api_log(self):
        """GET /log[?date=YYYYMMDD] -> descarga el JSONL del dia (pa analisis post-show)."""
        from flask import request, jsonify, Response
        date = request.args.get("date", datetime.now().strftime("%Y%m%d"))
        if not (len(date) == 8 and date.isdigit()):
            return jsonify({"ok": False, "error": "date debe ser YYYYMMDD"}), 400
        path = self._log_path(date)
        if not os.path.exists(path):
            return jsonify({"ok": False, "error": f"no hay log pa {date}", "dir": self._log_dir_real}), 404
        with open(path, "r", encoding="utf-8") as f:
            body = f.read()
        return Response(body, mimetype="application/x-ndjson",
                        headers={"Content-Disposition": f"attachment; filename=show_{date}.jsonl"})

    # config
    def _api_get_config(self):
        from flask import jsonify
        return jsonify({k: self._cfg(k) for k in self.DEFAULTS})

    def _api_set_config(self):
        """Nota: cambiar puertos requiere reiniciar el server (los binds son de carga)."""
        from flask import request, jsonify
        data = request.get_json(force=True) or {}
        changed = {}
        for k in self.DEFAULTS:
            if k not in data:
                continue
            v = data[k]
            if k in ("artnet_port", "sacn_port", "osc_port", "active_window",
                     "audio_chunk_seconds", "heartbeat_seconds", "battery_delta"):
                v = int(v)
            elif k in ("audio_threshold_db", "tc_freeze_seconds"):
                v = float(v)
            elif k == "tc_address":
                v = str(v)
            elif k == "audio_enabled":
                v = bool(v)
            self.set_config(k, v)
            changed[k] = v
        return jsonify({"ok": True, "changed": changed,
                        "nota": "puertos/audio aplican al reiniciar el server"})


plugin_class = FohMonitorPlugin
