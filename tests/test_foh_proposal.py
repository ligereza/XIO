# -*- coding: utf-8 -*-
"""The bridge from what FOH observed to a scene it only proposes.

Las dos reglas que esta prueba defiende: nada se emite desde aca, y nada se
engancha a una medicion que no existe o que es demasiado gruesa para
enganchar. Lo que no se observo no se rellena.
"""

import math

import pytest

from xio.flicker import flicker_reading
from xio.foh_proposal import (
    DB_CEILING,
    DB_FLOOR,
    ProposalError,
    cycle_from_room,
    energy_from_db,
    event_from_observation,
    propose,
)

LINE_SECONDS = 28e-6
FIXTURES = ["par1", "par2", "par3", "par4"]


def _rows(frequency, rows=4000, depth=0.4):
    """En la escala de un sensor de 8 bits: la lectura se niega a medir un
    cuadro sin luz, asi que los fixtures tienen que traer luz."""
    return [128.0 * (1 + depth * math.sin(2 * math.pi * frequency * index * LINE_SECONDS))
            for index in range(rows)]


def _status(level_db=-20.0, available=True, tc="5400.5"):
    return {
        "audio": {"available": available, "level_db": level_db,
                  "reason": None if available else "termux-api no instalado"},
        "timecode": {"value": tc, "display": "01:30:00:15", "state": "corriendo"},
    }


# ── el mapeo declarado ───────────────────────────────────────────────────


def test_the_db_mapping_is_a_written_line_not_a_magic_curve():
    assert energy_from_db(DB_FLOOR) == 0.0
    assert energy_from_db(DB_CEILING) == 1.0
    assert energy_from_db(-28.0) == pytest.approx(0.5, abs=0.02)
    # Fuera de rango se recorta, no se extrapola.
    assert energy_from_db(-80.0) == 0.0
    assert energy_from_db(0.0) == 1.0
    assert energy_from_db(None) is None


# ── el enganche de fase ──────────────────────────────────────────────────


def test_the_cycle_locks_to_an_exact_multiple_of_the_measured_period():
    reading = flicker_reading(_rows(240.0), LINE_SECONDS)
    cycle = cycle_from_room(reading, mode="lock", target_seconds=8.0)
    assert cycle["locked_to_hz"] == pytest.approx(240.0, rel=0.02)
    assert cycle["harmonic"] >= 1
    # El ciclo es harmonic periodos exactos, no 8 s redondos.
    period = 1.0 / cycle["locked_to_hz"]
    assert cycle["cycle_seconds"] == pytest.approx(cycle["harmonic"] * period, rel=1e-9)
    assert cycle["cycle_seconds"] == pytest.approx(8.0, abs=0.01)
    assert cycle["approximate"] is False


def test_a_coarse_measurement_is_not_a_lock_and_says_so():
    # 100 Hz en un cuadro de 1080 filas: +-33 Hz.
    reading = flicker_reading(_rows(100.0, rows=1080), LINE_SECONDS)
    assert reading["confidence"] == "gruesa"
    cycle = cycle_from_room(reading, mode="lock")
    assert cycle["approximate"] is True
    assert "la fase va a derivar" in cycle["reason"]


def test_without_a_measurement_the_cycle_stays_free_instead_of_inventing_one():
    cycle = cycle_from_room(None, mode="lock")
    assert cycle["mode"] == "free"
    assert cycle["locked_to_hz"] is None
    assert "numero inventado" in cycle["reason"]

    # Una lectura que no pudo medir arrastra SU motivo al ciclo, sea cual sea:
    # un cuadro sin luz y un cuadro con luz pero sin pulso fallan distinto.
    oscuro = cycle_from_room(flicker_reading([2.0] * 512, LINE_SECONDS), mode="lock")
    assert oscuro["mode"] == "free"
    assert "practicamente negro" in oscuro["reason"]

    plano = [128.0 + 2.0 * math.sin(index * 12.9898) for index in range(4000)]
    sin_pulso = cycle_from_room(flicker_reading(plano, LINE_SECONDS), mode="lock")
    assert sin_pulso["mode"] == "free"
    assert "ruido" in sin_pulso["reason"]


def test_the_beat_mode_offsets_the_cycle_on_purpose():
    reading = flicker_reading(_rows(240.0), LINE_SECONDS)
    locked = cycle_from_room(reading, mode="lock", target_seconds=8.0)
    beating = cycle_from_room(reading, mode="beat", target_seconds=8.0)
    assert beating["cycle_seconds"] > locked["cycle_seconds"]
    assert beating["mode"] == "beat"


def test_an_unknown_mode_is_refused():
    with pytest.raises(ProposalError):
        cycle_from_room(None, mode="inventado")


# ── lo que no se observo no se rellena ───────────────────────────────────


def test_a_missing_microphone_is_not_a_measured_silence():
    event, provenance = event_from_observation(_status(available=False, level_db=None))
    assert event["payload"]["signal_state"] == "missing"
    assert event["payload"]["amplitude"] == 0.0
    assert provenance["audio_available"] is False
    assert provenance["audio_reason"] == "termux-api no instalado"

    measured, provenance = event_from_observation(_status(level_db=-50.0))
    assert measured["payload"]["signal_state"] == "present"
    assert measured["payload"]["amplitude"] == 0.0
    assert provenance["audio_available"] is True
    # Los dos dan amplitud 0, y el sobre los distingue.


def test_the_pulse_is_zero_because_one_sample_cannot_show_a_transient():
    event, _ = event_from_observation(_status())
    assert event["payload"]["pulse"] == 0.0


def test_a_broken_timecode_does_not_break_the_event():
    event, _ = event_from_observation({"audio": {"available": False},
                                       "timecode": {"value": "no es un numero"}})
    assert event["time_seconds"] == 0.0
    assert event["timecode"] == "no es un numero" or event["timecode"]


# ── la propuesta ─────────────────────────────────────────────────────────


def test_a_proposal_says_in_its_own_envelope_that_nothing_was_sent():
    reading = flicker_reading(_rows(240.0), LINE_SECONDS)
    proposal = propose(_status(), FIXTURES, flicker=reading)
    assert proposal["decision"] == "proposal"
    assert proposal["emitted"] is False
    assert "propone y no decide" in proposal["note"]
    assert proposal["packet_bytes"] > 0
    assert len(proposal["frame"]["lights"]) == len(FIXTURES)


def test_the_proposal_carries_where_every_input_came_from():
    reading = flicker_reading(_rows(240.0), LINE_SECONDS)
    proposal = propose(_status(level_db=-20.0), FIXTURES, flicker=reading)
    assert proposal["observation"]["level_db"] == -20.0
    assert proposal["observation"]["db_floor"] == DB_FLOOR
    assert proposal["cycle"]["locked_to_hz"] == pytest.approx(240.0, rel=0.02)
    assert proposal["event"]["payload"]["amplitude"] == pytest.approx(0.68, abs=0.02)


def test_a_proposal_without_fixtures_is_refused():
    with pytest.raises(ProposalError):
        propose(_status(), [])


def test_the_same_observation_always_proposes_the_same_scene():
    reading = flicker_reading(_rows(240.0), LINE_SECONDS)
    first = propose(_status(), FIXTURES, flicker=reading)
    second = propose(_status(), FIXTURES, flicker=reading)
    assert first["packet_hex"] == second["packet_hex"]
    assert first["frame"]["scene"] == second["frame"]["scene"]
