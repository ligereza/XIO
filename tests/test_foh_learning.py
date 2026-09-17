# -*- coding: utf-8 -*-
"""What XIO may learn from its own shows, and what it must refuse to learn.

La regla: un valor aprendido viaja con su cantidad de muestras y su
dispersion, y si no hay muestras suficientes NO se estima. Un sesgo sacado de
una noche no es un sesgo.
"""

from pathlib import Path

import pytest

from xio.foh_learning import (
    MIN_SAMPLES,
    tap_latency,
    tap_precision,
    unfired_cues,
    work_durations,
)
from xio.show_reading import audit_cue_map, load_cue_map, load_records, read_show

ROOT = Path(__file__).resolve().parents[1]
REAL_LOG = ROOT / "xio" / "show_kit" / "registros" / "show_dref_20260724" / "foh_20260724.jsonl"
CUE_MAP = ROOT / "xio" / "show_kit" / "cue_map_dref.json"
DURATIONS = ROOT / "xio" / "show_kit" / "setlist_durations_dref.json"
SHOW_FROM = "2026-07-24T20:01:38"
SHOW_TO = "2026-07-24T21:28:04"


def _advance(ts, cue, title, tc, action="auto-tc"):
    detail = {"actual": f"{cue}  {title}"}
    if action is not None:
        detail["accion"] = action
    return {"ts": ts, "tipo": "setlist_next", "detalle": detail, "tc": str(tc)}


@pytest.fixture(scope="module")
def show_records():
    records, _ = load_records([REAL_LOG])
    return [row for row in records if SHOW_FROM <= row["ts"] <= SHOW_TO]


# ── la latencia del toque ────────────────────────────────────────────────


def test_a_timecode_driven_advance_is_the_control_and_lands_on_zero(show_records):
    # Si el estimador es correcto, un avance disparado POR el timecode tiene
    # atraso cero. Sobre el show real la mediana es 0.033 s.
    latency = tap_latency(show_records)
    assert latency["auto_samples"] == 20
    assert latency["auto_median_seconds"] == pytest.approx(0.0, abs=0.2)


def test_this_corpus_cannot_teach_the_tap_latency_and_says_so(show_records):
    # Los unicos avances manuales del log ocurrieron durante las pruebas, sin
    # timecode corriendo: no hay contra que medirlos.
    latency = tap_latency(show_records)
    assert latency["samples"] == 0
    assert latency["usable"] is False
    assert "no la mano del operador" in latency["reason"]
    assert tap_precision(latency) is None


def test_with_enough_manual_advances_the_lateness_is_measured():
    records = [
        _advance("2026-01-01T21:00:02", "01:00:00:00", "Uno", 3602.0, action=None),
        _advance("2026-01-01T21:03:03", "01:30:00:00", "Dos", 5403.0, action=None),
        _advance("2026-01-01T21:06:02", "02:00:00:00", "Tres", 7202.0, action=None),
        _advance("2026-01-01T21:09:04", "02:30:00:00", "Cuatro", 9004.0, action=None),
        _advance("2026-01-01T21:12:03", "03:00:00:00", "Cinco", 10803.0, action=None),
    ]
    latency = tap_latency(records)
    assert latency["samples"] == 5 >= MIN_SAMPLES
    assert latency["usable"] is True
    assert latency["median_seconds"] == pytest.approx(3.0, abs=0.1)
    assert latency["spread_seconds"] == pytest.approx(0.75, abs=0.3)
    # Y recien ahi el reloj `tap` puede declarar una precision.
    precision = tap_precision(latency)
    assert precision is not None and precision >= 0.5


def test_three_taps_are_not_enough_to_declare_a_bias():
    records = [
        _advance("2026-01-01T21:00:02", "01:00:00:00", "Uno", 3602.0, action=None),
        _advance("2026-01-01T21:03:03", "01:30:00:00", "Dos", 5403.0, action=None),
        _advance("2026-01-01T21:06:02", "02:00:00:00", "Tres", 7202.0, action=None),
    ]
    latency = tap_latency(records)
    assert latency["usable"] is False
    assert latency["median_seconds"] is None
    assert tap_precision(latency) is None


