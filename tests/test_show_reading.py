# -*- coding: utf-8 -*-
"""What a measured reading of a FOH show has to hold.

Two halves on purpose:

* invariantes sinteticos, que corren siempre y fijan las reglas (que reloj
  midio, que se descuenta, que se rechaza);
* aceptacion contra el show REAL del 2026-07-24, cuyos numeros fueron
  calculados a mano sobre 2168 registros y escritos en
  `xio/show_kit/ANOTACIONES_SHOW_20260724.md` antes de que existiera este
  codigo. Esa tabla es la respuesta; si el motor no la reproduce, el motor
  esta mal.

La aceptacion usa la copia VERSIONADA del log
(`xio/show_kit/registros/show_dref_20260724/`), no `xio/show_kit/_logs/`, que
esta ignorada por git: una prueba que se salta sola cuando falta el archivo se
lee igual que una prueba que pasa.
"""

import json
from pathlib import Path

import pytest

from xio.show_reading import (
    SESSION_GAP_SECONDS,
    fold,
    load_records,
    parse_timecode,
    read_show,
    sessions,
)


ROOT = Path(__file__).resolve().parents[1]
REAL_LOG = ROOT / "xio" / "show_kit" / "registros" / "show_dref_20260724" / "foh_20260724.jsonl"
DURATIONS = ROOT / "xio" / "show_kit" / "setlist_durations_dref.json"
SHOW_FROM = "2026-07-24T20:01:38"
SHOW_TO = "2026-07-24T21:28:04"


def _write(tmp_path, records, name="show_20260101.jsonl"):
    path = tmp_path / name
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n"
                            for row in records), encoding="utf-8")
    return path


def _advance(ts, cue, title, tc=None, action="auto-tc", n=None):
    detail = {"actual": f"{cue}  {title}"}
    if action is not None:
        detail["accion"] = action
    if n is not None:
        detail["n"] = n
    return {"ts": ts, "tipo": "setlist_next", "detalle": detail,
            "tc": None if tc is None else str(tc)}


def _beat(ts, tc=None):
    return {"ts": ts, "tipo": "heartbeat", "detalle": {"bateria": 90},
            "tc": None if tc is None else str(tc)}


def _freeze(ts, value, state="congelado"):
    return {"ts": ts, "tipo": "tc_freeze",
            "detalle": {"estado": state, "valor": str(value)},
            "tc": None if state == "caido" else str(value)}


def _resume(ts, value):
    return {"ts": ts, "tipo": "tc_resume", "detalle": {"valor": str(value)},
            "tc": str(value)}


# ── invariantes ──────────────────────────────────────────────────────────


def test_timecode_with_frames_needs_the_fps_to_become_seconds():
    assert parse_timecode("01:30:00:00", 30) == 5400.0
    assert parse_timecode("00:00:00:15", 30) == 0.5
    assert parse_timecode("00:00:00:15", 25) == 0.6
    assert parse_timecode("no es timecode", 30) is None


def test_titles_match_across_the_accent_the_setlist_map_does_not_carry():
    # `setlist_durations_dref.json` escribe "Pego fuerte" y el log "Pegó fuerte".
    assert fold("Pegó fuerte") == fold("Pego fuerte")
    assert fold("  Último   Día ") == fold("Ultimo Dia")
    # Pero dos titulos realmente distintos siguen distintos.
    assert fold("Pinky") != fold("FINAL FALSO")


def test_unreadable_lines_are_counted_instead_of_silently_dropped(tmp_path):
    path = tmp_path / "roto.jsonl"
    path.write_text('{"ts": "2026-01-01T00:00:00", "tipo": "heartbeat"}\n'
                    "esto no es json\n"
                    '["una lista no es un registro"]\n'
                    '{"tipo": "heartbeat"}\n',
                    encoding="utf-8")
    records, stats = load_records([path])
    assert len(records) == 1
    assert stats["unreadable_lines"] == 2
    assert stats["without_ts"] == 1


def test_a_missing_log_fails_instead_of_reading_an_empty_show(tmp_path):
    with pytest.raises(Exception):
        load_records([tmp_path / "no-existe.jsonl"])


