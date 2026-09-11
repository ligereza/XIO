# Informe de arquitectura XIO-RD / XIO-FOH / FLUJO — 2026-09-11

## Resumen ejecutivo

Se ordenó y documentó la arquitectura de campo alrededor de un principio simple:
el Xiaomi es actualmente el host de XIO y el hotspot privado es la red de acceso;
FLUJO sigue siendo el Hub de estudio en MAK; RD y FOH son dos superficies separadas
que comparten un solo servidor HTTP XIO en `:5000`.

La fuente preparada y sus gates están cerrados en Windows y MAK. La ejecución real en
el Xiaomi no está cerrada: el teléfono conserva un runtime XIO antiguo, no tiene los
assets actuales ni el snapshot RD y no escucha en `:5000`. No se hizo ninguna escritura,
instalación, reinicio ni activación en el teléfono.

Este documento registra hechos, decisiones, errores, aprendizajes, cambios, límites y
la evidencia que falta. No sustituye la comprobación del runtime físico.

## 1. Autoridad y reglas de continuidad

### Fuentes actuales

- Windows XIO: `C:\IA\XIO`.
- MAK XIO: `/home/mak/XIO`.
- FLUJO vivo en MAK: `/home/mak/flujo`, Hub activo en `:8765`.
- Espejo FLUJO en Windows: `C:\IA\flujo`.
- Base RD canónica para preparar una sesión: `/home/mak/flujo/data/rd.db`.
- Base Windows `C:\IA\flujo\data\rd.db`: copia de trabajo; el gate actual la considera desalineada.
- Memoria durable: `C:\IA\.remember\remember.md`.

El código vivo, el proceso, los listeners, la base inspeccionada y la evidencia fechada
mandan sobre un `.md` antiguo. Los documentos históricos se conservan como historia,
pero no son destinos ni instrucciones operativas si contradicen el estado actual.

### Reglas que se consolidaron

1. Buscar primero productos, consumidores, scripts, bases, sesiones y endpoints existentes.
2. Leer las sesiones más recientes en orden descendente y luego comprobar archivos, procesos,
   dispositivos, endpoints y Git.
3. No duplicar Hub, base de datos, puerto, APK, superficie ni reporte.
4. No borrar ni reemplazar trabajo ajeno sin identificar el alcance.
5. Separar siempre MAK (equipo Linux) de GPT Mini (agente); separar también RD de VJ/FOH.
6. No tratar un documento obsoleto ni un archivo antiguo del teléfono como prueba de release.
7. Mantener nombres, rutas y contratos ASCII cuando sean identificadores o comandos.
8. No escribir, instalar, reiniciar ni activar procesos en el Xiaomi sin autorización explícita.

## 2. Lo que se entendió correctamente

XIO no es solamente una APK: es una función de borde que puede correr en un Xiaomi,
en otro dispositivo conectado al router o, en el futuro, en un equipo que tenga memoria
y ejecute el servidor. El Xiaomi actual comparte datos móviles por hotspot, pero la LAN
del hotspot continúa funcionando aunque no haya señal móvil.

En un evento, el Xiaomi es el host de la información. Los teléfonos, iOS, tablets y
laptops son clientes web que entran a la red privada y consultan la superficie que les
corresponde. Un futuro router sin memoria no elimina la necesidad de un dispositivo host:
uno de los equipos debe ejecutar XIO y conservar el estado.

- **XIO-RD** pertenece a Reduciendo Daño: evento preparado, flyer/productora/venue,
  registro de muestras, fotos, timestamps, resultados y asistencia de campo.
- **XIO-FOH** pertenece al rubro personal VJ/ISKVW: evento de show, artista/cliente,
  venue/layout/rider, setlist, Mapping LED, Resolume, Chataigne, Showkit, OSC, Art-Net,
  sACN, timecode y evidencia de cabina.
- **FLUJO** es el Hub existente y sus fuentes de datos; no se le agregan pestañas nuevas
  para convertirlo en XIO.

## 3. Contrato de hosts, clientes y puertos

| Capa | Ubicación | Contrato |
|---|---|---|
| FLUJO Hub | MAK `:8765` | Hub de estudio y rutas existentes; no es el servidor XIO de campo |
| XIO host | Xiaomi/Termux `:5000` | Un servidor HTTP con dos namespaces; guarda el estado de campo |
| XIO-RD | `/api/plugins/rd_field/*` | PWA/browser; APK RD opcional sólo como cliente |
| XIO-FOH | `/api/plugins/foh_monitor/*` | PWA/browser; no necesita APK |
| Art-Net | UDP `:6454` | Entrada pasiva de FOH |
| sACN | UDP `:5568` | Entrada pasiva/multicast de FOH |
| OSC/timecode | UDP `:7000` | Entrada pasiva de Chataigne/Resolume para FOH |
| Showcontrol | namespace opcional existente | Herramienta activa distinta de las superficies RD/FOH |

