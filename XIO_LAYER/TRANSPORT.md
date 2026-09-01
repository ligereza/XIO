# TRANSPORT

Primera capa funcional de XIO Layer. Su responsabilidad es mover mensajes y
exponer el estado de entrega; no recolecta señales, no analiza el significado
de los mensajes y no reenvía ni ejecuta acciones por decisión propia.

## Modelo

```text
Endpoint = scheme + address + port + medium + scope
TransportMessage = source + destination + channel + envelope + sequence
DeliveryReceipt = accepted/duplicate/error + latency + sequence
ConnectionStatus = state + latency + sent/received/lost + last_error
```

### Medio y alcance son dimensiones diferentes

| Campo | Valores | Uso |
|---|---|---|
| `medium` | `ethernet`, `wifi`, `hotspot`, `router`, `unknown` | Cómo llega el enlace al endpoint. |
| `scope` | `local`, `lan`, `wan` | Qué alcance tiene la comunicación. |
| `scheme` | `memory`, `unix`, `tcp`, `udp`, `https` | Cómo se representa el transporte. |

Un enlace Wi-Fi puede ser LAN o WAN; un router puede ser el medio de una red
LAN o la salida WAN. Tener Internet no demuestra que un host sea alcanzable
localmente y no debe confundirse con el transporte entre aplicaciones.

## Política

`TransportPolicy` permite declarar explícitamente esquemas, peers, medios y
alcances. Por defecto no autoriza `wan`; para habilitarlo hay que incluir
`NetworkScope.WAN` en `allowed_scopes`. La política no escanea, no descubre y
no abre puertos.

El transporte local `InMemoryTransport` aplica la misma política, pero no crea
sockets. Es la base de pruebas y de una futura orquestación offline.

`JsonLineTransport` sólo serializa un mensaje a un `writer` inyectado. El host
que lo use decide si ese writer corresponde a TCP, UDP, Unix, TLS, una cola o
un adaptador de aplicación. XIO Layer no administra sockets, credenciales,
firewall ni port forwarding.

## Secuencia e idempotencia

- `sequence` es opcional y es monotónico por endpoint/canal cuando se usa;
- un salto (`1 → 3`) devuelve `sequence_gap` y no entrega el mensaje;
- una secuencia atrasada devuelve `out_of_sequence`;
- el mismo `message_id` o `idempotency_key` con el mismo contenido devuelve
  `duplicate` sin duplicar la entrega;
- la misma clave con contenido distinto devuelve `idempotency_conflict`;
- un fallo de entrega se registra con `mark_lost`, sin inventar que el paquete
  llegó.

## OSC y Art-Net

`OscEnvelope` y `ArtNetEnvelope` son tipos distintos:

- OSC conserva una dirección `/ruta`, argumentos y un timetag opcional;
- Art-Net conserva opcode, universo, secuencia, physical y bytes DMX opacos;
- ambos viajan dentro de `TransportMessage`, pero no se convierten entre sí ni
  se tratan como una lista común de argumentos.

La capa no implementa parsing completo, ArtPoll, render, cues ni semántica de
show. Eso pertenece a un adaptador de protocolo o a SIGNALS/GATEWAY más
adelante.

## Router común

Un router doméstico participa como medio de transporte: entrega DHCP, puentea
Ethernet/Wi-Fi/hotspot y posiblemente enruta hacia WAN. TRANSPORT sólo necesita
un endpoint autorizado; no necesita asumir marca, modelo, firmware o acceso
administrativo al router.

Información adicional podría incorporarse en el futuro, siempre como una
observación opcional y separada del envío:

- API documentada del router: clientes, estado de enlace y contadores;
- SNMP habilitado por el administrador: interfaces, errores y octetos;
- UPnP/IGD explícitamente autorizado: capacidades anunciadas del gateway.

No se implementan aquí credenciales, captura de tráfico, escaneo de red,
descubrimiento indiscriminado, firmware, control remoto ni port forwarding.

## Próximas capas

- `SIGNALS`: recolecta eventos de fuentes concretas.
- `ANALYSIS`: mide y explica latencia, pérdida y comportamiento.
- `GATEWAY`: reenvía mediante políticas explícitas.

TRANSPORT no debe absorber esas responsabilidades.

## Sesiones multi-peer

`core/sessions/peer_session.py` adds a session layer above `Transport` without
changing the transport boundary:

```text
caller registers peer + endpoint
        -> explicit handshake request
        -> explicit handshake ack
        -> connected session
        -> directed signal fan-out
        -> delivery ack per peer
```

- `PeerDescriptor` contains `peer_id`, `protocol_version`, `capabilities` and
  the caller-provided endpoint;
- `HandshakeRequest` and `HandshakeAck` carry `session_id` and explicit status;
- only authorized peers can connect; unknown peers are rejected;
- major protocol version mismatch is rejected; minor versions may interoperate;
- `SignalEnvelope` preserves `message_id`, `sequence`, source/session metadata
  and the original OSC or Art-Net envelope;
- `DeliveryAck` reports accepted, duplicate, sequence error, blocked,
  disconnected or version/peer rejection;
- fan-out is directed to the peer ids provided by the caller, or to already
  connected peers when the caller explicitly asks for the connected set;
- revocation changes the peer to `blocked` and prevents later delivery;
- disconnect changes the peer to `disconnected` and prevents later delivery;
- replay, observation and fan-out never create an `ExplicitAction`.

The current implementation is an offline session state machine. It does not
perform discovery, scan networks, open public sockets, authenticate identities,
or guarantee delivery on a real network. A real host must provide the
transport writer, identity/authentication policy, persistence and retry policy
as separate layers.
