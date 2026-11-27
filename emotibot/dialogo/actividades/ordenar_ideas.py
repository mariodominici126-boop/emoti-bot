"""Ordenar ideas en tres pasos fijos.

El robot conduce; la persona decide. Las tres preguntas son siempre las mismas
y están escritas a mano, así que la actividad funciona sin conexión y sin
cuota, y se puede evaluar: ¿la gente llega al tercer paso?

Decisión deliberada: el robot NO repite de vuelta lo que la persona dijo.
Reflejar y amplificar el malestar no ayuda; lo que ayuda aquí es avanzar hacia
algo concreto y dejar la decisión en manos de la persona.
"""
from __future__ import annotations

from .base import Paso

PREGUNTAS = (
    ("Cuéntame en una o dos frases qué pasó. Sin detalles, lo esencial.",
     "escuchando"),
    ("De todo eso, ¿qué parte está en tus manos y qué parte no?",
     "escuchando"),
    ("¿Cuál sería un primer paso pequeño, algo que puedas hacer hoy o mañana?",
     "escuchando"),
)

PUENTES = (
    "Bien. Siguiente pregunta.",
    "Entendido. Vamos con la última.",
)


class OrdenarIdeas:
    nombre = "ordenar_ideas"
    titulo = "Ordenar ideas"

    def __init__(self) -> None:
        self._indice = 0
        self._activa = False
        self._respuestas: list[str] = []

    @property
    def activa(self) -> bool:
        return self._activa

    def iniciar(self) -> Paso:
        self._activa = True
        self._indice = 0
        self._respuestas = []
        pregunta, estado = PREGUNTAS[0]
        return Paso(
            texto=(
                "Vamos a ordenarlo en tres preguntas. Tú decides qué contestar "
                f"y puedes parar cuando quieras. {pregunta}"
            ),
            estado_rostro=estado,
            escuchar_despues=True,
        )

    def avanzar(self, entrada: str | None = None) -> Paso:
        if not self._activa:
            return Paso(texto="", terminada=True)

        if entrada and entrada.strip():
            self._respuestas.append(entrada.strip())
        self._indice += 1

        if self._indice < len(PREGUNTAS):
            pregunta, estado = PREGUNTAS[self._indice]
            puente = PUENTES[min(self._indice - 1, len(PUENTES) - 1)]
            return Paso(
                texto=f"{puente} {pregunta}",
                estado_rostro=estado,
                escuchar_despues=True,
            )

        self._activa = False
        if len(self._respuestas) >= 3:
            cierre = (
                "Lo dejamos ahí: ya tienes un primer paso concreto. Te sugiero "
                "escribirlo en algún lugar donde lo vayas a ver."
            )
        else:
            cierre = (
                "Lo dejamos ahí. Aunque no completáramos las tres, ya es algo "
                "haberlo puesto en palabras."
            )
        return Paso(texto=cierre, estado_rostro="feliz", terminada=True)

    def cancelar(self) -> Paso:
        self._activa = False
        return Paso(
            texto="Lo dejamos. Cuando quieras retomarlo, me lo dices.",
            estado_rostro="reposo",
            terminada=True,
        )
