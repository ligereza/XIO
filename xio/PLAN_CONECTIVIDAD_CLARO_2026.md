# Plan de conectividad XIO — Claro Chile, agosto de 2026

## Resumen ejecutivo

El problema no debe tratarse como una sola "señal mala". Hay tres enlaces
distintos:

```text
Claro (radio celular) → Xiaomi/XIO → Wi‑Fi hotspot → Windows → Ethernet → MAK
```

La prioridad es eliminar el enlace Wi‑Fi intermedio, no intentar amplificarlo
a ciegas:

```text
Claro (radio celular) → Xiaomi/XIO por USB → Windows/ICS/QoS → Ethernet → MAK
```

Así el Xiaomi puede ocupar la mejor posición radioeléctrica disponible, el
hotspot 5 GHz deja de ser un posible punto de caída y Windows puede reservar
capacidad para su propio tráfico mientras limita las descargas de MAK. Esto no
mejora por sí solo la cobertura celular: evita que una cobertura celular débil
se mezcle con una segunda falla Wi‑Fi.

## Qué dicen los datos disponibles

### Lectura real del Xiaomi

La captura de Network Survey del 27-08-2026 registró, entre otros estados:

- PLMN Claro `730-03`.
- LTE EARFCN `9610`, PCI `326`, ECI `79431`, TAC `50014`.
- Banda baja de 700 MHz (B28), ancho de banda de 10 MHz.
- RSRP aproximadamente `-103 dBm`, RSRQ entre `-12` y `-16 dB`, SNR cercano a
  `0 dB`.
- El teléfono reportó LTE, sin agregación de portadoras y sin disponibilidad
  NR/EN-DC en la lectura actual.
- Se observaron 12 firmas `(EARFCN, PCI)` en total. Son firmas de celdas o
  sectores observados, no 12 torres físicas.

En términos de ingeniería: el teléfono está sobreviviendo con una portadora
de cobertura, pero con poco margen de calidad. No es evidencia suficiente de
throttling del plan.

### Inventario oficial cercano

Consulté la capa pública de elementos de SUBTEL alrededor de la coordenada que
entregó el teléfono, sin guardar aquí la dirección exacta:

- 29 registros de Claro con LTE en un radio de 2 km, correspondientes a 26
  soportes administrativos.
- 10 soportes con registros LTE en 700 MHz.
- 26 registros de Claro en 5G/3500 MHz en ese mismo radio, en 26 soportes.
- El registro 5G más cercano aparece a unos 206 m; el registro Claro de 700 MHz
  más cercano aparece a unos 849 m.

Esto es importante, pero no permite afirmar que el soporte más cercano sea la
célula servidora: el catastro es administrativo, no entrega el azimut real del
sector, la carga instantánea ni una correspondencia pública directa entre el
ECI del teléfono y el soporte.

