# RD NODO — arquitectura operativa del stand

Este documento define el sistema que se debe operar. No es una propuesta de
interfaz.

## Decisión central

RD NODO tendrá dos planos separados:

```text
                 preparación segura
 MAK / Windows ──────────────────────────────┐
     rd_nodo_build_pack.py                   │
     lee rd.db en modo sólo lectura          │
                                               ▼
                                  public_pack.json revisado
                                               │ USB / adb / scp
                                               ▼
┌──────────────────── XIO / Xiaomi ────────────────────┐
│                                                        │
│  plano privado: server.py :5000                       │
│  ADB, plugins, control del teléfono                    │
│  bind 127.0.0.1 durante el stand                      │
│                                                        │
│  plano público: rd_nodo_public_server.py :8088        │
│  GET/HEAD, pack curado, estado general                 │
│  sin Flask, ADB, plugins ni SQLite                     │
│                                                        │
│  rd_nodo_admin.py ── escribe state.json localmente    │
└────────────────────────┬──────────────────────────────┘
                         │ hotspot
                         ▼
                 teléfonos de asistentes
```

La consecuencia importante es que el hotspot puede seguir sin aislamiento de
clientes: un teléfono público sólo encuentra el servicio de contenido en 8088.
No se confía en que Android o el router oculten el puerto 5000.

## Hechos que condicionan el diseño

- El hotspot Xiaomi tiene un máximo verificado de 32 clientes.
- La configuración observada no ofrece aislamiento entre clientes.
- El rango del hotspot puede cambiar entre sesiones (`192.168.127.x`,
  `192.168.198.x`, etc.). Por eso no se fija una IP en el contenido.
- El `server.py` actual controla ADB y plugins y escucha en todas las
  interfaces. No debe ser el servidor que se entrega al público.
- `run_server.sh` reconstruye `$HOME/xioserver` y borra su carpeta `data` al
  desplegar. El estado del stand no puede vivir allí.
- `rd.db` contiene tablas de catálogo y trazabilidad de testeo. Una base de
  producción o `rd_datos.db` nunca se monta en el proceso público.

## Capacidad y límites

El límite de 32 es del hotspot, no de HTTP. Para un piloto se reserva un margen
operativo:

| Recurso | Límite operativo | Motivo |
|---|---:|---|
| Clientes Android totales | 32 máximo del equipo | límite físico observado |
| Clientes públicos objetivo | 24 como máximo planificado | deja margen para XIO, equipo y recuperación |
| Peticiones HTTP simultáneas | 16 | evita que un cliente o escaneo consuma la CPU |
| Peticiones por cliente | 60 por minuto, memoria volátil | suficiente para lectura; frena abuso |
| Pack público | 1 MiB | evita convertir el hotspot en distribución de medios |
| Carga | JSON pequeño, sin vídeo ni streaming | el recurso caro es el enlace celular, no la LAN |

El servidor no pretende contar personas ni atribuir consumo a celulares. La
capacidad real se verifica con el estado de clientes de Android antes de abrir;
el límite HTTP protege el servicio, no reemplaza el límite del hotspot.

## Seguridad

### Amenaza real

Con aislamiento desactivado, cualquier cliente puede intentar descubrir otros
equipos y el puerto 5000. Una contraseña del hotspot no convierte esa red en
confiable y CORS tampoco es una frontera de seguridad.

### Controles implementados

1. `rd_nodo_public_server.py` es un proceso independiente de `server.py`.
2. El proceso público no importa Flask, `xiaomi_controller`, plugins, ADB ni
   SQLite.
3. Sólo acepta `GET` y `HEAD` en una lista cerrada de rutas.
4. `POST`, `PUT` y `DELETE` responden `405`; no existe escritura remota.
5. No existe listado de directorios ni resolución de rutas arbitrarias.
6. El plano privado se puede enlazar a `127.0.0.1` activando el modo RD NODO.
7. Las respuestas incluyen `no-store`, `nosniff`, CSP sin recursos externos,
   `no-referrer` y una política de permisos vacía.
8. No se escriben accesos ni IPs de asistentes a disco. El rate limiter sólo
   conserva contadores en memoria y se pierde al reiniciar.
9. `state.json` se escribe con archivo temporal + reemplazo atómico.

### Lo que no se debe hacer

- No abrir `server.py:5000` al hotspot en modo público.
- No poner `rd.db`, `rd_datos.db`, `mak_knowledge.db` ni respaldos bajo la
  carpeta pública.
- No usar la lista de clientes del hotspot para identificar asistentes.
- No añadir formularios, login de asistentes, cookies, analytics o tracking.
- No publicar textos libres desde el hotspot: los avisos deben ser una lista
  aprobada y revisada.

