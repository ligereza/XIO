"""Flicker and banding read from a rolling-shutter frame, as numbers.

A phone camera reads its sensor row by row, so ONE frame is a time series
along the vertical axis: about 1/30 s sampled at the line rate, which is
thousands of samples per second. That turns the camera into a cheap
photometer, and it is the only instrument in XIO that measures the LIGHT THAT
CAME OUT instead of the packets the rig sent.

This module deliberately takes **a luminance value per sensor row**, not an
image. Decoding a frame belongs to whoever holds the camera (the APK, or a
host tool); the math, the provenance and the honesty about ambiguity belong
here, the same boundary `semantic_lighting` draws. Nothing here opens a
socket, touches a device or reads a file.

Two questions it answers, both asked in a real booth:

* ``flicker_reading`` -- at what frequency and how deeply is that wall or that
  fixture pulsing. This is what ruins the video someone is shooting of the
  show, and what gives a headache by the third hour.
* ``banding_origin`` -- are those colour bands coming from the CONTENT (an
  8-bit gradient, a low bitrate) or from the WALL (the LED processor, its bit
  depth, its gamma)? The answer decides whether you re-render the clip or call
  the LED tech, and it is the only question a VJ needs answered in the moment.

The line time is a DEVICE CONSTANT and it is never guessed: without it a band
spacing cannot become a frequency. ``calibrate_line_seconds`` derives it from
a source of known frequency -- in Chile the mains run at 50 Hz, so any cheap
LED or incandescent lamp in the room pulses at 100 Hz and is a free reference.
"""

from __future__ import annotations

import math


SCHEMA = "xio:foh-flicker-reading:0.1"

# Por debajo de esto no se busca: una frame entera dura ~1/30 s, asi que una
# "frecuencia" de 5 Hz dentro de una sola frame es un gradiente, no un pulso.
MIN_HZ = 20.0
# Profundidad de modulacion por debajo de la cual no se afirma un flicker: es
# ruido de sensor o textura de la imagen.
MIN_MODULATION = 0.02

# Un cuadro de rolling shutter es una ventana corta: 1080 filas a 28 us son
# 30 ms, y en 30 ms un pulso de 100 Hz entra solo 3 veces. Con menos de dos
# ciclos no hay periodo que estimar, y con menos de cuatro el numero existe
# pero vale +-1/T, que a esa ventana son +-33 Hz. Las dos cosas se declaran en
# la lectura en vez de entregar una frecuencia con precision fingida.
MIN_CYCLES = 2.0
COARSE_CYCLES = 4.0
# Para calibrar hace falta mas: un error en el tiempo de linea se propaga a
# TODA medicion posterior de ese aparato.
CALIBRATION_CYCLES = 6.0


class FlickerError(ValueError):
    """Raised when a reading cannot be made safely."""


def _finite_series(rows, field="rows"):
    series = []
    for value in rows:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise FlickerError(f"{field} debe traer solo numeros")
        value = float(value)
        if not math.isfinite(value):
            raise FlickerError(f"{field} trae un valor no finito")
        series.append(value)
    if len(series) < 32:
        raise FlickerError(f"{field} necesita al menos 32 filas para medir")
    return series


def detrend(series):
    """Remove the linear ramp before measuring the pulse.

    Una proyeccion tiene estructura espacial propia -- vignetting, un degrade
    en el contenido, la pared mas iluminada arriba -- y esa pendiente se
    confundiria con la parte baja del espectro. Se quita una recta por minimos
    cuadrados, no la media nada mas.
    """
    count = len(series)
    mean_index = (count - 1) / 2.0
    mean_value = sum(series) / count
    numerator = sum((index - mean_index) * (value - mean_value)
                    for index, value in enumerate(series))
    denominator = sum((index - mean_index) ** 2 for index in range(count))
    slope = numerator / denominator if denominator else 0.0
    intercept = mean_value - slope * mean_index
    return [value - (slope * index + intercept) for index, value in enumerate(series)]