La base consultada es el [catastro público de SUBTEL](https://licancabur.subtel.gob.cl/server/rest/services/LDT_ELEMENTOS_SERV_PT_1/FeatureServer/0),
y el [Portal de Torres de SUBTEL](https://antenas.subtel.gob.cl/).

### Marco 5G de Claro en Chile

SUBTEL documenta que Claro obtuvo/usa concesiones en la banda de 3,5 GHz; un
decreto de enero de 2026 referencia el bloque de 50 MHz dentro de 3,40–3,60
GHz. SUBTEL también reportó en abril de 2026 que Claro-VTR representaba 18,7 %
del tráfico de datos móviles 5G nacional. Eso confirma que existe un despliegue
5G de Claro, pero no garantiza que el interior de este edificio pueda usarlo.

Fuentes: [Decreto Claro 23 Exento (2026)](https://www.leychile.cl/navegar?idNorma=1221153),
[estadísticas SUBTEL enero de 2026](https://www.subtel.gob.cl/chile-supera-las-10-millones-de-conexiones-5g-y-cuenta-con-el-internet-fijo-mas-barato-de-america-latina/),
y [portal 5G de SUBTEL](https://www.subtel.gob.cl/concursos5g/).

## Hipótesis ordenadas por valor

### 1. El edificio deja pasar 700 MHz pero no deja pasar bien 3,5 GHz

La longitud de onda es aproximadamente 43 cm a 700 MHz y 8,6 cm a 3,5 GHz.
Hormigón armado, mallas metálicas, vigas y múltiples reflexiones penalizan más
la banda alta. Un soporte 5G a 206 m puede existir y aun así ser peor para el
teléfono dentro del departamento que una celda 700 MHz más lejana.

La edad de 1949 no prueba que el edificio fuera construido para radiografías.
Lo técnicamente plausible es estructura densa, metal y geometría interior
desfavorable. NIST documenta que los materiales producen atenuación,
dispersión y variabilidad fuerte dentro de edificios, incluyendo hormigón
armado y rejillas de acero: [NIST sobre materiales](https://www.nist.gov/publications/electromagnetic-signal-attenuation-construction-materials)
y [NIST sobre propagación en edificios](https://www.nist.gov/publications/radio-wave-signal-propagation-large-building-structures-part-1-cw-signal-attenuation).

### 2. El hotspot está usando un canal DFS y puede cambiar de canal

Windows vio el hotspot en canal 36 en una captura anterior y en canal 56 en la
actual. El canal 56 está en el grupo DFS documentado para 5 GHz. DFS permite
que el punto de acceso cambie de frecuencia si detecta una señal protegida; el
efecto para el cliente puede ser pausa, desasociación o cambio de BSSID. No
afirmo que haya ocurrido radar: afirmo que el canal 56 abre una causa concreta
que el registro debe confirmar.

El [documento técnico de Cisco sobre DFS](https://www.cisco.com/en/US/docs/routers/access/wireless/software/guide/RadioChannelDFS.pdf)
enumera explícitamente el canal 56 y describe los cambios de canal y la
desasociación de clientes. Si HyperOS permite elegir canal, la primera opción
sería 36/40/44/48 y ancho de 20/40 MHz. Si no lo permite, USB tethering elimina
por completo esta variable.

### 3. Carga y temperatura del Xiaomi cambian el margen del módem

El hecho de estar cargando no crea mágicamente una interferencia de 4G. Sí
puede elevar la temperatura y cambiar el estado energético del teléfono; eso
puede coincidir con reducción de capacidad, reconfiguración del hotspot o
reselección de radio. Por eso XIO debe registrar temperatura, corriente,
estado de carga y radio en la misma línea temporal. No se debe inferir una
causa a partir de que un aparato eléctrico esté cerca.

### 4. El problema puede ser congestión del sector, no potencia de señal

Una iglesia llena no equivale a "muchos hotspots interfiriendo". Importa cuántos
usuarios Claro/VTR terminan en el mismo sector y cuánto tráfico cursa ese
sector/backhaul. La red móvil puede estar congestionada aunque el RSRP no
cambie.

La propia política pública de Claro contempla medidas de gestión en horarios,
zonas y eventos de congestión, y los umbrales dependen del plan contratado:
[política de gestión de tráfico de Claro](https://www.clarochile.cl/portal/cl/legal-regulatorio/pdf/1523032603600-Archivo.pdf).
Esto no demuestra que tu línea esté limitada; para distinguirlo se necesita
ver si la caída aparece con radio estable, si coincide con la hora punta y si
se repite en varios destinos.

## Arquitectura recomendada sin comprar dispositivos

### Fase A — Cambiar la topología

1. Activar USB tethering del Xiaomi hacia Windows.
2. Mantener el Xiaomi en una posición radioeléctrica estable, separado de la
   superficie metálica y de la parte trasera de la TV/monitores.
3. Desactivar el hotspot Wi‑Fi del Xiaomi durante esta prueba.
4. Compartir la interfaz USB de Windows por Ethernet hacia MAK mediante ICS.
5. Mantener MAK como red cableada; no hacer que Windows y MAK compitan por el
   hotspot 5 GHz.

Esta es la idea central: XIO se convierte en un módem remoto; Windows es el
router y punto de política; MAK es un cliente cableado.

### Fase B — Separar tráfico por función

- Windows: videollamada, navegación, control y tráfico interactivo.
- MAK: descargas y procesos de fondo con un límite local explícito.
- En MAK, usar `tc`/FQ-CoDel o HTB para que sus descargas no llenen la cola de
  subida/bajada.
- En Windows, usar BITS o una política QoS para las aplicaciones de descarga.

Esto no esquiva la gestión de Claro ni enmascara tráfico. Evita que una
descarga local destruya la latencia de todo el enlace.

### Fase C — Elegir la red con evidencia

XIO debe conservar una tabla de estados, no cambiar de 4G a 5G por reflejo:

| Estado observado | Interpretación | Acción preferida |
|---|---|---|
| LTE B28 débil, gateway local sano, 5G no disponible | Cobertura/penetración celular | Mantener LTE; usar USB y posición estable |
| LTE estable, gateway sano, Internet lento en horario repetido | Congestión o política del operador | Limitar MAK; comparar con otro horario y guardar evidencia para Claro |
| BSSID/canal cambia y gateway pierde paquetes | Hotspot Wi‑Fi/DFS | Canal no DFS o USB tethering |
| Radio y gateway sanos, un proceso consume mucho | Contención local | QoS/HTB por equipo o proceso |
| Caída abrupta repetida al superar consumo/umbral | Política del plan | Revisar anexo y ciclo de facturación; no atribuirlo al edificio |

La automatización puede recomendar o notificar una acción. Forzar el modo
preferido 4G/5G desde una app normal de Android no es una capacidad fiable sin
privilegios de operador/root; XIO no debe fingir que ADB puede saltarse esa
restricción.

## Cómo se determina la antena sin inventar una triangulación

El teléfono sí puede entregar celdas servidoras y vecinas: EARFCN, PCI, ECI,
TAC y niveles de señal. No entrega por sí solo el número de torres físicas ni
el azimut de cada sector.

La forma seria de aproximar la infraestructura es:

1. cruzar firmas `(EARFCN, PCI, PLMN)` con el catastro SUBTEL y, como fuente
   secundaria, CellMapper;
2. observar la misma firma desde tres o más posiciones del edificio/barrio;
3. conservar solo soportes que sean compatibles en banda, distancia y
   variación de RSRP/RSRQ;
4. marcar el resultado como candidato, nunca como torre confirmada.

Con un solo punto se puede decir "hay 26 soportes 5G registrados cerca"; no se
puede decir "estás conectado a la antena de 206 m".

## Plan de ejecución

### Entregable 1 — Topología funcional

Probar USB tethering → Windows ICS → Ethernet → MAK. El criterio de éxito es
que MAK navegue con el hotspot Wi‑Fi apagado y que Windows conserve su ruta.

### Entregable 2 — Mapa de radio del propio departamento

Registrar en posiciones fijas: junto a ventana, centro del escritorio y otra
habitación. En cada posición se compara la misma celda/sector, no solo las
barras de señal. El resultado será una tabla de mejores posiciones por LTE y
por 5G, si 5G llega a registrarse.

### Entregable 3 — Perfil horario de la zona

Comparar bloques 15:00, 18:00–21:00 y 23:00 con muestras breves de latencia y
capacidad. El resultado buscado es una diferencia estadística por horario,
separando “radio cambió” de “radio estable pero capacidad cayó”.

### Entregable 4 — Política XIO

Automatizar solo acciones locales y reversibles:

- limitar descargas de MAK;
- notificar cambio de celda, CA, NR o canal Wi‑Fi;
- recomendar USB cuando el hotspot cambie de BSSID/canal;
- generar un informe para Claro con hora, PLMN, celda, radio, latencia y
  consumo.

No se automatiza todavía el cambio forzado de red móvil porque requiere una
capacidad privilegiada que el teléfono puede rechazar o convertir en un
estado peor.

## Qué no recomiendo

- Repetidor celular genérico: puede introducir ruido en uplink, oscilar y
  degradar la red. SUBTEL publicó en 2026 una propuesta con AGC,
  anti-oscilación, límites de ganancia y figura de ruido precisamente por esos
  riesgos: [propuesta técnica de repetidores](https://www.subtel.gob.cl/wp-content/uploads/2026/03/Propuesta_de_Norma_Tecnica_instalacion_y_el_uso_de_amplificadores_o_repetidores.pdf)
  y [resumen de respuestas](https://www.subtel.gob.cl/wp-content/uploads/2026/04/Resumen_Respuestas_Repetidores_Celulares_Web_Subtel.pdf).
- “Triangular” torres usando únicamente una lectura.
- Culpar a iPhone/iPad con Wi‑Fi apagado sin observar Bluetooth, carga,
  temperatura o cambio de celda.
- Usar una VPN para solucionar congestión o selección de antena.
- Forzar 5G solo porque aparece en el menú: 3,5 GHz puede tener peor
  penetración que B28 dentro del edificio.
