# XIO Layer

Infraestructura reutilizable para una capa adaptativa entre usuario,
dispositivos y aplicaciones.

XIO Layer extrae de XIO sólo la infraestructura transversal: eventos, tiempo,
snapshots, transporte, permisos, auditoría, replay y recuperación. No contiene
lógica de Android ni decide acciones pedagógicas o de dispositivo.

## Contrato de extremo a extremo

```text
event → snapshot → proposal → explicit_action → result → audit
```

- `event`: observación con tiempo de origen y tiempo de recepción.
- `snapshot`: estado materializado por un reducer puro sobre un único stream;
  registros y snapshots de otro stream se rechazan. En una proyección
  incremental, los registros deben seguir la versión del snapshot base.
- `proposal`: sugerencia explicable, con parámetros e IDs de eventos validados,
  pero sin autoridad de ejecución.
- `explicit_action`: confirmación explícita de un actor.
- `result`: resultado `succeeded`, `failed` o `denied`.
- `audit`: registro append-only con cadena de hashes.

No existe una ruta `event → action`. El replay sólo reconstruye estado.
`ActionGate` exige confirmación explícita y permiso vigente en el momento de
ejecutar.

## Estructura

```text
XIO_LAYER/
├── core/
│   ├── contracts/   modelos y protocolos estables
│   ├── events/      log idempotente y replay por secuencia de ingestión
│   ├── snapshots/   proyección, snapshots y checkpoints atómicos
│   ├── audit/       permisos revocables y ledger hash-chained
│   ├── transport/   política, transporte y probe de conectividad inyectable
│   └── sessions/    peers, handshake y fan-out dirigido
├── adapters/xio/    frontera de observación y ejecución explícita
├── adapters/        puentes de protocolo y entrada LUCIDA/MULTI
└── tests/           pruebas unitarias e integración ligera
```

`adapters/handoff.py` adds the explicit caller-selected adapter boundary. The
caller obtains a deterministic route plan, selects one declared candidate,
then prepares a privacy-projected LUCIDA/MULTI message. Preparation is not
delivery: no transport `send`, socket, discovery or action execution occurs.
Registry lookups, routing records and caller-supplied plans are validated before
adapter lookup or conversion; malformed inputs cannot invoke an adapter.
Selections reject ambiguous capability collections, and privacy projection
requires a valid selection and handoff identifier before it builds a new event.
The default allowlist exports no payload or provenance keys and anonymizes
session and peer ids. `AuditLedger` receives only safe selection and fingerprint
metadata; the resulting event remains replayable through `ApplicationEventLog`.
`adapters/local_source.py` supplies a read-only JSONL source that deduplicates
and replays records by ingestion sequence before handing them to that selected
route. It does not choose a route or send a message.
`EventLog` and `ApplicationEventLog` persist records with fsync and the shared
sidecar lock, reload current state before append, and expose persistence errors
without changing replay into action execution.
Both append boundaries reject the wrong event record type before acquiring a
file lock or touching in-memory or on-disk state.
`Event.from_dict()` and `ApplicationEvent.from_dict()` require the exact fields
and scalar types emitted by their serializers; malformed records are rejected
before replay or LUCIDA/MULTI restoration.
`ApplicationEvent` also rejects non-finite numbers and unsupported provenance
values at construction, so a built event is already safe to fingerprint and
serialize.
Its reversible bytes/datetime decoder reports malformed persisted values as
`ApplicationEventContractError` instead of leaking parser-specific exceptions.
`ConnectionStatus.from_dict()` applies the same fail-closed rule to measured
connectivity state, including endpoint fields, counters, latency and sequence.
The direct constructors enforce the same invariants, so restored and
programmatically created transport observations cannot diverge in type rules.
The event and snapshot constructors enforce the same temporal rule: boolean
values cannot masquerade as schema versions or replay sequences.
Transport receipts apply the same fail-closed rule to result flags, sequences
and latency values before a delivery status is exposed.
Transport policies reject ambiguous booleans and malformed allowlists before
they can authorize a transport.
Core mapping contracts are copied defensively and reject non-JSON values or
non-finite numbers before they can be hashed, replayed or audited.
`ExplicitAction` requires a real boolean confirmation and mapping parameters;
truthy strings cannot bypass the explicit-action gate.
`ActionGate` serializes the current permission check with the handler call:
revocation waits for an already-authorized operation to finish, while later
operations observe the revoked grant and are denied.
Permission registry operations validate actor, permission and callable inputs
before lock acquisition; invalid permission data cannot mutate the registry or
create an audit result.
`CheckpointStore` keeps atomic checkpoint files under a directory lock, treats
an identical stream/version checkpoint as idempotent, and rejects a different
state at an already occupied version. `RecoveryManager` also validates a
checkpoint against the event-log prefix before using it; an inconsistent
checkpoint is reported and replaced by a full state-only replay.
`SnapshotStore.save()` and `CheckpointStore.save()` reject non-snapshot inputs
before mutating memory or acquiring the checkpoint file lock.
Projection and recovery also reject malformed stream ids, record collections,
base snapshots and manager dependencies before replay begins.
Checkpoint restoration requires the exact serialized fields, scalar types and
state hash emitted by `Checkpoint.to_dict()`.
`JsonLineAuditLedger` persists the handoff audit chain across restarts and
rejects malformed or tampered entries on reload. `AuditEntry.from_dict()` also
requires exact serialized fields and scalar types before hash verification.
Direct `AuditEntry` construction applies the same identity, actor, outcome and
hash invariants, so in-memory and restored audit records cannot diverge.
Both audit ledgers also require `details` to be a mapping and validate the
record identity fields before acquiring their locks or mutating state.
Delivery is a distinct caller action through `deliver_adapter_handoff`; its
receipt is audited, it requires a current `PermissionRegistry` grant, and a
blocked, revoked or idempotency-conflicting delivery is not retried or
rerouted; idempotency conflict remains distinguishable as a terminal result.
The permission check and injected transport send share one registry lock, so a
revocation cannot interleave between authorization and that explicit send.
`AdapterHandoffDelivery` also rejects impossible status/receipt combinations,
so accepted, duplicate and conflict outcomes remain auditable as structured
results.
Local replay derives stable handoff ids from the selected route and event id,
keeping repeated projections fingerprint-identical.
Prepared handoffs can be restored from their privacy-safe representation; the
caller must re-inject its identity before any permission-checked delivery.
`JsonLineHandoffStore` makes that representation append-only and restart-safe,
with a versioned hash chain, idempotent same-content writes and rejection of
same-id content changes or tampered/reordered records. Calls sharing one store
instance and separate processes are serialized through a sidecar lock file.
Its append boundary rejects non-handoff values before acquiring the sidecar
lock; direct `AdapterHandoff` construction also validates types, route identity
and bridge coherence.
`PrivacyPolicy` rejects strings, mappings and non-text values where a collection
of allowlist keys is required, preventing accidental character-wise or
ambiguous privacy projections.
`TransportMessage.from_dict()` is the shared strict wire parser used by both
transport and handoff restoration.
`core/file_lock.py` provides the same portable sidecar locking primitive to
both persistent stores.
`core/sessions` applies the same fail-closed rule to peer descriptors,
handshake records, signal envelopes and delivery acknowledgements; session
wire restoration rejects missing, extra or coercible fields before any state
transition.
The session manager also serializes its in-memory state transitions, so
per-peer idempotency is preserved when callers fan out concurrently.
Signal payload, metadata and protocol-envelope representations are validated
as strict JSON before they can participate in fingerprinting or replay.
Session checkpoints preserve authorization evidence and delivery history for a
caller-controlled restart while intentionally requiring a fresh handshake.
Replacing a peer authorization also invalidates stale endpoint and handshake
state while retaining explicit delivery history.
Public session operations reject malformed record types and peer identifiers
before mutating state or calling the injected transport.

