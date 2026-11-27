"""Estado de animación SIN dibujar, reutilizando la `Cara` de producción.

El prototipo no reimplementa la animación: parpadeo, sacadas, interpolación
y la composición estado funcional + expresión (A1) son exactamente los de
`emotibot/rostro/cara.py`. Así la comparación A/B compara SOLO el dibujo.

Se llama a tres métodos internos de `Cara`. Es aceptable en un prototipo y
evita tocar el rostro de producción; si se adoptara este motor, esa lógica
pasaría a una clase propia y compartida.
"""
from __future__ import annotations

import time

from emotibot.rostro.cara import Cara
from emotibot.rostro.paleta import PALETA


class _LienzoNulo:
    """Lo mínimo para construir una `Cara` que nunca dibuja."""

    def winfo_width(self):
        return 800

    def winfo_height(self):
        return 480


class Animador:
    def __init__(self, paleta=PALETA) -> None:
        self.cara = Cara(_LienzoNulo(), paleta)
        self._ultimo = time.monotonic()
        self.inicio = self._ultimo

    # Las mismas entradas que la Cara de producción.
    def fijar(self, funcional=None, expresion=None) -> None:
        self.cara.fijar(funcional=funcional, expresion=expresion)

    def fijar_estado(self, nombre: str) -> None:
        self.cara.fijar_estado(nombre)

    def fijar_nivel_voz(self, nivel: float) -> None:
        self.cara.fijar_nivel_voz(nivel)

    def fijar_nivel_escucha(self, nivel: float) -> None:
        self.cara.fijar_nivel_escucha(nivel)

    def asentar(self) -> None:
        self.cara.asentar()

    def avanzar(self, ahora: float | None = None) -> float:
        """Avanza la animación hasta `ahora`. Devuelve t desde el inicio."""
        ahora = time.monotonic() if ahora is None else ahora
        delta = min(0.25, max(0.001, ahora - self._ultimo))
        self._ultimo = ahora
        self.cara._actualizar_parpadeo(ahora)
        self.cara._actualizar_mirada(ahora, delta)
        self.cara._acercar_a_expresion(delta)
        return ahora - self.inicio

    @property
    def anim(self):
        return self.cara._anim

    @property
    def expresion(self):
        return self.cara._expresion