def _fft(values):
    """Iterative radix-2 FFT, stdlib only.

    Barrer la frecuencia con Goertzel bin por bin costaba cientos de millones
    de operaciones sobre una foto de 4000 filas. La FFT encuentra el pico de
    una pasada y Goertzel queda para refinar alrededor de el, que es donde su
    precision sirve. Sin numpy a proposito: esto tambien tiene que poder correr
    en Termux, donde instalar una rueda binaria no es parte del trato.
    """
    count = len(values)
    spectrum = [complex(value, 0.0) for value in values]
    # Permutacion bit-reversa.
    bits = count.bit_length() - 1
    for index in range(count):
        mirror = int(format(index, "0%db" % bits)[::-1], 2) if bits else 0
        if mirror > index:
            spectrum[index], spectrum[mirror] = spectrum[mirror], spectrum[index]
    size = 2
    while size <= count:
        angle = -2.0 * math.pi / size
        step = complex(math.cos(angle), math.sin(angle))
        for start in range(0, count, size):
            factor = complex(1.0, 0.0)
            half = size // 2
            for offset in range(start, start + half):
                even = spectrum[offset]
                odd = spectrum[offset + half] * factor
                spectrum[offset] = even + odd
                spectrum[offset + half] = even - odd
                factor *= step
        size *= 2
    return spectrum