def test_the_clock_is_declared_and_a_human_tap_has_no_invented_precision(tmp_path):
    path = _write(tmp_path, [
        _advance("2026-01-01T21:00:00", "01:00:00:00", "Uno", tc=3600.0, action=None),
        _advance("2026-01-01T21:03:00", "01:30:00:00", "Dos", tc=5400.0, action=None),
        _beat("2026-01-01T21:04:00", 5460.0),
    ])
    envelope = read_show([path])
    first = envelope["segments"][0]
    assert first["boundary_clock"] == "tap"
    assert first["clock"] == "tap"
    # La latencia de un toque humano no esta medida todavia: null, no un numero.
    assert first["precision_seconds"] is None


def test_two_ltc_samples_are_required_before_a_duration_is_called_exact(tmp_path):
    # FINAL FALSO son 21 s reales y el log solo trae la muestra del disparo:
    # medir por timecode daria 1 s.
    path = _write(tmp_path, [
        _advance("2026-01-01T21:04:42", "07:02:35:00", "FINAL FALSO", tc=25355.9),
        _advance("2026-01-01T21:05:03", "07:30:00:00", "A Fuego", tc=27000.0),
        _beat("2026-01-01T21:06:03", 27060.0),
    ])
    segment = read_show([path])["segments"][0]
    assert segment["ltc_samples"] == 1
    assert segment["exact_by_ltc"] is False
    assert segment["clock"] == "wall"
    assert segment["seconds"] == 21.0
    assert any("no alcanza para medir por timecode" in note for note in segment["notes"])


def test_an_unattributed_blind_window_is_discounted_and_the_supposition_is_said(tmp_path):
    # El caso A Fuego: 8:19 de segmento con 4:16 sin timecode adentro, que era
    # otro tema (invitado). Descontarlo devuelve ~4:03.
    path = _write(tmp_path, [
        _advance("2026-01-01T21:05:03", "07:30:00:00", "A Fuego", tc=27000.0),
        _beat("2026-01-01T21:06:03", 27060.0),
        _freeze("2026-01-01T21:09:02", 27239.0),
        _freeze("2026-01-01T21:09:07", 27239.0, state="caido"),
        _resume("2026-01-01T21:13:23", 28800.0),
        _advance("2026-01-01T21:13:22", "08:00:00:00", "Misionar", tc=28800.0),
        _beat("2026-01-01T21:14:22", 28860.0),
    ])
    segment = read_show([path])["segments"][0]
    assert segment["seconds_wall"] == 499.0
    assert segment["blind_seconds"] == 256.0
    assert segment["seconds_attributed"] == 243.0
    assert any("sin atribuir" in note.lower() for note in segment["notes"])
    assert segment["failure_seconds"] == 0.0
    assert all(window["attributed"] is None for window in segment["dead_windows"])


def test_a_later_ltc_sample_below_an_earlier_one_is_reported_not_resolved(tmp_path):
    path = _write(tmp_path, [
        _advance("2026-01-01T21:21:35", "09:30:00:00", "Funkysolo", tc=34200.0),
        _beat("2026-01-01T21:22:19", 34243.5),
        _beat("2026-01-01T21:26:19", 34484.2),
        _freeze("2026-01-01T21:27:18", 34207.4),
        _advance("2026-01-01T21:27:30", "00:00:00:00", "intro show", tc=600.0),
    ])
    segment = read_show([path])["segments"][0]
    assert segment["contradictions"], "una muestra que retrocede tiene que quedar dicha"
    assert segment["contradictions"][0]["clase"] == "ltc_retrocede"
    # Y con la contradiccion presente, la duracion NO se declara exacta.
    assert segment["exact_by_ltc"] is False
    assert segment["clock"] == "wall"


def test_a_retrigger_of_the_previous_cue_is_dropped_as_a_bounce(tmp_path):
    path = _write(tmp_path, [
        _advance("2026-01-01T21:02:06", "07:00:00:00", "Pinky", tc=25200.0),
        _beat("2026-01-01T21:03:06", 25260.0),
        _advance("2026-01-01T21:04:41", "07:02:35:00", "FINAL FALSO", tc=25355.0),
        _advance("2026-01-01T21:04:42", "07:00:00:00", "Pinky", tc=25320.0),
        _advance("2026-01-01T21:04:42", "07:02:35:00", "FINAL FALSO", tc=25355.9),
        _advance("2026-01-01T21:05:03", "07:30:00:00", "A Fuego", tc=27000.0),
    ])
    envelope = read_show([path])
    titles = [segment["title"] for segment in envelope["segments"]]
    assert titles == ["Pinky", "FINAL FALSO", "A Fuego"]
    assert envelope["redisparos"], "el rebote descartado tiene que quedar registrado"


