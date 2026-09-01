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

`ConnectionStatus` also carries the host-supplied `reason` and serializes to a
stable dictionary with the endpoint, state and `checked_at` timestamp.

## Connectivity capability boundary

`ConnectivityProbe` is an injected host interface. Its `probe(endpoint)` method
returns the existing `ConnectionStatus` contract, so Ethernet, Wi-Fi, hotspot
and router reports use the same `medium`, `scope`, `state`, optional latency and
loss counters, timestamp and reason. `ConnectionState.UNKNOWN` means that the
host has not established a known state; it is not a guessed measurement.

`probe_connectivity` validates the returned status and endpoint, then returns
the host report unchanged. It does not create fallback values, open sockets,
scan, discover peers or turn an exception into a synthetic status. The host
owns the measurement method, permissions and any network effects. `UNKNOWN`,
`BLOCKED` and `ERROR` are valid explicit reports and should include a reason
when the host has one.

`adapters/connectivity_events.py` converts this measured status to an
`ApplicationEvent` with `event_type="connectivity.status"` and
`channel="transport"`. The payload contains the serialized status plus the
derived `loss_ratio`; provenance identifies the host probe and status contract.
The event is suitable for LUCIDA/MULTI reducers or analysis, but it is an
observation and never an order. The adapter requires the host to provide the
received timestamp and sequence, so it does not invent timing or connectivity
data.

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

## Canonical application events

`core/events/application.py` defines `ApplicationEvent`, an app-independent
contract with these fields:

```text
source_app, event_type, channel, payload,
source_timestamp, received_timestamp,
session_id, peer_id, sequence, raw_hash, provenance
```

The contract also carries an `event_id` and `schema_version` for replay and
migration. Source and received timestamps are timezone-aware UTC values. A
source clock that is ahead of reception is preserved as evidence and does not
change sequence ordering.

`adapters/protocol_events.py` provides injected conversion from `OscEnvelope`
and `ArtNetEnvelope`. It does not read a socket or discover an application:

- OSC becomes `event_type="osc.message"` with its address, arguments and
  timetag retained in `payload` and `provenance`;
- Art-Net becomes `event_type="artnet.frame"` with opcode, universe, sequence,
  physical and reversible base64 DMX bytes retained;
- the protocol envelope is not flattened into the other protocol's shape;
- `raw_hash` identifies the canonical reversible payload representation;
- `source_app`, `session_id`, `peer_id`, timestamps and sequence are supplied
  by the caller.

`core/events/replay_jsonl.py` provides `ApplicationEventLog` and `replay_jsonl`.
JSONL replay sorts by `sequence`, then received timestamp and event id, skips
identical duplicate ids, and rejects a conflicting fingerprint. The reducer
only returns state. No replay path creates or dispatches an action.

### Consumo por LUCIDA/MULTI

LUCIDA/MULTI can consume the canonical stream at the event boundary:

```text
OSC or Art-Net input
        -> ProtocolEventAdapter
        -> ApplicationEventLog / replay_jsonl
        -> LUCIDA or MULTI reducer/analysis
        -> optional human-readable proposal
```

They should depend on `ApplicationEvent`, not on Xiaomi, Android, ADB, router
details or the original application protocol. `provenance` remains available
for explanation and debugging, while `payload` remains available for exact
protocol-aware consumers. This contract does not define pedagogy, inference,
automation or execution authority.

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
- `fan_out(..., required_capability=...)` returns `capability_missing` for a
  connected peer that lacks the requested capability and does not send the
  signal; omitting the argument preserves the existing fan-out behavior;
- revocation changes the peer to `blocked` and prevents later delivery;
- disconnect changes the peer to `disconnected` and prevents later delivery;
- replay, observation and fan-out never create an `ExplicitAction`.

The current implementation is an offline session state machine. It does not
perform discovery, scan networks, open public sockets, authenticate identities,
or guarantee delivery on a real network. A real host must provide the
transport writer, identity/authentication policy, persistence and retry policy
as separate layers.
