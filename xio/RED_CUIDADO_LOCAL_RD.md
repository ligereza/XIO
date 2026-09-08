# RD NODO — Red Local de Cuidado

## Propuesta para Reduciendo Daño

**RD NODO** convierte el stand en una infraestructura local de cuidado. No es
"Wi-Fi para el público" ni otra app aislada: es una red que sostiene tres
espacios físicos que ya existen en el trabajo de RD —información, testeo y
contención/descanso— incluso cuando el evento no tiene cobertura o Internet
estable.

La red sirve contenido oficial, orienta a las personas dentro del stand y
permite al equipo registrar únicamente datos de campo anonimizados. La
atención sigue siendo humana; la tecnología disminuye fricción, ordena el
espacio y devuelve evidencia útil para mejorar el siguiente evento.

```
                     ┌─────────────────────────────────┐
                     │          RD NODO (offline)       │
                     │  guía, mapa, turnos, contenidos  │
                     └───────────────┬─────────────────┘
                                     │
        ┌────────────────────────────┼────────────────────────────┐
        │                            │                            │
  INFORMACIÓN                   TESTEO                    DESCANSO / CONTENCIÓN
  cómo funciona                 acompañamiento             espacio de pausa,
  el stand, límites             y registro técnico          escucha y derivación
  del testeo                    anónimo                     humana
```

## La experiencia para una persona

1. Ve el cartel **“RD NODO · información y acompañamiento, sin Internet”**.
2. Si quiere, se une a la red local o escanea el QR que se genera para ese
   evento. No hay registro, teléfono, correo, nombre ni inicio de sesión.
3. Encuentra tres puertas claras: **quiero información**, **quiero testear**
   y **necesito un espacio/acompañamiento**.
4. La pantalla le explica qué puede ofrecer cada zona, cuánto está ocupada y
   cómo acercarse. No evalúa a la persona ni promete resultados.
5. La atención sucede con el equipo. Al salir, puede conservar recursos
   descargables o un QR para continuar leyendo después; el stand no conserva
   su identidad ni el historial de navegación.

El portal no reemplaza una conversación, el criterio del equipo ni una
derivación de salud. Su función es bajar la incertidumbre antes de hablar con
alguien y dar continuidad a información validada después.

## Dos redes, no una sola

XIO ya tiene una arquitectura robusta para shows: una LAN que sigue viva sin
Internet y un teléfono que funciona como hub. Esa idea es valiosa aquí, pero
hay una diferencia crítica: el hotspot actual de Xiaomi no ofrece aislamiento
entre clientes. En un show eso puede ser aceptable para señales de luces; en
un espacio de cuidado no lo es para datos de atención.

Por eso RD NODO separa las funciones:

| Capa | Quién accede | Qué contiene | Qué no puede contener |
|---|---|---|---|
| **Red pública RD NODO** | Asistentes, de manera voluntaria | Guías oficiales, mapa del stand, mensajes de cuidado, recursos descargables, estado general de ocupación | Formularios de atención, resultados individuales, identificación de dispositivos, notas de voluntariado |
| **Nodo operativo privado** | Equipo autorizado, en terminales controlados | Registro anónimo de testeos, conteos por franja horaria, inventario y relevo interno | Datos identificables, navegación pública, gestión desde dispositivos del público |
| **Archivo RD posterior** | Equipo responsable de datos | Agregados revisados y fuentes trazables | Sincronización automática de datos personales ni telemetría cruda |

La conexión entre la red pública y el nodo operativo debe ser **unidireccional
en términos de información**: el público recibe contenido; nunca llega a la
base de datos interna.

## Arquitectura inicial con lo que ya existe

```
                         ┌─────────────────────────────┐
                         │  XIO / Xiaomi               │
                         │  hotspot + portal offline   │
                         │  QR dinámico + monitor UP   │
                         └──────────────┬──────────────┘
                                        │
                   asistentes ─────────┘
                    (solo contenido)

       cable privado                       cable privado
  ┌───────────────────┐               ┌───────────────────┐
  │ Windows, estación │───────────────│ MAK, archivo RD   │
  │ de equipo         │               │ rd.db / rd_datos  │
  └───────────────────┘               └───────────────────┘
         ▲
         │
  voluntariado autorizado
```

La primera versión no necesita Internet para operar. El Xiaomi sirve el
portal público; Windows y MAK quedan unidos por Ethernet y funcionan como la
estación privada del equipo. Si el Internet celular cae, la orientación local,
los recursos y el registro de campo continúan.

El QR debe generarse al inicio de cada jornada a partir de la IP local real de
XIO. El rango del hotspot Android puede cambiar entre eventos, por lo que no
se imprime una IP fija.

## Qué reutiliza de la base existente

MAK ya tiene la base estructurada de RD:

| Fuente | Rol dentro de RD NODO |
|---|---|
| `rd.db` | Catálogo curado de reactivos, familias, reacciones, colores y trazabilidad de eventos. Es de consulta, no de edición desde el stand. |
| `rd_datos.db` | Destino de registro anónimo de campo: testeos, atenciones y encuestas, bajo una política explícita de retención. |
| `testeo_observaciones_fuente` | Histórico para análisis posterior: permite comparar patrones sin convertir a asistentes en perfiles. |

