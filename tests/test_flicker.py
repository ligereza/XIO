# -*- coding: utf-8 -*-
"""What a flicker reading has to get right, and what it must refuse to claim.

Todo sintetico y determinista: se construye la serie de filas con una
frecuencia conocida y un tiempo de linea conocido, y se verifica que el
estimador la recupere. Es la unica forma de probar esto sin el telefono, y es
mas severa que una foto: aca tambien se prueban los casos donde el metodo
MIENTE con cara de certeza (aliasing, pendiente espacial, poca modulacion).
"""

import math

import pytest

from xio.flicker import (
    FlickerError,
    aliases,
    banding_origin,
    calibrate_line_seconds,
    detrend,
    flicker_index,
    flicker_reading,
    modulation_depth,
    value_quantization,
)


# Un sensor tipico: ~1080 filas leidas en unos 30 ms -> ~28 us por fila.
LINE_SECONDS = 28e-6
ROWS = 1080


def _rows(frequency_hz, depth=0.5, line_seconds=LINE_SECONDS, rows=ROWS,
          phase=0.0, base=0.5, slope=0.0, noise=None):
    series = []
    for index in range(rows):
        value = base * (1.0 + depth * math.sin(
            2.0 * math.pi * frequency_hz * index * line_seconds + phase))
        value += slope * index
        if noise:
            # Ruido determinista: no se usa random para que la prueba no falle
            # una vez cada tanto.
            value += noise * math.sin(index * 12.9898)
        series.append(value)
    return series


def test_a_known_frequency_is_recovered_from_the_row_series():
    reading = flicker_reading(_rows(240.0), LINE_SECONDS)
    assert reading["verdict"] == "flicker medido"
    assert reading["frequency_hz"] == pytest.approx(240.0, rel=0.02)
    assert reading["modulation_depth"] == pytest.approx(0.5, rel=0.05)
    assert reading["confidence"] == "utilizable"


def test_a_short_frame_cannot_resolve_a_low_pulse_and_says_it(_=None):
    # 1080 filas a 28 us son 30 ms: un pulso de 100 Hz entra 3 veces. El numero
    # existiria, pero valdria +-33 Hz, asi que la lectura lo declara gruesa.
    reading = flicker_reading(_rows(100.0), LINE_SECONDS)
    assert reading["resolution_hz"] == pytest.approx(33.07, rel=0.02)
    assert reading["cycles_in_frame"] == pytest.approx(3.0, abs=0.6)
    assert reading["confidence"] == "gruesa"
    assert "no se arregla midiendo mas fino" in reading["reason"]
    assert reading["frequency_hz"] == pytest.approx(100.0, abs=reading["resolution_hz"])


def test_a_pulse_below_the_window_floor_is_refused_not_guessed():
    # 40 Hz en 30 ms es un solo ciclo: no hay periodo que estimar.
    reading = flicker_reading(_rows(40.0, depth=0.5), LINE_SECONDS, min_hz=10.0)
    assert reading["frequency_hz"] is None
    assert reading["verdict"] == "por debajo de lo que este cuadro puede resolver"
    assert "mas filas" in reading["reason"]


def test_a_longer_readout_does_resolve_the_mains_pulse():
    # Una foto de 4000 filas es una ventana de 112 ms: 100 Hz entra 11 veces.
    reading = flicker_reading(_rows(100.0, rows=4000), LINE_SECONDS)
    assert reading["cycles_in_frame"] == pytest.approx(11.2, abs=0.6)
    assert reading["confidence"] == "utilizable"
    assert reading["frequency_hz"] == pytest.approx(100.0, rel=0.02)


@pytest.mark.parametrize("frequency", [100.0, 120.0, 240.0, 480.0, 1000.0, 2400.0])
def test_the_estimator_holds_across_the_frequencies_a_room_actually_has(frequency):
    # Con una ventana larga (una foto, no un cuadro de video) el metodo sostiene
    # desde la red hasta el PWM de un LED moderno.
    reading = flicker_reading(_rows(frequency, depth=0.35, rows=4000), LINE_SECONDS)
    assert reading["frequency_hz"] == pytest.approx(frequency, rel=0.03)
    assert reading["confidence"] == "utilizable"