def test_a_log_is_not_a_show_and_the_reader_never_picks_the_session(tmp_path):
    gap = SESSION_GAP_SECONDS + 60
    path = _write(tmp_path, [
        _advance("2026-01-01T05:00:00", "01:00:00:00", "prueba", tc=3600.0),
        _advance("2026-01-01T05:01:00", "01:30:00:00", "prueba", tc=5400.0),
        _advance("2026-01-01T21:00:00", "01:00:00:00", "show", tc=3600.0),
        _advance("2026-01-01T21:05:00", "01:30:00:00", "show", tc=5400.0),
    ])
    records, _ = load_records([path])
    assert gap > 0
    blocks = sessions(records)
    assert len(blocks) == 2
    envelope = read_show([path])
    # Sin ventana ni eventKey el sobre lo dice, en vez de inventar un show.
    assert envelope["source"]["bounded_by"].startswith("nada")
    assert len(envelope["sessions"]) == 2


def test_the_window_inherits_what_the_setlist_was_already_showing(tmp_path):
    path = _write(tmp_path, [
        _advance("2026-01-01T18:00:00", "00:00:00:00", "intro show", tc=0.0),
        _beat("2026-01-01T20:13:00", 60.0),
        _freeze("2026-01-01T20:18:04", 331.0),
        _advance("2026-01-01T20:18:52", "01:30:00:00", "2000s", tc=5400.0),
        _beat("2026-01-01T20:19:52", 5460.0),
        _freeze("2026-01-01T20:23:29", 5674.3),
        _advance("2026-01-01T20:23:34", "02:00:00:00", "Un call", tc=7200.0),
    ])
    envelope = read_show([path], start="2026-01-01T20:12:00", end="2026-01-01T20:24:00")
    first = envelope["segments"][0]
    assert first["title"] == "intro show"
    assert first["inherited"] is True
    assert any("heredado" in note for note in first["notes"])


# ── aceptacion contra el show real ───────────────────────────────────────


@pytest.fixture(scope="module")
def real_show():
    assert REAL_LOG.is_file(), (
        f"falta el registro versionado del show: {REAL_LOG}. Sin el, esta "
        "aceptacion no mide nada y no debe pasar en silencio.")
    return read_show([REAL_LOG], DURATIONS, start=SHOW_FROM, end=SHOW_TO)


def test_the_real_log_is_read_whole(real_show):
    assert real_show["source"]["records"] == 2020
    assert real_show["source"]["unreadable_lines"] == 0
    assert real_show["source"]["bounded_by"] == "ventana"


@pytest.mark.parametrize("title,expected,clock", [
    # Tabla "Duraciones EXACTAS por LTC" de las anotaciones del show.
    ("intro show", 331.0, "ltc"),      # el clip largo: 5:31, resuelve el pendiente
    ("2000s", 274.3, "ltc"),           # 4:34 clavado
    ("2+1", 145.2, "ltc"),             # 2:25 clavado
    ("Las flores que te gustan", 261.1, "ltc"),   # 4:20
    ("Despertador", 170.6, "ltc"),     # 2:50
    ("Botero", 233.6, "ltc"),          # 3:53
    ("Pinky", 155.0, "ltc"),           # 2:35, y FINAL FALSO aparte
    ("Enrolar", 311.7, "ltc"),         # 5:12 contra un clip de 1:28
    # Tabla por reloj, donde el timecode no cubre el tema.
    ("FINAL FALSO", 21.0, "wall"),     # 0:21, separada del clip de Pinky
    ("Funkysolo", 346.0, "wall"),      # 5:46
    ("Llama a tu amiga", 129.0, "wall"),  # 2:09 de tema + 1:03 de conversacion
])
def test_reproduces_the_hand_measured_duration(real_show, title, expected, clock):
    matches = [segment for segment in real_show["segments"]
               if fold(segment["title"]) == fold(title)]
    assert matches, f"el motor no encontro el tema {title!r}"
    segment = matches[0]
    assert segment["clock"] == clock
    assert segment["seconds"] == pytest.approx(expected, abs=0.6)


