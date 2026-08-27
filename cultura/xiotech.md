# XIO — Plataforma multi-rol para instalaciones artísticas
### Plan de mejora ejecutable por agente · README técnico

> **XIO** = Xiaomi 11 Lite 5G (Snapdragon 778G/780G · Adreno 642 · Android 14 · HyperOS 2 · **sin root**).
> Reutilizado como instrumento de borde: router 5G, servidor de automatización, nodo de señales, sonda de luz y visor 3D.
> Este documento es el hand-off para que otro agente construya/mejore el sistema. Léelo completo antes de ejecutar.

---

## 0. Principio rector (no lo violes al implementar)

**Medir antes de calcular · Observar antes de renderizar.** Cada subsistema es un lazo cerrado guiado por medición, no una secuencia ciega (timecode). Cuando dudes entre "computar más" y "observar primero", observa primero: reduce varianza y costo. Salida = estado sostenido, no eventos sueltos.

---

## 1. Restricciones de hardware — la "teoría de muros"

Antes de proponer cualquier feature, clasifícala contra el muro que choca:

| Muro | Qué es | ¿Root lo cruza? | Rodeo |
|------|--------|-----------------|-------|
| 1 · Hardware ausente | RF de banda fija (SAW/PA/antena atados a su banda), sin SDR interno, sin line-in analógico | ❌ nunca | **USB-OTG** (adopta periférico) |
| 2 · Firmware firmado | Baseband/módem caja negra | ❌ nunca | — |
| 3 · Kernel/driver | Nodo existe pero sin exponer | ⚠️ parcial | root parcial |
| 4 · Sandbox OS | Permisos, SELinux, Doze, no-root | ✅ **único que root derriba** | rediseñar dentro del sandbox |
| 5 · Software | Solo falta código | — | construir |

**Hecho crítico:** en XIO el **root es inalcanzable** — el bootloader está cerrado por Xiaomi (portal de desbloqueo retirado el 30-dic-2025) y Magisk exige bootloader abierto. ⇒ **Diseña TODO para el envelope sin-root.** No propongas nada que dependa de sysfs, ALSA directo, nftables, monitor mode o daemons privilegiados.

**El puente que sí tienes:** USB-C OTG (host) concede permiso de dispositivo a la app sin root → adopta **RTL-SDR/HackRF, interfaz de audio USB (UAC), USB-Ethernet, USB-serial (ESP32)**. Con un hub USB-C **PD** cargas + hosteas simultáneamente.

**Techo real:** presupuesto térmico del 778G (throttling sin refrigeración). No corras SDR-FFT + DSP multicanal + inferencia a la vez sin medir temperatura. Añade ventilador USB si va a operar horas.

---

## 2. Estado actual del repo (artefactos ya producidos en este chat)

| Archivo | Estado | Qué hace |
|---------|--------|----------|
| `soc_controller.py` | ✅ funcional (v0) | Lazo cerrado de carga: ADB lee SoC/temp → conmuta enchufe Tapo/Kasa. Bang-bang + histéresis + guarda térmica. |
| `orchestrator.py` | ✅ funcional (v0) | Show-controller: cues + OSC (TD/Resolume/Max) + Art-Net/DMX (44 Hz, fades) + WoL verificado. |
| `mapa_xio.html` | ✅ | Mapa conceptual interactivo (grafo de fuerzas vanilla, ~65 nodos, citas). |
| `XIO_mapa_artefacto.html` | ✅ | Bundle del mapa vía `web-artifacts-builder` (React+Parcel, HTML único). |

Los `.py` son **v0 probados en lógica pero no en hardware real**. Las mejoras abajo asumen que existen y hay que endurecerlos.

---

## 3. Arquitectura objetivo (módulos)

```
                         ┌─────────────────────────────┐
                         │  XIO (Termux, sin root)      │
                         │  plano de control + cerebro  │
                         └─────────────┬───────────────┘
      ┌───────────┬───────────┬────────┼────────┬───────────┬───────────┐
      ▼           ▼           ▼        ▼        ▼           ▼           ▼
   M1 batería  M2 orquest.  M3 fabric M4 sonda M5 splat   (5G/WiFi     USB-OTG
   (lazo)      (cues/OSC/   (SDR+     (luz/    (viewer    backbone)    hub PD →
               DMX/WoL)     audio)    DMX auto)  WebGL)                 SDR/audio/
                                                                       eth/serial)
```

