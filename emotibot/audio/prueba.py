"""Prueba de audio en pantalla: el veredicto de bin/diagnostico_audio.py
(mismos umbrales), en frases cortas para la configuración."""
from __future__ import annotations

import math

SNR_MINIMA_DB = 10.0


def db(valor: float, referencia: float) -> float:
    if valor <= 0 or referencia <= 0:
        return 0.0
    return 20 * math.log10(valor / referencia)


def clasificar(ruido: float, voz: float, piso: float) -> str:
    """«bajo» (la voz no llega al piso del detector), «ruido» (llega, pero
    con menos de 10 dB sobre el ruido) u «ok»."""
    if voz < piso:
        return "bajo"
    if (db(voz, ruido) if ruido > 0 else 0.0) < SNR_MINIMA_DB:
        return "ruido"
    return "ok"


def veredicto(ruido: float, voz: float, piso: float) -> list[str]:
    snr = db(voz, ruido) if ruido > 0 else 0.0
    lineas = [f"Ruido de fondo: {ruido:.0f} RMS · voz: {voz:.0f} RMS · SNR {snr:.1f} dB."]
    codigo = clasificar(ruido, voz, piso)
    if codigo == "bajo":
        lineas += ["La voz no llega al umbral del detector.",
                   "Sube la ganancia del micrófono en el sistema y repite la prueba,",
                   "o prueba la sensibilidad «Alta»."]
    elif codigo == "ruido":
        lineas += ["La voz llega, pero hay mucho ruido cerca.",
                   "Acerca el micrófono o reduce el ruido de la sala."]
    else:
        lineas += ["El micrófono va bien a esta distancia."]
    return lineas
