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
import shutil
import socket
import struct
import subprocess
import threading
import time
from datetime import datetime

_ARTNET_HEADER = b"Art-Net\x00"
_ACN_PID = b"ASC-E1.17\x00\x00\x00"

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
.feed{flex:1;overflow-y:auto;background:#0d1016;border:1px solid #1c2130;border-radius:12px;padding:8px}
.ev{font-size:13px;padding:5px 8px;border-left:3px solid #333;margin-bottom:4px;background:#12151d;border-radius:0 8px 8px 0}
.ev .t{color:#6b7280;font-size:11px;margin-right:6px}
.e-on{border-color:#4ade80}.e-off{border-color:#f87171}.e-set{border-color:#60a5fa}.e-au{border-color:#fbbf24}
.hot{color:#f87171;font-weight:800}
</style></head><body>
<div class=tiles id=tiles></div>
<div class="now tc-na" id=nowbox>
 <div class=nowtc id=tcval>--:--:--:--</div>
 <div class=nowlbl id=tclbl>TIMECODE</div>
 <div class=title id=cur>--</div>
 <div class=bar id=barwrap><i id=barfill></i><span class=pct id=barpct></span></div>
 <div class=nxt id=nx></div>
</div>
<div class=row><span id=batt></span><a href=registro style="color:#60a5fa;font-weight:800;text-decoration:none;padding:6px 10px">REGISTRO &#9776;</a><span id=sub>...</span></div>
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
tick();setInterval(tick,1000);
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

    def hit(self, info=""):
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
        # Timecode: canal propio, excluido del canal osc/VISUAL.
        self._tc = {"value": None, "last_seen": 0.0, "last_change": 0.0,
                    "total": 0, "state": "sin_senal"}
        self._tc_buckets = {}  # segundo -> count (pps del TC)
        self._tc_song_index = -1  # ultimo tema auto-detectado por TC (evita re-loguear)
        self._audio = {"available": False, "reason": "no evaluado", "level_db": None,
                       "active": False, "last_seen": 0.0}
        self._setlist = {"songs": [], "durations": [], "index": -1,
                         "loaded_at": None, "advanced_at": None}
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

    # ── lifecycle ────────────────────────────────────────────────────
    def on_load(self):
        for k, v in self.DEFAULTS.items():
            if self.get_config(k, None) is None:
                self.set_config(k, v)

        self.register_route("/status", self._api_status, methods=["GET"])
        self.register_route("/panel", self._api_panel, methods=["GET"])
        self.register_route("/registro", self._api_registro, methods=["GET"])
        self.register_route("/manifest.webmanifest", self._api_manifest, methods=["GET"])
        self.register_route("/events", self._api_events, methods=["GET"])
        self.register_route("/setlist", self._api_setlist_get, methods=["GET"])
        self.register_route("/setlist", self._api_setlist_post, methods=["POST"])
        self.register_route("/next", self._api_next, methods=["POST"])
        self.register_route("/prev", self._api_prev, methods=["POST"])
        self.register_route("/log", self._api_log, methods=["GET"])
        self.register_route("/logs", self._api_logs, methods=["GET"])
        self.register_route("/config", self._api_get_config, methods=["GET"])
        self.register_route("/config", self._api_set_config, methods=["POST"])

        self._resolve_log_dir()
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
        d = str(self._cfg("log_dir"))
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
            }
            self.logger.info(f"foh setlist recargado: {len(songs)} temas, index {self._setlist['index']}")
        except FileNotFoundError:
            pass
        except Exception as e:
            self.logger.error(f"foh setlist load failed: {e}")

    def _log_path(self, date_str=None):
        date_str = date_str or datetime.now().strftime("%Y%m%d")
        return os.path.join(self._log_dir_real, f"show_{date_str}.jsonl")

    def _log_event(self, tipo, detalle):
        """Una linea JSON al archivo del dia (rotacion implicita por nombre)."""
        # cada evento lleva el ultimo timecode vigente pa correlacion post-show
        ev = {"ts": datetime.now().isoformat(timespec="seconds"), "tipo": tipo,
              "detalle": detalle, "tc": self._tc_current()}
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

    def _start_sacn(self):
        ch = self._channels["sacn"]
        port = int(self._cfg("sacn_port"))
        try:
            sock = self._bind_udp(port)
        except Exception as e:
            ch.error = f"bind {port} fallo: {e}"
            self.logger.error(f"foh sacn: {ch.error}")
            return
        # join multicast best-effort por universo (239.255.hi.lo). En Android
        # sin MulticastLock esto puede no recibir nada igual: se anota el modo
        # y sACN por UNICAST a la IP del telefono siempre funciona.
        joined = 0
        for u in self._parse_universes(str(self._cfg("sacn_universes"))):
            try:
                grp = socket.inet_aton(f"239.255.{(u >> 8) & 0xFF}.{u & 0xFF}")
                mreq = struct.pack("4s4s", grp, socket.inet_aton("0.0.0.0"))
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
                joined += 1
            except Exception:
                pass
        self._sacn_mode = f"multicast({joined} joins)" if joined else "unicast (join multicast fallo/bloqueado)"
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
                ch.hit(info)

    # parsers: devuelven str info si el paquete es valido, None si no
    @staticmethod
    def _parse_artnet(data):
        if len(data) < 12 or not data.startswith(_ARTNET_HEADER):
            return None
        opcode = data[8] | (data[9] << 8)
        if opcode == 0x5000 and len(data) >= 18:  # OpDmx
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
        info = self._parse_osc(data)
        if isinstance(info, str) and info.startswith(str(self._cfg("tc_address"))):
            self._tc_hit(data)
            return False
        return info

    def _tc_hit(self, data):
        """Registra un paquete de timecode: primer arg string o float."""
        val = self._osc_first_arg(data)
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
            "channels": {k: c.snapshot(window) for k, c in self._channels.items()},
            "timecode": self._tc_state(),
            "sacn_mode": self._sacn_mode,
            "audio": audio,
            "setlist": self._setlist_view(),
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
                         "advanced_at": None}
        self._tc_song_index = -1  # re-dispara la auto-deteccion por TC
        self._save_setlist()
        self._log_event("setlist_next", {"accion": "cargada", "temas": len(songs), "actual": songs[0]})
        return jsonify({"ok": True, **self._setlist_view()})

    def _api_next(self):
        from flask import jsonify
        songs = self._setlist["songs"]
        if not songs:
            return jsonify({"ok": False, "error": "sin setlist cargada"}), 400
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