No hay cuatro APKs ni cuatro servidores HTTP. Hay dos superficies separadas sobre un
listener XIO común. Los puertos UDP son protocolos de señal, no nuevos servidores web.

`127.0.0.1:8765` sólo describe un acceso local a FLUJO. Nunca debe entregarse como URL
a un cliente del hotspot para RD o FOH. Un cliente del evento necesita la IP actual del
Xiaomi y el puerto `5000`.

## 4. Persistencia y claves de identidad

### RD

`rd_field`:

- lee un snapshot revisado de la base RD canónica del host;
- exige que `eventRef` exista en el bootstrap del host;
- rechaza un `eventRef` desconocido con `409`;
- nunca crea implícitamente un evento;
- persiste muestras y evidencias en el host XIO;
- hace el sync idempotente para que repetir una petición no duplique la muestra.

La UI RD fue corregida: ya no crea eventos operativos locales cuando el host no responde.
En HTTP sólo lista eventos entregados por el host y no permite agregar muestras sin un
evento host-backed. La fixture sintética queda limitada al modo `file://` de desarrollo.

### FOH

`foh_monitor`:

- mantiene su catálogo VJ/FOH separado del `eventRef` de RD;
- exige un `eventKey` exacto del catálogo VJ;
- persiste la selección en `foh_vj_context.json`/estado de logs del host;
- etiqueta la evidencia con `domain: vj_foh` y `fohEventKey`;
- impide que setlist y evidencia de dos fechas del mismo artista se mezclen;
- conserva el monitor OSC/Art-Net/sACN y la herramienta Mapping LED existente.

La relación DrefQuila/venue/layout/setlist se incluyó sólo cuando existía una referencia
explícita en las fuentes. No se inventó un venue o rider a partir del nombre de un artista.

### Seguridad de campo

El límite de acceso de RD y FOH es la contraseña del hotspot privado. No se agregaron
tokens, login ni capas de seguridad innecesarias. La red pública opcional de `showcontrol`
es una decisión distinta y conserva su mecanismo específico cuando se habilita; no se
debe trasladar ese contrato a RD/FOH.

## 5. IP dinámica del Xiaomi

La IP del Xiaomi es estado de sesión. La observación actual fue `10.248.64.39/24`, pero
no es una configuración permanente y no se debe copiar a presets ni scripts.

Se corrigieron los caminos operativos para:

- derivar la dirección, red y broadcast de `wlan1` en tiempo real;
- usar `255.255.255.255` para broadcast de OSC/Art-Net cuando corresponde;
- usar el broadcast de la subred actual como fallback, nunca una subred histórica;
- resolver el host HTTP XIO desde gateways actuales y verificar `/api/plugins` en `:5000`;
- ignorar un `XIO_HOST` viejo si no responde y continuar con el gateway actual;
- usar un opener sin proxy para que Windows no redirija tráfico local del hotspot;
- hacer que el watcher ADB derive la IP actual del teléfono.

Las IP históricas de shows se conservan como evidencia, no como destinos operativos.

## 6. Cambios realizados

### Servidor y despliegue

- `xio/new/server.py`: bind configurable mediante `XIO_BIND_HOST`, datos mediante
  `XIO_DATA_DIR` y listener de campo por defecto en `0.0.0.0:5000`.
- `xio/new/run_server.sh`: overlay limitado a los plugins de campo, preserva la librería
  existente, separa runtime reemplazable de datos durables y exige el snapshot RD.
- `xio/new/pc_reboot_watch.sh`: descubre la IP actual de `wlan1`.
- `xio/actual/server.py`: se alineó el comportamiento de host dinámico.
- `connectivity_supervisor`: expone `hotspot_address`, `hotspot_network` y
  `hotspot_broadcast` y no usa una subred fija como default.

### Superficies

- Se integró `xio/new-plugins/rd_field/` con puente RD portable, PWA, manifest, service
  worker, lectura, bootstrap y sync.
- Se integró `xio/new-plugins/foh_monitor/` con contexto VJ exacto, catálogo, estado,
  Mapping LED, logs y validación de señales existente.
- Se sincronizaron las superficies y sus gates en Windows, MAK XIO y los espejos FLUJO.
- Se mantuvo la APK RD existente como cliente opcional; no se convirtió FOH en APK.

### Show kit y documentos