# ── duracion real contra clip, acumulada ─────────────────────────────────


def _reading(title, seconds, clip, clock="ltc"):
    return {
        "segments": [{"title": title, "seconds": seconds, "clock": clock,
                      "precision_seconds": 0.1, "blind_seconds": 0}],
        "clip_comparison": [{"title": title, "clip_seconds": clip,
                             "gap_seconds": round(seconds - clip, 3)}],
    }


def test_one_show_describes_one_night_and_recommends_nothing():
    learned = work_durations([_reading("Enrolar", 311.7, 88.1)])
    row = learned["works"][0]
    assert row["shows"] == 1
    assert row["recommendation"] is None
    assert "esa noche" in row["reason"]


def test_a_gap_that_repeats_across_shows_becomes_a_recommendation():
    learned = work_durations([_reading("Enrolar", 311.7, 88.1),
                              _reading("Enrolar", 305.0, 88.1),
                              _reading("Enrolar", 316.0, 88.1)])
    row = learned["works"][0]
    assert row["shows"] == 3
    assert row["gap_seconds"] > 200
    assert "extender el visual" in row["recommendation"]
    assert row["spread_seconds"] < 10


def test_measurements_that_change_sign_recommend_nothing():
    learned = work_durations([_reading("Botero", 240.0, 234.0),
                              _reading("Botero", 200.0, 234.0)])
    row = learned["works"][0]
    assert row["recommendation"] is None
    assert "no coinciden en el signo" in row["reason"]


def test_a_difference_inside_the_clock_precision_is_not_a_finding():
    learned = work_durations([_reading("2000s", 274.3, 274.467),
                              _reading("2000s", 275.0, 274.467)])
    row = learned["works"][0]
    assert row["recommendation"] is None
    assert "cabe en la precision" in row["reason"]


def test_the_real_show_reproduces_the_pending_work_for_the_next_show():
    envelope = read_show([REAL_LOG], DURATIONS, start=SHOW_FROM, end=SHOW_TO)
    learned = work_durations([envelope])
    worst = learned["works"][0]
    # Lo primero de la lista de pendientes de las anotaciones: Enrolar.
    assert worst["title"] == "Enrolar"
    assert worst["gap_seconds"] == pytest.approx(223.6, abs=2.0)


# ── cues que no dispararon ───────────────────────────────────────────────


def test_the_two_cues_that_never_fired_are_the_ones_the_operator_named(show_records):
    cue_map = load_cue_map(CUE_MAP)
    pending = unfired_cues(show_records, cue_map)
    titles = sorted(row["title"] for row in pending["unfired"])
    # Las anotaciones: Yoseke no se toco, y DIABLO SANTO se reemplazo por un QR
    # soltado a mano.
    assert titles == ["FINAL DIABLO SANTO", "Yoseké"]
    assert "quien decide es el operador" in pending["note"]


def test_a_whole_day_of_testing_answers_about_the_day_not_the_show():
    records, _ = load_records([REAL_LOG])
    pending = unfired_cues(records, load_cue_map(CUE_MAP))
    # Durante las pruebas del dia dispararon todas: el resultado es correcto y
    # no dice nada del show.
    assert pending["unfired"] == []


def test_the_cue_map_numbering_is_audited_before_anyone_fires_a_number():
    audit = audit_cue_map(CUE_MAP)
    assert audit["cues"] == 21
    # Defecto real del dato versionado: la cue de FINAL FALSO trae n="%%%%%%",
    # y por eso el mapa numera 18 lo que el setlist llama 19.
    assert audit["numbering_usable"] is False
    problem = audit["problems"][0]
    assert problem["tema"] == "FINAL FALSO"
    assert problem["clase"] == "n_no_numerico"


def test_the_audit_travels_with_the_unfired_report(show_records):
    pending = unfired_cues(show_records, load_cue_map(CUE_MAP), cue_map_path=CUE_MAP)
    assert pending["cue_map_audit"]["numbering_usable"] is False
