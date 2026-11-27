"""Contrato del reconocimiento de voz."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class ErrorStt(RuntimeError):
    pass


@dataclass
class Transcripcion:
    texto: str
    motor: str
    segundos: float = 0.0
    idioma: str = "es"

    @property
    def vacia(self) -> bool:
        return not self.texto.strip()


class Transcriptor(Protocol):
    nombre: str

    def disponible(self) -> bool: ...

    def transcribir(self, pcm: bytes, frecuencia: int) -> Transcripcion: ...

    def cerrar(self) -> None: ...