Backbone de datos = **bus canónico**: medios sobre RTP/AES67, control sobre **OSC/MQTT**, red sincronizada por **PTP (IEEE-1588)** cuando haya multicanal. Topología estrella O(N+M), no malla.

---

## 4. Módulos — spec, stack, tareas, criterios de aceptación

### M1 · Controlador de batería en lazo cerrado  `soc_controller.py`
- **Objetivo:** mantener SoC en banda [45–70%] con guarda térmica para prolongar vida de celda en operación 24/7.
- **Stack:** Python 3.11+, `adb` (platform-tools), `python-kasa`. Sin root.
- **Teoría:** envejecimiento Li-ion calendario (Arrhenius, SoC alto+calor) + ciclo (DoD). Bang-bang con banda muerta = anti-chattering del relé.
- **Tareas de mejora:**
  - [ ] Reemplazar polling ADB por conexión persistente (`adb` TCP keep-alive; reconexión con backoff).
  - [ ] Logging a CSV (`ts, soc, temp, current, plug_state`) para ajustar umbrales con datos reales.
  - [ ] Config externa (YAML/env) para umbrales, IP enchufe, credenciales.
  - [ ] Failsafe: si ADB cae >N ciclos → apagar enchufe (no dejar cargando a ciegas).
  - [ ] Soporte multi-enchufe / multi-teléfono.
- **Aceptación:** corre ≥24 h sin fugas de estado; nunca deja el enchufe ON con temp≥TEMP_MAX; CSV consistente; conmuta ≤1 vez / `MIN_DWELL_SECS`.

### M2 · Orquestador / show-controller  `orchestrator.py`
- **Objetivo:** cerebro de la instalación: cola de cues disparada por OSC/reloj/intervalo → WoL + OSC + DMX simultáneos.
- **Stack:** Python asyncio, `python-osc`, Art-Net inline (UDP crudo, puerto 6454) o `stupidArtnet`, WoL inline. Termux runtime.
- **Persistencia (crítico, sin root):** Termux + **Termux:Boot** + **Termux:API** (instalar desde **F-Droid**, NO Play Store) + `termux-wake-lock` + desactivar optimización de batería. Script de arranque en `~/.termux/boot/`.
- **Teoría:** DMX = estado sostenido a ~44 Hz (Art-Net expira si dejas de emitir); fades mutan el buffer, el emisor nunca para.
- **Tareas de mejora:**
  - [ ] Panel de control HTTP (FastAPI) para disparar cues desde navegador/tablet.
  - [ ] Persistir cue-list en archivo; hot-reload.
  - [ ] OSC bidireccional: recibir feedback de TD/Resolume (estados, no solo triggers).
  - [ ] WoL: verificación de puerto de servicio (no solo ping) antes de lanzar show.
  - [ ] Timeline/cronograma con SMPTE opcional además de reloj de pared.
  - [ ] Test de integración con nodo Art-Net virtual + servidor OSC dummy.
- **Aceptación:** autoarranca tras corte de luz; DMX se sostiene sin parpadeo; un cue coordina WoL+OSC+fade sin bloquear el loop; sobrevive 8 h desatendido.
- **Requisito de red:** WoL exige Ethernet cableado al notebook + WoL habilitado en BIOS/UEFI y NIC del SO (WiFi-WoL es poco fiable).

### M3 · Fabric de señales (visualizador + router)
- **Objetivo:** (a) espectrograma multi-frecuencia de eventos; (b) router/transformador de audio multi-fuente.
- **Stack:**
  - Espectro: **RTL-SDR** (24 MHz–1.7 GHz) o **HackRF** (1 MHz–6 GHz) por USB-OTG. `SoapySDR`/`rtl_sdr` → FFT (numpy/`scipy`) → **STFT/cascada**. Viewer WebGL servido local.
  - Audio: interfaz USB **UAC** → captura multicanal (tap en **line-out de receptores** Hollyland/intercom, NO decodificar RF). Ruteo con matriz de operadores.
  - Protocolos: OSC, MQTT (`paho-mqtt`), Art-Net, MIDI. Sincronía PTP si multicanal.