def test_the_conversation_inside_llama_a_tu_amiga_is_the_blind_window(real_show):
    segment = next(seg for seg in real_show["segments"]
                   if fold(seg["title"]) == fold("Llama a tu amiga"))
    # Las anotaciones: "2:09 + 1:03 conversacion".
    assert segment["blind_seconds"] == pytest.approx(63.0, abs=1.0)
    assert segment["seconds_wall"] == pytest.approx(192.0, abs=1.0)


def test_the_guest_song_shows_up_as_an_unattributed_window_inside_a_fuego(real_show):
    segment = next(seg for seg in real_show["segments"]
                   if fold(seg["title"]) == fold("A Fuego"))
    # Random Friends: 4:16 sin SMPTE, visual CCTV, sin entrada propia.
    assert segment["blind_seconds"] == pytest.approx(256.0, abs=2.0)
    assert segment["dead_windows"], "la ventana tiene que quedar listada"
    assert all(window["attributed"] is None for window in segment["dead_windows"])


def test_enrolar_is_the_missing_visual_and_it_is_quantified(real_show):
    row = next(row for row in real_show["clip_comparison"]
               if fold(row["title"]) == fold("Enrolar"))
    assert row["verdict"] == "falta visual"
    # Las anotaciones: clip 1:28, real 5:12 -> faltan 3:44 = 224 s.
    assert row["gap_seconds"] == pytest.approx(224.0, abs=2.0)


def test_funkysolo_contradicts_the_hand_note_and_says_so(real_show):
    segment = next(seg for seg in real_show["segments"]
                   if fold(seg["title"]) == fold("Funkysolo"))
    # La anotacion dice "el LTC muere a los 7 s". El log tiene 9 muestras y los
    # heartbeats avanzan 1:1 con el reloj hasta 34484.2 (4:44 dentro del tema),
    # y solo el congelamiento reporta 34207.4. El motor no elige: lo reporta.
    assert segment["ltc_samples"] >= 8
    assert segment["contradictions"]
    contradiction = segment["contradictions"][0]
    assert contradiction["muestra_mayor"]["valor"] == pytest.approx(34484.2, abs=0.5)
    assert contradiction["ultima_muestra"]["valor"] == pytest.approx(34207.4, abs=0.5)


def test_every_segment_declares_a_clock_or_says_it_has_none(real_show):
    for segment in real_show["segments"]:
        if segment["clock"] is None:
            assert any("sin reloj" in note for note in segment["notes"])
        else:
            assert segment["clock"] in ("ltc", "osc_trigger", "wall", "audio", "tap")
            assert segment["seconds"] is not None


# ── la marca en vivo y el reloj sin timecode ─────────────────────────────


def _mark(ts, clase, texto="", tema=None):
    return {"ts": ts, "tipo": "marca",
            "detalle": {"clase": clase, "texto": texto, "tema_en_pantalla": tema,
                        "tc_estado": "caido"},
            "tc": None}


def _clip(ts, layer, clip):
    return {"ts": ts, "tipo": "clip_trigger",
            "detalle": {"layer": layer, "clip": clip,
                        "address": f"/composition/layers/{layer}/clips/{clip}/connect"},
            "tc": None}


def _blind_case(tmp_path, *marks):
    return _write(tmp_path, [
        _advance("2026-01-01T21:05:03", "07:30:00:00", "A Fuego", tc=27000.0),
        _beat("2026-01-01T21:06:03", 27060.0),
        _freeze("2026-01-01T21:09:02", 27239.0),
        _freeze("2026-01-01T21:09:07", 27239.0, state="caido"),
        *marks,
        _resume("2026-01-01T21:13:23", 28800.0),
        _advance("2026-01-01T21:13:24", "08:00:00:00", "Misionar", tc=28800.0),
        _beat("2026-01-01T21:14:24", 28860.0),
    ])


def test_a_content_mark_makes_the_window_its_own_block_and_not_the_song(tmp_path):
    path = _blind_case(tmp_path, _mark("2026-01-01T21:10:00", "contenido",
                                       "tema invitado, visual CCTV"))
    segment = read_show([path])["segments"][0]
    window = segment["dead_windows"][0]
    assert window["attributed"] == "contenido"
    assert window["marks"][0]["texto"].startswith("tema invitado")
    assert segment["blind_seconds"] == 256.0
    assert segment["seconds_attributed"] == 245.0
    assert any("contenido propio" in note for note in segment["notes"])
    # Y ya no queda ningun supuesto sin declarar.
    assert not any("sin atribuir" in note.lower() for note in segment["notes"])


