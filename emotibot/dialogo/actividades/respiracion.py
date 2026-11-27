"""Respiración guiada 4-4-6, con temporización real.

Voluntaria, breve y general. No es una intervención clínica y no se presenta
como tal: es una pausa guiada, del tipo que cualquiera puede hacer solo, con
la ventaja de que el robot marca el ritmo y la persona no tiene que contar.
"""
from __future__ import annotations

from .base import Paso

INHALAR_S = 4.0
SOSTENER_S = 4.0
EXHALAR_S = 6.0
CICLOS_POR_DEFECTO = 4
# Ritmos que ofrece la configuración (inhalar-sostener-exhalar). Solo estos.
RITMOS = {"4-4-6": (4.0, 4.0, 6.0), "3-3-5": (3.0, 3.0, 5.0), "5-5-7": (5.0, 5.0, 7.0)}
_NUMEROS = {3: "tres", 4: "cuatro", 5: "cinco"}


class Respiracion:
    nombre = "respiracion"
    titulo = "Respiración guiada"

    def __init__(self, ciclos: int = CICLOS_POR_DEFECTO,
                 ritmo: tuple[float, float, float] = (INHALAR_S, SOSTENER_S, EXHALAR_S)) -> None:
        self.ciclos = max(1, min(10, int(ciclos)))
        self.inhalar_s, self.sostener_s, self.exhalar_s = ritmo
        self._ciclo = 0
        self._fase = 0
        self._activa = False

    @property
    def activa(self) -> bool:
        return self._activa

    def iniciar(self) -> Paso:
        self._activa = True
        self._ciclo = 0
        self._fase = 0
        return Paso(
            texto=(
                f"Vamos a respirar juntos {self.ciclos} veces. Si en algún "
                "momento quieres parar, dime para y lo dejamos. Ponte cómodo "
                "y sigue mi voz."
            ),
            estado_rostro="respirando",
            espera_s=1.5,
        )

    def avanzar(self, entrada: str | None = None) -> Paso:
        if not self._activa:
            return Paso(texto="", terminada=True)

        if self._ciclo >= self.ciclos:
            self._activa = False
            return Paso(
                texto=(
                    "Listo. Nota cómo estás ahora, sin juzgarlo. "
                    "Si te vino bien, puedes repetirlo cuando quieras."
                ),
                estado_rostro="feliz",
                espera_s=0.5,
                terminada=True,
            )

        fase = self._fase
        self._fase = (self._fase + 1) % 3
        if self._fase == 0:
            self._ciclo += 1

        if fase == 0:
            return Paso(
                texto=f"Inhala por la nariz, contando {_NUMEROS[int(self.inhalar_s)]}.",
                estado_rostro="respirando_inhalar",
                espera_s=self.inhalar_s,
            )
        if fase == 1:
            return Paso(
                texto="Sostén el aire.",
                estado_rostro="respirando_sostener",
                espera_s=self.sostener_s,
            )
        restantes = self.ciclos - self._ciclo
        cola = "" if restantes else " Una más y terminamos."
        return Paso(
            texto=f"Suelta el aire despacio por la boca.{cola}",
            estado_rostro="respirando_exhalar",
            espera_s=self.exhalar_s,
        )

    def cancelar(self) -> Paso:
        self._activa = False
        return Paso(
            texto="Lo dejamos aquí. Hiciste bien en intentarlo.",
            estado_rostro="reposo",
            terminada=True,
        )
