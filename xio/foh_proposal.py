"""From what the FOH surface observed to a lighting scene it merely proposes.

XIO already had the two halves and they had never been joined. `foh_monitor`
measures the room -- audio level, timecode, the pulse of a wall -- and
`semantic_lighting` turns a canonical event into a deterministic scene plus a
compact packet an edge node could expand into DMX. This module is the bridge,
and it is what turns the witness into a collaborator: from the microphone,
which works with no console, no timecode and no protocol at all, a scene can be
PROPOSED.

The boundary is the one `xio/vision/README.md` already states and this keeps:
**propone, nunca decide**. Nothing here opens a socket, sends a packet or
touches a fixture. It returns a frame and the bytes; emitting them is an
explicit act by somebody else, and `semantic_lighting` was written the same way
on purpose.

The new part is the phase. A chaser at a given phase across fixtures IS spatial
banding, and a strobe IS temporal flicker, so a room whose pulse has been
MEASURED can be played with instead of guessed at: ``lock`` makes the proposed
cycle an exact multiple of the room's period, ``beat`` offsets it on purpose to
produce a slow, controlled beat. And when the measurement is coarse -- a 30 ms
frame cannot resolve 100 Hz better than +-33 Hz -- the lock says it is
approximate, because locking onto 100+-33 Hz is not a lock.
"""

from __future__ import annotations

import math

from xio.semantic_lighting import build_predictive_frame, pack_semantic_frame


SCHEMA = "xio:foh-lighting-proposal:0.1"

# Mapeo declarado de dBFS a energia 0..1. No es una curva magica: es una recta
# entre un piso y un techo escritos aca, para que se pueda discutir. El umbral
# por omision del plugin es -50 dBFS, asi que el piso lo acompaña.
DB_FLOOR = -50.0
DB_CEILING = -6.0

MODES = ("lock", "beat", "free")


class ProposalError(ValueError):
    """Raised when a proposal would rest on something nobody measured."""


def energy_from_db(level_db, floor=DB_FLOOR, ceiling=DB_CEILING):
    """Map an RMS dBFS level to 0..1 with the mapping written down."""
    if level_db is None:
        return None
    if ceiling <= floor:
        raise ProposalError("el techo de dBFS tiene que ser mayor que el piso")
    span = ceiling - floor
    return max(0.0, min(1.0, (float(level_db) - floor) / span))


def cycle_from_room(flicker, mode="lock", target_seconds=8.0, beat_seconds=30.0):
    """Choose the chaser cycle against the room's MEASURED pulse.

    `lock`: el ciclo queda en un multiplo entero del periodo de la sala, asi que
    la fase se repite igual cada vuelta. `beat`: se corre a proposito para que
    la diferencia produzca una batida lenta de `beat_seconds`. `free`: no usa la
    medicion, y lo dice.

    Una medicion gruesa no se puede enganchar: se devuelve `approximate` con la
    resolucion que la lectura declaro, para que quien decida sepa que el
    enganche vale +-eso.
    """
    if mode not in MODES:
        raise ProposalError(f"mode debe ser uno de {MODES}")
    result = {"mode": mode, "cycle_seconds": float(target_seconds),
              "locked_to_hz": None, "harmonic": None, "approximate": None,
              "reason": None}
    if mode == "free":
        result["reason"] = "ciclo libre: no usa ninguna medicion de la sala"
        return result

    frequency = (flicker or {}).get("frequency_hz")
    if not frequency:
        result["mode"] = "free"
        result["reason"] = (
            "no hay frecuencia medida de la sala: "
            f"{(flicker or {}).get('reason') or (flicker or {}).get('verdict') or 'sin lectura'}"
            ". El ciclo queda libre en vez de engancharse a un numero inventado.")
        return result

    period = 1.0 / float(frequency)
    harmonic = max(1, int(round(target_seconds / period)))
    locked = harmonic * period
    if mode == "beat":
        # Un ciclo mas por batida: la diferencia de fase recorre una vuelta
        # completa en `beat_seconds`.
        beats = max(beat_seconds, locked * 2.0)
        locked = locked * (1.0 + locked / beats)
    result.update({
        "cycle_seconds": round(locked, 9),
        "locked_to_hz": float(frequency),
        "harmonic": harmonic,
        "approximate": (flicker or {}).get("confidence") == "gruesa",
    })
    resolution = (flicker or {}).get("resolution_hz")
    if result["approximate"]:
        result["reason"] = (
            f"la medicion es gruesa (+-{resolution} Hz): el enganche es "
            "aproximado y la fase va a derivar. Sirve para probar, no para "
            "afirmar que quedo en fase.")
    return result


def event_from_observation(status, sequence=1, event_id=None, timestamp=None):
    """Build the canonical event `semantic_lighting` expects, from /status.

    Lo que no se observo NO se rellena: sin audio disponible el evento va con
    `signal_state: missing`, que es lo que ese modulo ya sabe tratar poniendo la
    energia en cero. Un silencio medido y un microfono ausente no son lo mismo,
    y el sobre del resultado los distingue.
    """
    status = status or {}
    audio = status.get("audio") or {}
    timecode = status.get("timecode") or {}
    available = bool(audio.get("available"))
    energy = energy_from_db(audio.get("level_db")) if available else None
    value = timecode.get("value")
    try:
        time_seconds = max(0.0, float(value))
    except (TypeError, ValueError):
        time_seconds = 0.0
    display = timecode.get("display") or timecode.get("value")
    event = {
        "event_id": event_id or "foh-observation",
        "sequence": int(sequence),
        "timestamp": timestamp or "1970-01-01T00:00:00+00:00",
        "timecode": str(display) if display not in (None, "") else "00:00:00:00",
        "time_seconds": time_seconds,
        "payload": {
            "amplitude": round(energy, 6) if energy is not None else 0.0,
            # El pulso pide una transitoria y /status entrega un nivel: sin dos
            # muestras no se puede afirmar una, asi que va en cero declarado.
            "pulse": 0.0,
            "signal_state": "present" if available and energy is not None else "missing",
        },
    }
    provenance = {
        "audio_available": available,
        "audio_reason": None if available else audio.get("reason"),
        "level_db": audio.get("level_db"),
        "db_floor": DB_FLOOR,
        "db_ceiling": DB_CEILING,
        "timecode_state": timecode.get("state"),
    }
    return event, provenance


def propose(status, fixture_ids, session_id="foh", flicker=None, mode="lock",
            parameters=None, sequence=1, event_id=None, timestamp=None,
            target_seconds=8.0):
    """Propose a scene from an observation. It is never sent from here."""
    if not fixture_ids:
        raise ProposalError("sin fixtures no hay escena que proponer")
    event, provenance = event_from_observation(status, sequence, event_id, timestamp)
    cycle = cycle_from_room(flicker, mode, target_seconds)
    params = dict(parameters or {})
    params["cycle_seconds"] = cycle["cycle_seconds"]
    frame = build_predictive_frame(event, session_id=session_id,
                                   fixture_ids=list(fixture_ids),
                                   parameters=params)
    packet = pack_semantic_frame(frame)
    return {
        "schema": SCHEMA,
        "domain": "vj_foh",
        # Lo que este sobre ES y lo que no es, escrito en el propio sobre.
        "decision": "proposal",
        "emitted": False,
        "note": ("XIO propone y no decide: nadie envio nada. Expandir esto a DMX "
                 "es un acto explicito de otro, fuera de este modulo."),
        "event": event,
        "observation": provenance,
        "cycle": cycle,
        "frame": frame,
        "packet_hex": packet.hex(),
        "packet_bytes": len(packet),
    }