- **Teoría clave:** **doble ingesta** — SDR para VER (no requiere decodificar; recibir es legal), tap de receptor para TENER audio (ya demodulado). Muro legal: re-emitir en banda licenciada; rodéalo enrutando a IP/cableado/ISM.
- **Tareas:**
  - [ ] PoC SDR: leer espectro, render cascada en `<canvas>`/WebGL, etiquetar bandas (micros UHF / intercom DECT 1.9 GHz / video 5 GHz).
  - [ ] Detección de ocupación de canal (umbral sobre piso de ruido) + alerta de interferencia.
  - [ ] Router de audio: matriz N×M con operadores {ganancia, mezcla, split, delay-align, gate}.
  - [ ] Salida modulación cruzada: nivel de audio → OSC → DMX (une con M2).
  - [ ] Medir latencia por camino; líneas de retardo para coherencia.
- **Aceptación:** cascada estable ≥15 fps con SDR conectado; router rutea ≥4 entradas a ≥2 salidas con delay-align; audio→DMX reacciona <100 ms.
- **Muro de HW:** cámaras/radios internos NO reciben RF ajena (banda fija). SDR USB es obligatorio.

### M4 · Sonda de campo de luz (relighting + automapping DMX)
- **Objetivo:** cámaras como fotómetros → (forward) relightear visuales con la luz real; (inverse) automapear el rig DMX sin layout.
- **Stack:** Camera2 **RAW/DNG** (exposición/ISO/WB fijos, linealizar gamma), OpenCV, numpy. IMU vía Termux:API o app. Códigos Hadamard para multiplexado. Salida DMX vía M2.
- **Teoría:** la ecuación de render corre en dos sentidos desde la sonda.
  - **Forward:** luz incidente medida (coef. SH) → shader → normal map "cobra vida".
  - **Inverse:** transporte lineal `m = T·d`; actúa base de canales DMX, estima matriz de transporte `T` columna a columna. `T` = layout aprendido. Multiplexado Hadamard para SNR; triangulación multi-pose para posición 3D.
- **Variables emergentes a explotar:**
  - [ ] **Flicker-ID por rolling shutter:** códigos de parpadeo PWM únicos → ID de todos los fixtures de una vez (colapsa el sondeo).
  - [ ] Ocupación por oclusión (misma medición = sensor de presencia).
  - [ ] Inferencia de haz/gobo desde la caída sobre superficies.
- **Muro:** **metamerismo RGB** (3 bandas → espectros distintos colapsan). Mitigar con calibración por fixture; no se elimina.
- **Prerrequisito NO negociable:** **calibración radiométrica** (RAW + AE/ISO/WB bloqueados + linealización). Sin esto los números son basura.
- **Aceptación:** con AE bloqueado, valor de píxel ∝ radiancia (curva verificada); automap recupera dirección+color de ≥90% de fixtures en escena de prueba; lazo de refinamiento (medir→inferir→predecir→comparar) converge.
- **Nota:** cámaras frontal+trasera simultáneas dependen del HAL; en 778G quizá haya que **multiplexar en el tiempo** (alternar). Verificar Camera2 concurrent-camera support.

### M5 · Pipeline / visor Gaussian Splatting (.ply/.spz)
- **Objetivo:** capturar/renderizar radiance fields como material de instalación; splats reactivos vía OSC.
- **Stack:**
  - Entrenar (**offload**, NO en XIO): COLMAP + `gsplat`/nerfstudio/Inria 3DGS en GPU CUDA (notebook/nube).
  - Formatos: **PLY** maestro (lossless) → **SPZ** (Niantic, ~10× lossy) para entrega. glTF como bus canónico (extensión 3DGS, 2025).
  - Render en XIO: **visor WebGL/WebGPU** en navegador (Adreno), carga .ply/.spz, cuentas de splats **moderadas**.
- **Teoría:** 3DGS explícito (vs NeRF implícito) → rasterizable y editable. Atributos: pos, escala, quaternión, opacidad, SH. Cuello de botella móvil = **sort por profundidad** por frame. SH grado 0–1 en móvil (precisión vs tiempo real).
- **Tareas:**
  - [ ] Script de captura→entrenamiento reproducible (offload) que exporte PLY maestro + SPZ.
  - [ ] Visor WebGL self-contained; medir splats máx a ≥30 fps en XIO.
  - [ ] Hook OSC → modular opacidad/jitter/color SH en vivo (une con M2/M3/M4).
  - [ ] (Investigar) splats *relightables* para alimentar con luz de M4.