def test_a_spatial_ramp_is_removed_instead_of_being_read_as_a_pulse():
    # Vignetting o un degrade del contenido: una pendiente fuerte encima de un
    # pulso de 240 Hz no debe desviar la frecuencia.
    reading = flicker_reading(_rows(240.0, depth=0.3, slope=0.0008), LINE_SECONDS)
    assert reading["frequency_hz"] == pytest.approx(240.0, rel=0.03)
    flat = detrend([1.0 + 0.01 * index for index in range(200)])
    assert max(abs(value) for value in flat) < 1e-9


def test_noise_does_not_invent_a_frequency_where_there_is_no_pulse():
    flat = [0.5 + 0.001 * math.sin(index * 12.9898) for index in range(ROWS)]
    reading = flicker_reading(flat, LINE_SECONDS)
    assert reading["verdict"] == "sin flicker medible"
    assert "ruido" in reading["reason"]
    assert reading["frequency_hz"] is None


def test_without_the_line_time_it_reports_rows_and_refuses_to_report_hertz():
    reading = flicker_reading(_rows(100.0, rows=4000), None)
    assert reading["frequency_hz"] is None
    assert reading["band_rows"] == pytest.approx(1.0 / (100.0 * LINE_SECONDS), rel=0.03)
    assert reading["verdict"] == "periodo en filas, sin frecuencia"
    assert "no se adivina" in reading["reason"]


def test_the_ambiguity_above_nyquist_is_published_not_hidden():
    reading = flicker_reading(_rows(240.0, depth=0.4), LINE_SECONDS)
    assert reading["nyquist_hz"] == pytest.approx(0.5 / LINE_SECONDS, rel=0.01)
    assert reading["aliases_hz"], "una sola captura no puede desambiguar"
    # Los alias declarados son los que dibujarian la MISMA banda.
    sample_rate = 1.0 / LINE_SECONDS
    assert any(abs(candidate - (sample_rate - 240.0)) < 1.0
               for candidate in reading["aliases_hz"])


def test_aliases_are_empty_without_a_calibration():
    assert aliases(240.0, None) == []
    assert aliases(None, LINE_SECONDS) == []


def test_the_mains_lamp_calibrates_the_line_time_of_this_sensor():
    # El procedimiento de sala: red de 50 Hz -> la lampara pulsa a 100 Hz.
    rows = _rows(100.0, depth=0.6, rows=4000)
    calibration = calibrate_line_seconds(rows, known_hz=100.0)
    assert calibration["line_seconds"] == pytest.approx(LINE_SECONDS, rel=0.03)
    assert "ESTE sensor" in calibration["note"]
    # Y con ese tiempo de linea, otra fuente se mide bien.
    reading = flicker_reading(_rows(360.0, depth=0.3),
                              calibration["line_seconds"])
    assert reading["frequency_hz"] == pytest.approx(360.0, rel=0.05)


def test_calibration_refuses_a_series_with_no_band():
    with pytest.raises(FlickerError):
        calibrate_line_seconds([0.5] * 256, known_hz=100.0)
    with pytest.raises(FlickerError):
        calibrate_line_seconds(_rows(100.0), known_hz=0)


def test_calibration_refuses_a_frame_with_too_few_reference_cycles():
    # Calibrar con 3 ciclos propagaria el error a TODA medicion posterior.
    with pytest.raises(FlickerError) as failure:
        calibrate_line_seconds(_rows(100.0, rows=1080), known_hz=100.0)
    assert "se propaga" in str(failure.value)


def test_a_reading_needs_real_numbers_and_enough_rows():
    with pytest.raises(FlickerError):
        flicker_reading([0.1, 0.2, 0.3], LINE_SECONDS)
    with pytest.raises(FlickerError):
        flicker_reading([0.5] * 64 + [float("nan")] * 64, LINE_SECONDS)
    with pytest.raises(FlickerError):
        flicker_reading(["0.5"] * 128, LINE_SECONDS)