`adapters/lucida_input.py` exposes a narrower `LucidaInputRecord` for a future
LUCIDA reducer. It carries only event identity, source/version, type/time,
sequence, capability, privacy status and a bounded data shape. It reuses
`PrivacyPolicy` and `ApplicationEventLog`; raw payload values never cross this
boundary. `LucidaInputLog.replace()` is the explicit append-only replacement
path, while replay remains sequence-ordered and idempotent. The synthetic
fixture is `tests/fixtures/lucida_input_events.jsonl`.

## Contrato de consumo LUCIDA/MULTI

LUCIDA y MULTI reciben un `ApplicationEvent` mediante un `TransportMessage`
con dos marcas obligatorias: el canal `application-event` y el envelope
`xio.application-event` con `schema_version` 1. El payload del transporte es
el `ApplicationEvent.to_dict()` completo; por eso conserva `event_id`,
`session_id`, `peer_id`, `sequence`, ambos timestamps, `raw_hash`,
`provenance` y el payload codificado de forma reversible, incluidos bytes.

El puente [lucida_bridge.py](adapters/lucida_bridge.py) sólo convierte y
valida. No abre sockets, no descubre peers y no ejecuta acciones. El host
decide el writer o transporte concreto, y LUCIDA/MULTI puede entregar el
evento validado a `ApplicationEventLog` o a replay. La deduplicación de
entrega usa `event_id` como `idempotency_key`; la secuencia del evento debe
coincidir con la secuencia del transporte.

Flujo de consumo:

```text
ApplicationEvent
  -> application_event_to_transport
  -> TransportMessage(application-event, xio.application-event)
  -> transport_to_application_event
  -> EventLog / snapshot replay
```

La conversión nunca crea una ruta `event -> action`.

## Ejecución

Desde la raíz del repositorio:

```text
python -m unittest discover -s XIO_LAYER/tests -v
```

No hay dependencias de Flask, ADB, Termux, Android o servicios externos.

## Principios de seguridad

- timestamps ingenuos son rechazados; el desfase del reloj de origen se
  registra, no se inventa ni se usa para reordenar eventos;
- duplicados idénticos son idempotentes; el mismo id con otro contenido falla;
- una revocación de permisos invalida la ejecución pendiente;
- checkpoints se escriben mediante archivo temporal y reemplazo atómico;
- un checkpoint corrupto no bloquea la recuperación: se informa y se reconstruye
  desde eventos;
- el transporte no abre sockets ni elige destinos por sí solo;
- XIO aporta observación y ejecución, pero XIO Layer no le entrega decisión
  automática.

## Technical language rule

Code and machine-readable contracts use English ASCII only. This includes
identifiers, file and directory names, imports, branch-facing technical names,
event keys, fixtures, tests, and parseable logs. Do not place accented letters,
non-ASCII punctuation, or locale-specific characters in those elements. User
interface text and explanatory documentation may be localized, but must stay
separate from technical identifiers and contracts.