def test_a_failure_mark_keeps_the_blind_time_inside_the_song(tmp_path):
    path = _blind_case(tmp_path, _mark("2026-01-01T21:10:00", "falla",
                                       "se corto el LTC, el tema siguio"))
    segment = read_show([path])["segments"][0]
    assert segment["dead_windows"][0]["attributed"] == "falla"
    # El tema siguio: no se descuenta nada.
    assert segment["blind_seconds"] == 0.0
    assert segment["failure_seconds"] == 256.0
    assert segment["seconds_attributed"] == segment["seconds_wall"]
    assert any("el tema siguio" in note for note in segment["notes"])


def test_marks_that_disagree_are_reported_as_disputed_not_averaged(tmp_path):
    path = _blind_case(tmp_path,
                       _mark("2026-01-01T21:10:00", "contenido"),
                       _mark("2026-01-01T21:11:00", "falla"))
    segment = read_show([path])["segments"][0]
    assert segment["dead_windows"][0]["attributed"] == "discutida"
    # Discutida NO es falla, asi que se descuenta, pero queda la pregunta.
    assert segment["blind_seconds"] == 256.0
    assert len(segment["dead_windows"][0]["marks"]) == 2


def test_a_plain_note_does_not_attribute_the_window(tmp_path):
    path = _blind_case(tmp_path, _mark("2026-01-01T21:10:00", "nota", "publico cantando"))
    segment = read_show([path])["segments"][0]
    assert segment["dead_windows"][0]["attributed"] == "nota"
    assert segment["blind_seconds"] == 256.0


def test_with_no_setlist_the_resolume_clip_trigger_is_the_clock(tmp_path):
    path = _write(tmp_path, [
        _clip("2026-01-01T22:00:00", 1, 1),
        _clip("2026-01-01T22:03:20", 1, 2),
        _clip("2026-01-01T22:07:00", 2, 5),
        _beat("2026-01-01T22:08:00"),
    ])
    envelope = read_show([path])
    assert envelope["segment_source"] == "clip_trigger"
    first = envelope["segments"][0]
    assert first["clock"] == "osc_trigger"
    assert first["seconds"] == 200.0
    assert first["boundary_clock"] == "osc_trigger"
    # Sin cue map el segmento se llama por lo unico que dijo el paquete.
    assert first["title"] == "capa 1 / clip 1"
    assert first["named_by_cue_map"] is False


def test_the_clip_title_comes_from_the_cue_map_and_never_from_the_address(tmp_path):
    cue_map = tmp_path / "cue_map.json"
    cue_map.write_text(json.dumps({
        "fps": 30,
        "cues": [{"n": "1", "tema": "intro show", "timecode": "00:00:00:00",
                  "layer": 1, "clip": 1, "clip_name": "INTRO"},
                 {"n": "3", "tema": "2000s", "timecode": "01:30:00:00",
                  "layer": 1, "clip": 2, "clip_name": "2000"}],
    }), encoding="utf-8")
    path = _write(tmp_path, [
        _clip("2026-01-01T22:00:00", 1, 1),
        _clip("2026-01-01T22:01:11", 1, 2),
        _clip("2026-01-01T22:05:45", 9, 9),
    ])
    envelope = read_show([path], cue_map_path=cue_map)
    titles = [(seg["title"], seg["named_by_cue_map"]) for seg in envelope["segments"]]
    assert titles[0] == ("intro show", True)
    assert titles[1] == ("2000s", True)
    # Un clip que el cue map no declara NO recibe un nombre inventado.
    assert titles[2] == ("capa 9 / clip 9", False)


def test_the_setlist_wins_over_clip_triggers_when_both_exist(tmp_path):
    path = _write(tmp_path, [
        _advance("2026-01-01T22:00:00", "01:00:00:00", "Uno", tc=3600.0),
        _clip("2026-01-01T22:00:01", 1, 1),
        _advance("2026-01-01T22:03:00", "01:30:00:00", "Dos", tc=5400.0),
        _beat("2026-01-01T22:04:00", 5460.0),
    ])
    envelope = read_show([path])
    assert envelope["segment_source"] == "setlist_next"
    assert [seg["title"] for seg in envelope["segments"]] == ["Uno", "Dos"]