- `xio/show_kit/discover_xio.py` descubre el host dinámico sin escanear la subred.
- `check_show`, `check_show.bat` y `cargar_setlist.bat` usan el descubrimiento actual.
- Presets activos de Chataigne/Showkit usan broadcast, no una IP del Xiaomi.
- `FACES.md`, `RUNBOOK.md`, `HOTSPOT_SHOW_RUNBOOK.md`, `DIA_DEL_SHOW.md` y README de
  showcontrol fueron alineados con la IP dinámica y la separación de listeners.
- `FACES.md` ahora contiene el contrato vigente de `FLUJO :8765` versus XIO `:5000`,
  separación RD/FOH, puertos de señal y regla de hotspot dinámico.
- `rd_field/README.md` ya no presenta la base Windows desalineada como fuente de campo.

### Android RD

Se conservaron y ajustaron las piezas del cliente Android existente (`MainActivity`,
`FlujoGateway`, `RdFieldDb`, `RdFieldExporter` y `app.js`) para que la APK sea entendida
como cliente opcional de RD. Esto no prueba que la APK sea el servidor ni que su presencia
implique que XIO esté desplegado en el teléfono.

### Memoria y continuidad

`C:\IA\.remember\remember.md` registra la raíz canónica, el estado del teléfono, los
hashes, la regla de IP dinámica, la autoridad de la base RD, los gates y los errores que
no se deben repetir. La memoria es una síntesis de continuidad, no una autoridad superior
a los hechos actuales.

## 7. Artefactos preparados

- Superficies: `C:\IA\work\artifacts\xio-field-surfaces-20260911-tree.zip`
  - SHA-256: `577aa86aafc2b255511468d6f8889bc0312abcbaffe15fd7351b42c39d433ccc`
- Runtime: `C:\IA\work\artifacts\xio-field-runtime-20260911.zip`
  - SHA-256: `150b9ca76352432f8a19546a6567e0dec8761743e1ab41d8728389b8f77632f4`

El runtime contiene el servidor actual y únicamente el overlay `rd_field`,
`foh_monitor` y `connectivity_supervisor`. No contiene bases de datos ni caches Python.

## 8. Evidencia obtenida

| Comprobación | Resultado | Qué demuestra |
|---|---|---|
| Gate IP dinámico Windows | PASS | descubrimiento por gateway, presets broadcast y contrato documental |
| Gate IP dinámico MAK XIO | PASS | el mismo contrato en MAK |
| Gate RD plugin | PASS | namespace, evento exacto, UI host-gated y sync |
| Gate RD bridge | PASS | bootstrap, ingest, lectura e idempotencia aisladas |
| Gate FOH context | PASS | selección exacta, dominio VJ y separación de RD |
| Gate staging MAK | PASS | 37 tablas, 42 referencias de eventos, assets RD/FOH/CONNECTIVITY |
| Gate runtime bundle | PASS | servidor `5000`, overlay exacto, sin DB/cache en el ZIP |
| FLUJO vivo MAK | HTTP 200 | `/home/mak/flujo` continúa sirviendo el Hub en `:8765` |

La prueba que requiere Flask local no se ejecutó porque Flask no está instalado en Windows;
no se instaló ninguna dependencia. Los gates sin Flask cubren el contrato mediante stubs y
el staging de MAK pasó con la base real.

## 9. Estado real del Xiaomi

La inspección fue sólo de lectura mediante ADB y GET HTTP:

- dispositivo `8299e66f`: online;
- `wlan1`: `10.248.64.39/24` en esa sesión;
- `:8765`: servidor estático de FLUJO, no XIO;
- `:5000`: sin listener;
- assets actuales de RD/FOH: ausentes;
- `rd_field/rd.db`: ausente;
- `server.py`, launcher, FOH y connectivity: hashes antiguos y distintos del release;
- resultado autoritativo: `PHONE_RUNTIME=NO-GO`.

Este `NO-GO` es correcto: evita confundir un servidor antiguo en el teléfono con el
release preparado. Falta autorización explícita para copiar el bundle, preparar el snapshot
RD y arrancar XIO en el dispositivo. No se debe afirmar que la arquitectura está validada
en campo mientras ese paso no ocurra.

## 10. Errores y patrones de error detectados

### Confundir puertos y hosts

Se mezcló `127.0.0.1:8765` de FLUJO con XIO `:5000`, y un server visible en el teléfono
parecía suficiente para afirmar que XIO funcionaba. La corrección fue distinguir proceso,
listener, bind, URL local y URL del hotspot, y añadir esa diferencia al gate documental.

### Confiar en archivos viejos

El teléfono tenía un runtime XIO antiguo y `C:\XPEDR\.remember\now.md` conservaba una
dirección de julio. También había documentos que describían subredes como defaults. Se
mantuvieron como historia, se marcaron como supersedidos y se hizo que el gate compare
hashes del teléfono contra la fuente actual.