## Base de datos e integración

La integración con RD es una exportación unidireccional y deliberadamente
estrecha:

```text
rd.db (MAK / equipo autorizado, sólo lectura)
       │
       └─ SELECT de reactivos aprobados
              │
              └─ public_pack.json
                     │
                     └─ XIO :8088
```

El exportador sólo lee `reactivos(reactivo, familia, reaccion, hex)`. El pack
no contiene `id`, observaciones, muestras, resultados individuales, eventos,
fuentes, filas de origen, etiquetas crudas ni datos de personas. El servidor
público sólo lee el JSON ya construido.

`rd_datos.db` queda reservado para una futura herramienta privada de registro
con consentimiento explícito; no forma parte del piloto público.

## Estado operativo

El estado que se publica es mínimo:

```json
{
  "schema_version": 1,
  "notice": "normal",
  "updated_at": 0,
  "zones": {
    "info": {"status": "disponible"},
    "test": {"status": "espera"},
    "care": {"status": "pausa"}
  }
}
```

Los únicos estados permitidos son `disponible`, `espera` y `pausa`. El equipo
los cambia localmente en XIO:

```sh
python rd_nodo_admin.py --state-file /sdcard/xio_termux/rd_nodo/state.json \
  zone test espera

python rd_nodo_admin.py --state-file /sdcard/xio_termux/rd_nodo/state.json \
  notice care
```

El servicio público lee ese archivo en cada consulta, así que no requiere
reinicio para reflejar un cambio. Un fallo del archivo vuelve a un estado
seguro por defecto y no expone un traceback ni una ruta local.

## Flujo de despliegue

### Antes del evento, en MAK o Windows

```sh
python xio/new/rd_nodo_build_pack.py \
  --source /ruta/segura/rd.db \
  --output /ruta/rd_nodo/public_pack.json \
  --edition "RD NODO · evento 001"
```

El resultado queda como `pending_review`. Se revisa el JSON y, sólo si RD lo
aprueba para esa edición, se vuelve a generar con `--publish`:

```sh
python xio/new/rd_nodo_build_pack.py \
  --source /ruta/segura/rd.db \
  --output /ruta/rd_nodo/public_pack.json \
  --edition "RD NODO · evento 001" \
  --publish
```

Se copia el pack `ready` como:

```text
/sdcard/xio_termux/rd_nodo/public_pack.json
```

No se copia la base de datos.

### En XIO / Termux

```sh
mkdir -p /sdcard/xio_termux/rd_nodo
touch /sdcard/xio_termux/rd_nodo/enabled
sh /sdcard/xio_termux/run_server.sh
```

El modo habilitado hace dos cosas: enlaza el controlador XIO a `127.0.0.1` y
levanta el plano público en `:8088`. El supervisor existente sigue comprobando
el controlador privado en localhost y el supervisor RD NODO recupera sólo el
proceso público si muere. El pack y el estado viven fuera de
`$HOME/xioserver/data`, por lo que el redeploy no los borra.

La URL pública se obtiene de la IP actual del hotspot, no se incrusta en el
pack:

```text
http://IP-ACTUAL-DE-XIO:8088/
http://IP-ACTUAL-DE-XIO:8088/content/pack.json
http://IP-ACTUAL-DE-XIO:8088/api/state
```

## Criterios de aceptación del piloto

1. Un teléfono público recibe `200` en `/healthz`, `/content/pack.json` y
   `/api/state` sin internet celular.
2. `POST /api/state` devuelve `405`.
3. `GET http://IP-XIO:5000/api/plugins` no es accesible desde el hotspot en
   modo RD NODO.
4. El pack `ready` no contiene `rd.db`, `rd_datos.db`, `observation`, `event_id`,
   `source_row`, `test_id`, nombres de personas ni identificadores internos.
5. Cambiar un estado con `rd_nodo_admin.py` se ve en la siguiente consulta
   pública sin reiniciar el servidor.
6. Borrar o corromper `state.json` no detiene el servicio y devuelve el estado
   seguro por defecto.
7. El servicio no crea un archivo de log con IPs de asistentes.

## Lo que se revisita después del piloto

- Si el número real de clientes supera 24, separar el contenido público en un
  AP dedicado; el teléfono no debe convertirse en infraestructura de sala.
- Si se necesita interacción o consentimiento, crear un plano privado separado
  con retención y responsables definidos; no ampliar este servicio público.
- Si el equipo necesita controlar XIO desde otro dispositivo, usar túnel SSH o
  una red administrativa separada, nunca volver a publicar el puerto 5000.
- Si se quiere QR, generarlo por evento a partir de la IP observada; no poner
  una URL fija dentro del pack porque la subred Android deriva entre sesiones.
