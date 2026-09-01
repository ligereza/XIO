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
- `snapshot`: estado materializado por un reducer puro.
- `proposal`: sugerencia explicable, sin autoridad de ejecución.
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
│   ├── transport/   política y transporte local/red inyectable
│   └── sessions/    peers, handshake y fan-out dirigido
├── adapters/xio/    frontera de observación y ejecución explícita
└── tests/           pruebas unitarias e integración ligera
```

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