### IP fija como si fuera identidad

Los presets y herramientas podían romperse al cambiar la IP del hotspot. La IP dejó de
ser configuración persistente: se descubre por sesión, se usa broadcast para señales y
se usa la IP actual sólo para HTTP/diagnóstico.

### Mezclar los dos repositorios de MAK

`/home/mak/XIO` es la fuente de despliegue XIO; `/home/mak/flujo` es el Hub FLUJO vivo.
No son raíces intercambiables y sus bases no se deben fusionar copiando archivos. Se
sincronizaron sólo las piezas de integración necesarias.

### Mezclar RD con FOH

RD usa `eventRef` y la regla del evento preparado. FOH usa `eventKey` VJ y puede tener
otro criterio de selección. El FOH no lee ni escribe `eventRef`; los logs llevan dominio
explícito. La UI RD que todavía mostraba “Crear evento” era una contradicción real y fue
cerrada.

### Usar un staging temporal como autoridad

Una prueba FOH llegó a preferir un archivo temporal y podía ocultar que la fuente real
estaba distinta. Se eliminó ese fallback: los gates leen la implementación efectiva de
`new-plugins` y exigen los assets actuales.

### Empaquetar demasiado

Al reconstruir el runtime se incluyeron por error todos los plugins heredados. El gate lo
rechazó; se rehizo el ZIP con sólo `rd_field`, `foh_monitor` y `connectivity_supervisor`.
Esto evita desplegar herramientas no solicitadas o peligrosas.

### Base incorrecta

La copia Windows de `rd.db` parecía una fuente posible, pero no tenía el esquema/estado
de la base canónica de MAK. Se dejó la autoridad en `/home/mak/flujo/data/rd.db` y el gate
de staging queda como requisito para cualquier snapshot.

### Errores procedurales de comprobación

En una pasada se invocaron dos gates con argumentos incorrectos (`--bundle` y falta de
`--rd-db`); se corrigieron sin alterar datos. La prueba Flask local quedó omitida por
dependencia ausente, no se “pintó” como PASS y se conservaron los gates alternativos.

## 11. Aciertos y mejoras

- Se respetó el límite de no tocar el Xiaomi durante la auditoría.
- Se prefirió evidencia de procesos/listeners/hash sobre inferencias de documentos.
- Se mantuvo una sola capa HTTP XIO con dos namespaces, evitando sobreingeniería.
- Se hizo host-owned la persistencia y se evitó que cada cliente cree eventos.
- Se dejó FOH como web accesible desde iOS, sin obligar a descargar APK.
- Se protegió el trabajo histórico y se sincronizaron las copias operativas.
- Los gates ahora fallan ante IP fija, overlay demasiado amplio, UI RD contradictoria,
  assets ausentes, snapshot RD ausente o runtime telefónico obsoleto.
- La memoria durable conserva no sólo decisiones, sino también el motivo de los fallos.

## 12. Lo que aún no está hecho

1. Copiar el runtime actual al Xiaomi mediante el overlay previsto.
2. Preparar y revisar el snapshot de `/home/mak/flujo/data/rd.db` en el host XIO.
3. Arrancar XIO `:5000` en el Xiaomi.
4. Probar desde un cliente del hotspot la UI RD y FOH con la IP de esa sesión.
5. Probar en un iPhone/iPad real los flujos de navegador, cámara, cache y visualización.
6. Probar en venue señales reales Art-Net, sACN, OSC/timecode y broadcast de la subred.
7. Verificar la reconciliación post-show del snapshot RD hacia FLUJO.

La siguiente acción correcta, cuando exista autorización, es desplegar sin instalar APK ni
reiniciar arbitrariamente: snapshot RD revisado, overlay exacto, arranque del launcher,
gate de runtime y GET de las rutas namespaced desde un cliente del hotspot. Si la IP cambia,
se vuelve a descubrir; no se edita un preset histórico.

## 13. Regla para futuros agentes

Antes de actuar, leer sesiones recientes y Git; después comprobar el estado vivo. Si aparece
un documento contradictorio, comparar fecha, código real, proceso, base y evidencia. Preguntar
en loop: “¿esto ya existe?, ¿hay un consumidor?, ¿hay un script?, ¿hay una base?, ¿qué fuente
es canónica?, ¿estoy mezclando una copia, un producto o un runtime?”. No borrar, duplicar,
instalar ni agregar una capa sólo porque una prueba local resulte más fácil.

**Estado del informe:** escrito desde la fuente Windows XIO y destinado a sincronización
byte a byte con XIO MAK y sus espejos FLUJO. Los estados de Git y los hashes de publicación
se registran después de crear este documento.
