"""Utilidades de señal para PCM 16 bits little-endian mono."""
from __future__ import annotations

import io
import math
import wave
from array import array

try:  # audioop existe hasta Python 3.12 y es ~100x más rápido que Python puro.
    import audioop  # type: ignore
except ImportError:  # pragma: no cover - Python 3.13+
    audioop = None

ANCHO_MUESTRA = 2
RMS_MAXIMO = 32768.0


def rms(datos: bytes) -> float:
    """Amplitud RMS de un bloque PCM. 0.0 si el bloque es demasiado corto."""
    if len(datos) < ANCHO_MUESTRA:
        return 0.0
    utiles = datos[: len(datos) - (len(datos) % ANCHO_MUESTRA)]
    if audioop is not None:
        return float(audioop.rms(utiles, ANCHO_MUESTRA))
    muestras = array("h")
    muestras.frombytes(utiles)
    if not muestras:
        return 0.0
    total = 0
    for valor in muestras:
        total += valor * valor
    return math.sqrt(total / len(muestras))


def nivel_normalizado(datos: bytes) -> float:
    """RMS en escala 0..1, con compresión suave para que la boca se vea viva."""
    bruto = rms(datos) / RMS_MAXIMO
    if bruto <= 0.0:
        return 0.0
    # Raíz cuadrada: la energía de la voz es muy desigual y en lineal la boca
    # apenas se movería en las sílabas suaves.
    return min(1.0, math.sqrt(bruto) * 2.6)


def escalar(datos: bytes, factor: float) -> bytes:
    """PCM de 16 bits multiplicado por `factor` (0-1: solo baja)."""
    factor = max(0.0, min(1.0, float(factor)))
    if factor >= 0.999 or not datos:
        return datos
    import array
    muestras = array.array("h")
    muestras.frombytes(datos[: len(datos) - len(datos) % 2])
    for i, m in enumerate(muestras):
        muestras[i] = int(m * factor)
    return muestras.tobytes()


def pico(datos: bytes) -> int:
    if len(datos) < ANCHO_MUESTRA:
        return 0
    utiles = datos[: len(datos) - (len(datos) % ANCHO_MUESTRA)]
    if audioop is not None:
        return int(audioop.max(utiles, ANCHO_MUESTRA))
    muestras = array("h")
    muestras.frombytes(utiles)
    return max((abs(v) for v in muestras), default=0)


def a_wav(pcm: bytes, frecuencia: int) -> bytes:
    """Envuelve PCM crudo en un contenedor WAV, en memoria."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as destino:
        destino.setnchannels(1)
        destino.setsampwidth(ANCHO_MUESTRA)
        destino.setframerate(frecuencia)
        destino.writeframes(pcm)
    return buffer.getvalue()


def de_wav(datos: bytes) -> tuple[bytes, int]:
    """Extrae (pcm, frecuencia) de un WAV en memoria."""
    with wave.open(io.BytesIO(datos), "rb") as origen:
        frecuencia = origen.getframerate()
        pcm = origen.readframes(origen.getnframes())
    return pcm, frecuencia


def duracion_s(pcm: bytes, frecuencia: int) -> float:
    if frecuencia <= 0:
        return 0.0
    return len(pcm) / (ANCHO_MUESTRA * frecuencia)


def trocear(pcm: bytes, bytes_por_trozo: int):
    """Divide PCM en trozos alineados a muestra."""
    paso = max(ANCHO_MUESTRA, bytes_por_trozo - (bytes_por_trozo % ANCHO_MUESTRA))
    for inicio in range(0, len(pcm), paso):
        trozo = pcm[inicio : inicio + paso]
        if trozo:
            yield trozo