def test_modulation_and_flicker_index_describe_depth_not_frequency():
    deep = _rows(100.0, depth=0.8)
    shallow = _rows(100.0, depth=0.1)
    assert modulation_depth(deep) > modulation_depth(shallow)
    assert flicker_index(deep) > flicker_index(shallow)
    assert 0.0 < flicker_index(deep) < 0.5


# ── de quien son las bandas ──────────────────────────────────────────────


def _staircase(steps=8, rows=ROWS, offset=0.0):
    """A posterized gradient: flat plateaus with equal-height steps."""
    series = []
    for index in range(rows):
        level = int(index * steps / rows)
        series.append(offset + level / float(steps))
    return series


def test_a_posterized_gradient_is_recognized_by_its_value_staircase():
    quantization = value_quantization(_staircase())
    assert quantization["quantized"] is True
    assert quantization["plateau_ratio"] > 0.9
    assert quantization["step_uniformity"] == pytest.approx(1.0, abs=0.05)


def test_a_smooth_pulse_is_not_a_staircase():
    quantization = value_quantization(_rows(100.0))
    assert quantization["quantized"] is False
    assert quantization["plateau_ratio"] < 0.1


def test_content_posterization_is_attributed_to_the_content():
    # El mismo degrade posterizado, corrido en el cuadro porque el contenido se
    # movio: sigue siendo del contenido.
    origin = banding_origin([_staircase(), _staircase(offset=0.05),
                             _staircase(offset=0.1)])
    assert origin["origin"] == "contenido"
    assert "posterizacion" in origin["reason"]
    assert origin["quantized_frames"] == 3


def test_two_frames_never_establish_that_a_band_stayed_put():
    frames = [_rows(240.0, depth=0.4, phase=0.0) for _ in range(2)]
    origin = banding_origin(frames)
    assert origin["origin"] is None
    assert "casualidad" in origin["reason"]


def test_a_band_that_does_not_move_between_frames_belongs_to_the_wall():
    frames = [_rows(240.0, depth=0.4, phase=0.0) for _ in range(4)]
    origin = banding_origin(frames)
    assert origin["origin"] == "muro o refresco"
    assert origin["phase_spread"] <= 0.1


def test_a_band_that_travels_with_the_image_belongs_to_the_content():
    frames = [_rows(240.0, depth=0.4, phase=phase)
              for phase in (0.0, 1.9, 3.5, 5.1)]
    origin = banding_origin(frames)
    assert origin["origin"] == "contenido"
    assert origin["phase_spread"] >= 0.5


def test_when_the_evidence_does_not_decide_it_says_so_instead_of_choosing():
    frames = [_rows(240.0, depth=0.4, phase=phase) for phase in (0.0, 0.35, 0.7)]
    origin = banding_origin(frames)
    assert origin["origin"] is None
    assert "no se puede distinguir" in origin["reason"]


def test_one_frame_cannot_answer_a_temporal_question():
    with pytest.raises(FlickerError):
        banding_origin([_rows(240.0)])


def test_known_cabinet_seams_turn_the_inference_into_a_check():
    frames = [_rows(240.0, depth=0.4) for _ in range(3)]
    period = flicker_reading(frames[0], None)["band_rows"]
    seams = [int(round(period * multiple)) for multiple in (1, 2, 3)]
    origin = banding_origin(frames, geometry_rows=seams)
    assert origin["at_known_geometry"] == "3/3"


def test_the_resolvable_range_is_answered_before_capturing():
    from xio.flicker import resolvable_range
    # Camara 0 del Xiaomi 8299e66f: 3472 filas (dumpsys media.camera, 2026-09-17).
    main = resolvable_range(3472, 20e-6)
    assert main["frame_seconds"] == pytest.approx(0.0694, abs=0.001)
    assert main["resolution_hz"] == pytest.approx(14.4, abs=0.2)
    assert main["usable_from_hz"] < 100.0, "tiene que resolver la red de 50/100 Hz"
    # Camara 1: menos filas, ventana mas corta, 100 Hz queda al limite.
    front = resolvable_range(1940, 20e-6)
    assert front["usable_from_hz"] > 100.0
    assert front["nyquist_hz"] == main["nyquist_hz"]
    with pytest.raises(Exception):
        resolvable_range(0, 20e-6)