def _peak_bin(series, bottom_cycles, top_cycles):
    """Dominant cycles-per-row from the FFT, restricted to the allowed band."""
    padded = 1
    while padded < len(series):
        padded *= 2
    window = series + [0.0] * (padded - len(series))
    spectrum = _fft(window)
    best_index, best_magnitude = None, -1.0
    for index in range(1, padded // 2):
        cycles = index / float(padded)
        if cycles < bottom_cycles or cycles > top_cycles:
            continue
        magnitude = abs(spectrum[index])
        if magnitude > best_magnitude:
            best_magnitude, best_index = magnitude, index
    if best_index is None:
        return None
    return best_index / float(padded)


def _goertzel(series, bin_frequency):
    """Magnitude of one frequency bin, in cycles per sample."""
    coefficient = 2.0 * math.cos(2.0 * math.pi * bin_frequency)
    first = second = 0.0
    for value in series:
        first, second = coefficient * first - second + value, first
    real = first - second * math.cos(2.0 * math.pi * bin_frequency)
    imaginary = second * math.sin(2.0 * math.pi * bin_frequency)
    return math.hypot(real, imaginary) * 2.0 / len(series)


def modulation_depth(series):
    """Peak-to-peak modulation over the sum, the usual flicker percentage."""
    top, bottom = max(series), min(series)
    if top + bottom <= 0:
        return None
    return (top - bottom) / (top + bottom)


def flicker_index(series):
    """Area above the mean over the total area (IES flicker index)."""
    mean_value = sum(series) / len(series)
    if mean_value <= 0:
        return None
    above = sum(value - mean_value for value in series if value > mean_value)
    total = sum(series)
    return above / total if total else None


def aliases(frequency_hz, line_seconds, limit=4):
    """The frequencies that would draw the SAME bands at this line rate.

    Una camara de rolling shutter muestrea a 1/line_seconds, asi que todo lo
    que este por encima de Nyquist vuelve replegado. Decir "la pared pulsa a
    240 Hz" sin decir que 240 y sus alias son indistinguibles con UNA captura
    es dar una certeza que la medicion no tiene. Se desambigua con una segunda
    captura a otro tiempo de linea, o contra una fuente conocida.
    """
    if not frequency_hz or not line_seconds:
        return []
    sample_rate = 1.0 / line_seconds
    found = []
    for order in range(1, limit + 1):
        for candidate in (order * sample_rate - frequency_hz,
                          order * sample_rate + frequency_hz):
            if candidate > frequency_hz and math.isfinite(candidate):
                found.append(round(candidate, 2))
    return sorted(set(found))


def resolvable_range(rows, line_seconds):
    """What a frame of this shape can and cannot resolve, BEFORE capturing.

    Sirve para elegir camara y modo en vez de descubrir despues que el cuadro
    no alcanzaba. Medido en el Xiaomi 8299e66f el 2026-09-17 (`dumpsys
    media.camera`): la camara 0 tiene 3472 filas y exposicion minima de 82 us;
    la camara 1 tiene 1940 filas y minima de 17 us. O sea que la 0 da la
    ventana larga -- buena para la red y frecuencias bajas -- y la 1 resuelve
    PWM rapido, porque para ver bandas la exposicion tiene que ser mas corta
    que el periodo del pulso.
    """
    if not rows or not line_seconds or rows < 2 or line_seconds <= 0:
        raise FlickerError("rows y line_seconds tienen que ser positivos")
    frame_seconds = rows * float(line_seconds)
    return {
        "schema": SCHEMA,
        "rows": int(rows),
        "line_seconds": float(line_seconds),
        "frame_seconds": round(frame_seconds, 6),
        "resolution_hz": round(1.0 / frame_seconds, 2),
        "min_hz": round(MIN_CYCLES / frame_seconds, 2),
        "usable_from_hz": round(COARSE_CYCLES / frame_seconds, 2),
        "nyquist_hz": round(0.5 / float(line_seconds), 2),
        "note": ("por debajo de min_hz no hay periodo que estimar; entre min_hz "
                 "y usable_from_hz la lectura sale gruesa; la exposicion tiene "
                 "que ser mas corta que el periodo que se quiere ver"),
    }


def flicker_reading(rows, line_seconds=None, min_hz=MIN_HZ, resolution_hz=0.5):
    """Measure the pulse in one rolling-shutter frame's row luminance."""
    series = _finite_series(rows)
    detrended = detrend(series)
    depth = modulation_depth(series)
    index = flicker_index(series)

    reading = {
        "schema": SCHEMA,
        "rows": len(series),
        "modulation_depth": None if depth is None else round(depth, 4),
        "flicker_index": None if index is None else round(index, 4),
        "line_seconds": line_seconds,
        "frequency_hz": None,
        "cycles_per_row": None,
        "band_rows": None,
        "aliases_hz": [],
        "nyquist_hz": None,
        "cycles_in_frame": None,
        "resolution_hz": None,
        "confidence": None,
        "verdict": None,
        "reason": None,
    }
    if line_seconds:
        frame_seconds = len(series) * float(line_seconds)
        reading["frame_seconds"] = round(frame_seconds, 6)
        # La resolucion de frecuencia de UNA ventana es 1/T. No se mejora
        # barriendo mas fino: es el ancho del propio lobulo.
        reading["resolution_hz"] = round(1.0 / frame_seconds, 2)
        reading["resolvable_min_hz"] = round(MIN_CYCLES / frame_seconds, 2)

    if depth is not None and depth < MIN_MODULATION:
        reading["verdict"] = "sin flicker medible"
        reading["reason"] = (f"modulacion {depth * 100:.1f}% por debajo del "
                             f"minimo {MIN_MODULATION * 100:.0f}%: es ruido o "
                             "textura de la imagen, no un pulso")
        return reading

    # Barrido en ciclos por fila. El limite superior es Nyquist del propio
    # muestreo por filas: media muestra por ciclo.
    floor_cycles = MIN_CYCLES / len(series)
    if line_seconds:
        top_cycles = 0.5
        step = resolution_hz * line_seconds
        bottom_cycles = max(min_hz * line_seconds, floor_cycles)
    else:
        # Sin calibracion se puede hablar de periodo en FILAS, nunca en Hz.
        top_cycles = 0.5
        step = 1.0 / (8.0 * len(series))
        bottom_cycles = floor_cycles
    if step <= 0 or bottom_cycles >= top_cycles:
        reading["verdict"] = "sin flicker medible"
        reading["reason"] = "la resolucion pedida no cabe en las filas dadas"
        return reading

    # Busqueda por FFT, refinado por Goertzel alrededor del pico.
    best_cycles = _peak_bin(detrended, bottom_cycles, top_cycles)
    if best_cycles is None:
        reading["verdict"] = "sin flicker medible"
        reading["reason"] = "no hubo ningun maximo en la banda buscada"
        return reading
    coarse_step = max(step, 1.0 / (8.0 * len(detrended)))
    scan_bottom = max(best_cycles - 2.0 * coarse_step, bottom_cycles)
    scan_top = min(best_cycles + 2.0 * coarse_step, top_cycles)
    best_magnitude = -1.0
    cycles = scan_bottom
    while cycles <= scan_top:
        magnitude = _goertzel(detrended, cycles)
        if magnitude > best_magnitude:
            best_magnitude, best_cycles = magnitude, cycles
        cycles += step

    # Refinado parabolico con los dos vecinos: la grilla no tiene por que caer
    # justo sobre la frecuencia real.
    left = _goertzel(detrended, max(best_cycles - step, bottom_cycles))
    right = _goertzel(detrended, min(best_cycles + step, top_cycles))
    denominator = left - 2.0 * best_magnitude + right
    if denominator:
        best_cycles += step * 0.5 * (left - right) / denominator

    cycles_in_frame = best_cycles * len(series)
    reading["cycles_per_row"] = round(best_cycles, 8)
    reading["band_rows"] = round(1.0 / best_cycles, 2) if best_cycles else None
    reading["cycles_in_frame"] = round(cycles_in_frame, 2)

    # El maximo pegado al piso del barrido no es una medicion: es el borde.
    if best_cycles <= bottom_cycles + step:
        reading["verdict"] = "por debajo de lo que este cuadro puede resolver"
        reading["frequency_hz"] = None
        reading["band_rows"] = None
        reading["reason"] = (
            f"el maximo cae en el piso del barrido ({cycles_in_frame:.1f} ciclos "
            f"en el cuadro). Con esta ventana no se puede afirmar una frecuencia "
            f"mas baja: hace falta capturar mas filas o un modo mas lento.")
        return reading

    reading["confidence"] = ("gruesa" if cycles_in_frame < COARSE_CYCLES
                             else "utilizable")
    if line_seconds:
        reading["frequency_hz"] = round(best_cycles / line_seconds, 2)
        reading["nyquist_hz"] = round(0.5 / line_seconds, 2)
        reading["aliases_hz"] = aliases(reading["frequency_hz"], line_seconds)
        reading["verdict"] = "flicker medido"
        if reading["confidence"] == "gruesa":
            reading["reason"] = (
                f"solo {cycles_in_frame:.1f} ciclos en el cuadro: la frecuencia "
                f"vale +-{reading['resolution_hz']} Hz, que es el ancho del "
                "lobulo de esta ventana y no se arregla midiendo mas fino")
    else:
        reading["verdict"] = "periodo en filas, sin frecuencia"
        reading["reason"] = ("falta line_seconds: el tiempo de linea del sensor "
                            "es una constante del aparato y no se adivina. "
                            "calibrate_line_seconds lo deriva contra los 100 Hz "
                            "de la red.")
    return reading


def calibrate_line_seconds(rows, known_hz, min_hz=MIN_HZ):
    """Derive the sensor line time from a source of known frequency.

    Procedimiento de sala: apuntar a una lampara barata alimentada por la red
    y capturar. En Chile la red es de 50 Hz, asi que el brillo pulsa al doble,
    100 Hz, y el espaciado de las bandas en filas da el tiempo de linea. Hecho
    una vez por aparato, queda.
    """
    if not known_hz or known_hz <= 0:
        raise FlickerError("known_hz tiene que ser una frecuencia positiva")
    reading = flicker_reading(rows, None, min_hz=min_hz)
    if not reading.get("band_rows"):
        raise FlickerError("no se encontro un periodo de banda para calibrar: "
                           f"{reading.get('reason') or reading.get('verdict')}")
    cycles = reading.get("cycles_in_frame") or 0.0
    if cycles < CALIBRATION_CYCLES:
        raise FlickerError(
            f"solo {cycles:.1f} ciclos de la referencia en el cuadro y hacen "
            f"falta {CALIBRATION_CYCLES:g}: un error de tiempo de linea se "
            "propaga a todo lo que mida este aparato despues. Capturar mas "
            "filas, un modo mas lento, o una referencia de frecuencia mas alta.")
    line_seconds = reading["cycles_per_row"] / known_hz
    return {
        "schema": SCHEMA,
        "line_seconds": line_seconds,
        "band_rows": reading["band_rows"],
        "known_hz": known_hz,
        "rows": reading["rows"],
        "cycles_in_frame": reading["cycles_in_frame"],
        "modulation_depth": reading["modulation_depth"],
        "note": ("valido para ESTE sensor en ESTE modo de captura: cambiar de "
                 "camara, de resolucion o de modo cambia el tiempo de linea"),
    }


def value_quantization(rows, tolerance=1e-6):
    """Detect a value staircase: the fingerprint of content posterization.

    Un degrade de 8 bits mal comprimido sube en ESCALONES de igual altura, con
    mesetas planas entremedio, y eso no depende de donde caiga la pared en el
    cuadro. Una banda del procesador LED, en cambio, sigue la geometria del
    muro. Aca se mide solo el escalon; la geometria la mira `banding_origin`.
    """
    series = _finite_series(rows)
    steps = []
    plateau_rows = 0
    for before, after in zip(series, series[1:]):
        difference = after - before
        if abs(difference) <= tolerance:
            plateau_rows += 1
        else:
            steps.append(abs(difference))
    result = {
        "plateau_ratio": round(plateau_rows / max(len(series) - 1, 1), 4),
        "step_count": len(steps),
        "step_median": None,
        "step_uniformity": None,
        "quantized": False,
    }
    if not steps:
        result["quantized"] = False
        return result
    ordered = sorted(steps)
    middle = len(ordered) // 2
    median = (ordered[middle] if len(ordered) % 2
              else (ordered[middle - 1] + ordered[middle]) / 2.0)
    result["step_median"] = round(median, 6)
    if median > 0:
        spread = sum(abs(step - median) for step in steps) / len(steps)
        uniformity = max(0.0, 1.0 - spread / median)
        result["step_uniformity"] = round(uniformity, 4)
        # Mesetas largas + escalones parejos = cuantizacion de valor.
        result["quantized"] = bool(result["plateau_ratio"] >= 0.5
                                   and uniformity >= 0.8)
    return result


def banding_origin(frames_rows, geometry_rows=None, tolerance=1e-6):
    """Do the bands follow the image, or do they follow the wall?

    Se necesitan VARIOS cuadros, porque la discriminacion es temporal: el
    contenido se mueve y la pared no. Si la fase de la banda se queda quieta en
    el espacio de filas mientras el contenido cambia, la banda es del muro o
    del refresco; si se mueve con la imagen, es del contenido. Y si el propio
    valor sube en escalones parejos, es posterizacion, que tambien es del
    contenido.

    `geometry_rows` son las filas donde estan los bordes fisicos conocidos
    (costuras de gabinete). Si se entregan y las bandas caen ahi, la respuesta
    deja de ser una inferencia.
    """
    if len(frames_rows) < 2:
        raise FlickerError("banding_origin necesita al menos dos cuadros: la "
                           "discriminacion es temporal, no espacial")
    # Cuadros IDENTICOS no son evidencia de que la banda este quieta: son una
    # captura que entrego el mismo buffer varias veces. Medido el 2026-09-17:
    # ffmpeg escribio seis veces el mismo cuadro de la webcam y este modulo
    # contesto "muro o refresco" con dispersion de fase 0.0 -- una respuesta
    # segura y falsa. Un sensor vivo tiene ruido: dos cuadros iguales hasta el
    # ultimo bit no existen.
    distintos = {tuple(rows) for rows in frames_rows}
    if len(distintos) < len(frames_rows):
        raise FlickerError(
            f"{len(frames_rows)} cuadros y solo {len(distintos)} distintos: la "
            "captura esta repitiendo el mismo buffer. Dos cuadros identicos de "
            "un sensor vivo no existen, asi que esto no mide nada.")
    # Con dos cuadros una fase parecida puede ser casualidad. Tres es el minimo
    # para decir que la banda "no se movio".
    enough_frames = len(frames_rows) >= 3
    readings = [flicker_reading(rows, None) for rows in frames_rows]
    # Para preguntar DE QUIEN es la banda, primero tiene que haber banda. Dos o
    # tres ciclos en un cuadro son un degradado de la escena, no un patron: con
    # esa cantidad no se distingue un pulso de la forma de lo que se esta
    # mirando. Se exige el mismo umbral que hace utilizable una lectura.
    periods = [reading["band_rows"] for reading in readings
               if reading.get("band_rows")
               and (reading.get("cycles_in_frame") or 0) >= COARSE_CYCLES]
    # Sin banda no hay origen que atribuir. Medido el 2026-09-17 sobre la webcam
    # de MAK: la luz de la pieza no tenia flicker resoluble y el componente
    # dominante era la propia escena (1.9 ciclos en el cuadro, o sea una zona
    # clara y otra oscura). Este modulo contestaba igual "muro o refresco",
    # etiquetando el origen de algo que no era una banda.
    if len(periods) < len(frames_rows):
        sin_banda = len(frames_rows) - len(periods)
        return {
            "schema": SCHEMA,
            "frames": len(frames_rows),
            "band_rows": None,
            "phase_spread": None,
            "quantized_frames": sum(1 for rows in frames_rows
                                    if value_quantization(rows, tolerance)["quantized"]),
            "origin": None,
            "at_known_geometry": None,
            "reason": (f"{sin_banda} de {len(frames_rows)} cuadros no traen una "
                       f"banda de al menos {COARSE_CYCLES:g} ciclos: lo que domina "
                       "es la escena, no un pulso. Sin banda no hay origen que "
                       "atribuir -- hace falta una ventana mas larga (mas filas) "
                       "o exposicion mas corta."),
        }
    quantization = [value_quantization(rows, tolerance) for rows in frames_rows]

    phases = []
    for rows, reading in zip(frames_rows, readings):
        cycles = reading.get("cycles_per_row")
        if not cycles:
            continue
        detrended = detrend(_finite_series(rows))
        real = sum(value * math.cos(2.0 * math.pi * cycles * index)
                   for index, value in enumerate(detrended))
        imaginary = sum(value * math.sin(2.0 * math.pi * cycles * index)
                        for index, value in enumerate(detrended))
        phases.append(math.atan2(imaginary, real))

    phase_spread = None
    if len(phases) >= 2:
        # Dispersion circular: 0 = la banda no se movio, 1 = fase repartida.
        mean_cos = sum(math.cos(phase) for phase in phases) / len(phases)
        mean_sin = sum(math.sin(phase) for phase in phases) / len(phases)
        phase_spread = round(1.0 - math.hypot(mean_cos, mean_sin), 4)

    result = {
        "schema": SCHEMA,
        "frames": len(frames_rows),
        "band_rows": [None if p is None else round(p, 2) for p in periods] or None,
        "phase_spread": phase_spread,
        "quantized_frames": sum(1 for item in quantization if item["quantized"]),
        "origin": None,
        "reason": None,
        "at_known_geometry": None,
    }

    if geometry_rows and periods:
        period = periods[0]
        hits = sum(1 for row in geometry_rows
                   if min((row % period), period - (row % period)) <= 2.0)
        result["at_known_geometry"] = f"{hits}/{len(geometry_rows)}"

    if result["quantized_frames"] == len(frames_rows):
        result["origin"] = "contenido"
        result["reason"] = ("el valor sube en escalones parejos con mesetas: es "
                            "posterizacion del material, no del muro")
    elif not enough_frames:
        result["origin"] = None
        result["reason"] = (f"{len(frames_rows)} cuadros: con menos de tres, una "
                            "fase parecida puede ser casualidad y no evidencia "
                            "de que la banda este quieta")
    elif phase_spread is not None and phase_spread <= 0.02:
        result["origin"] = "muro o refresco"
        result["reason"] = ("la fase de la banda no se movio entre cuadros "
                            "mientras el contenido cambiaba: la banda esta "
                            "pegada al aparato, no a la imagen")
    elif phase_spread is not None and phase_spread >= 0.3:
        result["origin"] = "contenido"
        result["reason"] = ("la banda se movio con la imagen entre cuadros")
    else:
        result["origin"] = None
        result["reason"] = ("no se puede distinguir con esta evidencia: hacen "
                            "falta mas cuadros, o el encuadre se movio")
    return result
