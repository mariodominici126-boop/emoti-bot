"""Contrato de las actividades guiadas.

Las actividades son la diferenciación real del proyecto frente a un chatbot:
están escritas en código, tienen temporización de verdad, funcionan sin
conexión, no consumen cuota y se pueden medir (tasa de finalización). Un
modelo de lenguaje improvisando una respiración no es lo mismo.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class Paso:
    """Una instrucción de la actividad.

    - `texto`: lo que el robot pronuncia.
    - `estado_rostro`: estado visual que acompaña (ver rostro.estados).
    - `espera_s`: segundos de pausa DESPUÉS de hablar, para que la persona
      siga el ritmo. Es la parte que un modelo no puede garantizar.
    - `escuchar_despues`: si debe abrirse el micrófono al terminar el paso.
    - `terminada`: último paso de la actividad.
    """

    texto: str
    estado_rostro: str = "hablando"
    espera_s: float = 0.0
    escuchar_despues: bool = False
    terminada: bool = False


class Actividad(Protocol):
    nombre: str
    titulo: str

    def iniciar(self) -> Paso: ...

    def avanzar(self, entrada: str | None = None) -> Paso: ...

    def cancelar(self) -> Paso: ...

    @property
    def activa(self) -> bool: ...