- **Aceptación:** visor corre en navegador de XIO con escena SPZ de prueba a ≥30 fps; modulación OSC visible en <100 ms.

### M6 · Mapa conceptual (documentación viva) — ✅ hecho
- Bundle React (`web-artifacts-builder`). Mejoras opcionales: nodo de bibliografía, export PNG, modo presentación por hilos.

---

## 5. Entorno de build — GOTCHAS del sandbox (léelo o perderás tiempo)

- **npm/pnpm 403 en el sandbox:** `registry.npmjs.org` está en `no_proxy`, así que npm lo intenta **directo** y el proxy autenticado no inyecta credenciales → `403 Forbidden`. **Fix:** exportar `no_proxy="" NO_PROXY="" npm_config_noproxy=""` antes de cualquier install para forzar ruteo por el proxy `https_proxy=http://127.0.0.1:44167`.
- **web-artifacts-builder** (React+Parcel → HTML único):
  1. `bash /root/.claude/skills/web-artifacts-builder/scripts/init-artifact.sh <proj>` (con el fix de proxy).
  2. Editar `src/App.tsx`. Para reusar HTML ya probado sin re-portar a React: incrustar como `<iframe sandbox="allow-scripts" src="data:text/html;base64,...">` (base64 inline en un `const`).
  3. **Quitar** la línea `favicon.svg` de `index.html` (Parcel falla al resolverla).
  4. `bash scripts/bundle-artifact.sh` (con fix de proxy) → `bundle.html`.
  5. Verificar con Playwright (`executablePath: /opt/pw-browsers/chromium`) antes de entregar.
- **Playwright/Chromium** preinstalado en `/opt/pw-browsers/chromium`. NO correr `playwright install`.
- **Python:** `pip install --break-system-packages`.
- **Artefactos persistentes de galería** (`mcp__remote-devices__create_artifact`) NO están disponibles en sesiones sin puente de escritorio; entregar vía render HTML es la vía válida aquí.

---

## 6. Orden de ejecución sugerido (dependencias)

1. **M1** (independiente, ya casi listo) → endurecer + logging. *Bajo riesgo, alto valor 24/7.*
2. **M2** (independiente) → persistencia Termux:Boot + panel HTTP. *Es la columna; todo lo demás emite hacia aquí.*
3. **M3-SDR-viz** (necesita RTL-SDR físico) → PoC espectro. *Verificar HW disponible antes.*
4. **M4** (necesita calibración radiométrica primero) → forward relighting antes que inverse automap.
5. **M5** (necesita GPU de offload) → pipeline + visor.
6. **M3-router** y **modulación cruzada** (une M3↔M4↔M5 vía M2) al final.

Regla: **M2 es el bus.** Implementa su capa OSC/DMX estable antes de M3/M4/M5, porque todos modulan a través de ella.

---

## 7. Decisiones abiertas / riesgos (resolver con el humano)

- HW disponible: ¿RTL-SDR o HackRF? ¿interfaz de audio USB multicanal? ¿hub USB-C PD? (bloquea M3/M4).
- ¿Controlador de M1/M2 corre en XIO (Termux) o en una Raspberry/PC externa como broker? (Termux es más frágil ante Doze).
- Marca de enchufe inteligente (protocolo `python-kasa` vs Tapo cloud vs local).
- Cámaras concurrentes en 778G: confirmar soporte o asumir time-multiplex (afecta M4).
- Presupuesto térmico: definir qué corre on-device vs offload bajo carga sostenida.

---

## 8. Verificación global (antes de dar por bueno cualquier módulo)

- [ ] Corre el tiempo objetivo desatendido sin fuga de estado ni crash.
- [ ] Respeta el principio: mide/observa antes de actuar (nada de lazo abierto ciego).
- [ ] Salidas sostenidas (DMX/red) no expiran.
- [ ] Degradación graceful si un sensor/actuador cae (failsafe explícito, logueado).
- [ ] Sin dependencia oculta de root.
- [ ] Test reproducible (dummy OSC/Art-Net/SDR mock donde no haya HW).
```