# ── ventanas de señal: el show que conduce la consola ────────────────────

PHONE_LOGS = ROOT / "xio" / "show_kit" / "registros" / "telefono_20260917"


def _signal_on(ts, channel, info, pps=9):
    return {"ts": ts, "tipo": "senal_on",
            "detalle": {"canal": channel, "info": info, "pps": pps}, "tc": None}


def _signal_off(ts, channel, last=None):
    return {"ts": ts, "tipo": "senal_off",
            "detalle": {"canal": channel, "ultimo": last}, "tc": None}


def _app_signal(ts, protocol, detail):
    return {"ts": ts, "tipo": "app_signal",
            "detalle": {"source": "xio_foh_apk", "protocol": protocol,
                        "detail": detail}, "tc": None}


def test_a_signal_stretch_is_measured_per_channel(tmp_path):
    path = _write(tmp_path, [
        _signal_on("2026-01-01T22:00:00", "artnet", "OpDmx uni 1"),
        _signal_off("2026-01-01T22:00:12", "artnet", "2026-01-01T22:00:07"),
        _signal_on("2026-01-01T22:01:00", "osc", "/composition/1/clip"),
        _signal_off("2026-01-01T22:01:30", "osc"),
    ])
    windows = read_show([path])["signal_windows"]
    assert [(w["channel"], w["seconds"]) for w in windows] == [
        ("artnet", 12.0), ("osc", 30.0)]
    assert windows[0]["last_packet_ts"] == "2026-01-01T22:00:07"
    assert windows[0]["reported_by_apk"] is False


def test_a_stretch_reported_by_the_native_apk_says_so(tmp_path):
    path = _write(tmp_path, [
        _app_signal("2026-01-01T22:00:00", "Art-Net", "OpDmx uni 1"),
        _signal_on("2026-01-01T22:00:01", "artnet", "APK OpDmx uni 1"),
        _signal_off("2026-01-01T22:00:06", "artnet"),
    ])
    window = read_show([path])["signal_windows"][0]
    # No es lo mismo lo que vio este proceso que lo que otro le conto.
    assert window["reported_by_apk"] is True
    assert window["info"] == "APK OpDmx uni 1"


def test_a_stretch_still_open_at_the_end_of_the_log_is_not_given_a_duration(tmp_path):
    path = _write(tmp_path, [
        _signal_on("2026-01-01T22:00:00", "sacn", "E1.31 uni 3"),
        _beat("2026-01-01T22:05:00"),
    ])
    window = read_show([path])["signal_windows"][0]
    assert window["seconds"] is None
    assert window["to_ts"] is None
    assert "quedo abierta" in window["note"]


def test_the_rescued_phone_log_carries_the_signal_the_dref_show_never_had():
    # El log del 24/07 tiene los tres canales en cero porque ese show se opero
    # por timecode. El del 23/07, rescatado del telefono, si trae senal.
    log = PHONE_LOGS / "foh_20260723.jsonl"
    assert log.is_file(), f"falta el registro rescatado: {log}"
    windows = read_show([log])["signal_windows"]
    assert windows, "el 23/07 tiene transiciones de senal reales"
    assert {w["channel"] for w in windows} <= {"artnet", "sacn", "osc", "audio"}
    assert all(w["seconds"] is None or w["seconds"] >= 0 for w in windows)


def test_the_september_log_is_bounded_by_its_own_event_key():
    log = PHONE_LOGS / "foh_20260911.jsonl"
    assert log.is_file(), f"falta el registro rescatado: {log}"
    envelope = read_show([log],
                         event_key="vj_show:drefquila-chocolate-curico-2026-07-24")
    assert envelope["source"]["bounded_by"] == "eventKey"
    # 478 de 843 registros llevan esa clave: el limite lo trae el propio log.
    assert envelope["source"]["records_for_event"] == 478
    assert envelope["source"]["records"] == 843
    apk_windows = [w for w in envelope["signal_windows"] if w["reported_by_apk"]]
    assert apk_windows, "el 11/09 trae senal ingestada por la APK nativa"