El sistema debe dejar intacta una regla editorial esencial de RD: un resultado
colorimétrico es **presuntivo**. La interfaz nunca mostrará “seguro”, “puro” o
un diagnóstico automático. Puede explicar límites, mostrar material validado y
acompañar el trabajo de quien atiende.

## Interfaces que vale la pena diseñar

### 1. Portal público: `rd-nodo`

- Mapa simple del stand: dónde están información, testeo y descanso.
- Qué esperar antes de acercarse: tiempos, privacidad y límites del servicio.
- Biblioteca offline de contenido aprobado por RD.
- Señalización de ocupación en tres estados generales: disponible, con espera,
  volver en unos minutos. Nunca se exhiben casos ni situaciones de personas.
- Recursos de salida: contactos y material de cuidado revisados por RD.

### 2. Consola de equipo

- Cambio manual de estado de cada zona.
- Entrega de turno por franja horaria: equipo presente, disponibilidad de
  materiales, alertas operativas sin nombres.
- Formulario de observación de testeo anónimo que mapea a `rd_datos.db`.
- Conteo agregado de atenciones y entregas de información.
- Exportación al cierre para revisión humana; sin sincronización automática a
  Internet.

### 3. Pantalla ambiente

Una pantalla visible, si el montaje la tiene, puede mostrar sólo el mapa,
mensajes rotativos y la disponibilidad general. Es una interfaz de acogida,
no un tablero de incidentes ni una analítica del público.

## Privacidad como forma de cuidado

RD NODO no recopila MAC, IP, identificadores publicitarios, fotos, ubicación,
correo ni nombres de asistentes. Por el mismo motivo, el plugin de XIO que
lista clientes del hotspot no se usaría para personas asistidas: sólo puede
usarse para saber si la infraestructura está arriba, sin persistir quién se
conectó.

Las reglas mínimas son:

- Nada de login, portal cautivo con datos personales o analítica de terceros.
- Nada de resultados individuales en una red compartida.
- Nada de reconocimiento de imagen/color automatizado como decisión de salud.
- Registros de campo con el mínimo necesario y sin vínculo a una identidad.
- Retención, responsables de acceso y borrado definidos antes del piloto.
- El contenido público se firma/revisa antes del evento y queda congelado para
  esa jornada; los cambios se hacen en preparación, no bajo presión durante la
  atención.

## Operación de una jornada

| Momento | Sistema | Equipo |
|---|---|---|
| Antes de abrir | Levanta hotspot, portal offline y QR; prueba que Windows↔MAK por cable responde. | Revisa contenido, responsables, stock y protocolo de derivación. |
| Durante | Mantiene la LAN aunque falte Internet; muestra estado público y guarda sólo observaciones anónimas en la estación privada. | Actualiza disponibilidad y realiza la atención. |
| Cambio de turno | Muestra relevo de zona y faltantes operativos sin nombres de asistentes. | Confirma inventario, carga y continuidad humana. |
| Cierre | Genera exportación local y un resumen agregado. | Revisa, corrige si corresponde, decide qué se incorpora al archivo RD. |

## Piloto en tres etapas

### Etapa 0 — Un evento, sin tocar datos sensibles

Portal local offline con mapa, biblioteca y QR dinámico. El equipo usa la
estación actual como siempre. Se mide únicamente: disponibilidad del portal,
cantidad de aperturas agregadas si se decide contarlas y observación
cualitativa del equipo.

### Etapa 1 — Operación anónima

Agregar consola privada para conteos por turno y registros anónimos de testeo,
exportados a `rd_datos.db` al final de la jornada. Evaluar si ayuda a reducir
duplicación, confusión de turnos o pérdida de observaciones.

### Etapa 2 — Red de estaciones

Sólo después de validar el piloto: añadir terminales de equipo y, si se
necesita Wi-Fi para ellas, un punto de acceso que permita aislamiento de
clientes. No se habilita acceso de equipo sensible sobre el hotspot público de
XIO mientras éste no tenga esa propiedad.

## Decisión que se le pide a la directiva

Autorizar un piloto de RD NODO como **infraestructura de cuidado offline**,
con un responsable de contenido y uno de datos. El éxito no se mide por
personas “capturadas” ni por descargas: se mide por si el stand se vuelve más
legible, el equipo puede sostener mejor los relevos y RD obtiene evidencia
agregada útil sin traicionar la confidencialidad de quienes se acercan.

## Límites explícitos

- RD NODO no sustituye atención presencial, emergencia médica ni decisiones
  del equipo.
- No conecta el público a servicios internos de MAK ni expone `rd.db` en la
  red abierta.
- No requiere ni promete conectividad celular.
- No automatiza interpretación química ni toma decisiones sobre consumo.
- La incorporación de cualquier dato nuevo a la base de RD se hace después de
  revisión humana.
