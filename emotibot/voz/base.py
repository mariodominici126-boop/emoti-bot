"""Interfaz común de los sintetizadores y división en frases."""
from __future__ import annotations

import re
from typing import Iterator, Protocol

_RE_LIMPIEZA = re.compile(r"[`*_#>\[\]|]+")
_RE_ESPACIOS = re.compile(r"\s+")
_RE_CORTE = re.compile(r"(?<=[\.\!\?\…\:\;])\s+|\n+")

MIN_CARACTERES_FRASE = 28
MIN_CARACTERES_COLA = 12


class Sintetizador(Protocol):
    nombre: str
    frecuencia: int

    def sintetizar(self, texto: str) -> Iterator[bytes]:
        """Produce PCM 16 bits mono, frase a frase."""
        ...

    def cerrar(self) -> None: ...


def limpiar(texto: str, maximo: int = 700) -> str:
    """Prepara texto para pronunciar: sin markdown ni espacios redundantes."""
    sin_marcas = _RE_LIMPIEZA.sub("", str(texto))
    return _RE_ESPACIOS.sub(" ", sin_marcas).strip()[:maximo]


def partir_en_frases(texto: str) -> list[str]:
    """Divide en frases para sintetizar y reproducir de forma escalonada.

    Granularidad por frase, no por palabra: así la primera frase empieza a
    sonar mientras se sintetiza la siguiente, que es de donde sale la mejora
    perceptible de latencia, sin depender de APIs de streaming que cambian
    entre versiones de Piper.

    Las frases muy cortas se unen a la siguiente: sintetizar "Sí." por
    separado suena entrecortado y añade una pausa artificial.
    """
    limpio = limpiar(texto)
    if not limpio:
        return []
    crudas = [p.strip() for p in _RE_CORTE.split(limpio) if p and p.strip()]
    if not crudas:
        return [limpio]

    frases: list[str] = []
    acumulado = ""
    for parte in crudas:
        acumulado = f"{acumulado} {parte}".strip() if acumulado else parte
        if len(acumulado) >= MIN_CARACTERES_FRASE:
            frases.append(acumulado)
            acumulado = ""
    if acumulado:
        # Una cola muy corta ("Sí.") se pega a la frase anterior: sintetizarla
        # sola suena entrecortado. Una cola con cuerpo propio ("¿Cómo estás?")
        # se queda aparte, para no perder el escalonado de la síntesis.
        if frases and len(acumulado) < MIN_CARACTERES_COLA:
            frases[-1] = f"{frases[-1]} {acumulado}".strip()
        else:
            frases.append(acumulado)
    return frases
