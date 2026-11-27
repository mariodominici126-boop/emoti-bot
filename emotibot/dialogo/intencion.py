"""Detección local de intención, sin consumir cuota.

Antes de preguntar a un modelo conviene saber si hace falta preguntarle. La
identidad, las actividades y la cortesía se resuelven aquí, en el dispositivo,
con coste cero y sin depender de la red. Solo lo que es conversación de
verdad llega al orquestador.
"""
from __future__ import annotations

import enum
import re

from .seguridad import normalizar


class Intencion(enum.Enum):
    IDENTIDAD = "identidad"
    CAPACIDADES = "capacidades"
    RESPIRACION = "respiracion"
    ORDENAR_IDEAS = "ordenar_ideas"
    DETENER = "detener"
    DESPEDIDA = "despedida"
    CONVERSACION = "conversacion"
    CONFIGURACION = "configuracion"


_PATRONES: tuple[tuple[Intencion, tuple[str, ...]], ...] = (
    (Intencion.DETENER, (
        r"\b(?:para|detente|basta|ya\s+esta|dejalo|cancela|olvidalo)\b",
        r"\bno\s+quiero\s+seguir\s+(?:con\s+)?(?:esto|el\s+ejercicio)\b",
    )),
    (Intencion.RESPIRACION, (
        r"\brespira\w*\b",
        r"\bejercicio\s+de\s+respiracion\b",
        r"\bayudame\s+a\s+calmarme\b",
        r"\bnecesito\s+calmarme\b",
        r"\bestoy\s+muy\s+(?:nervios\w+|acelerad\w+)\b",
    )),
    (Intencion.ORDENAR_IDEAS, (
        r"\borden\w*\s+(?:mis\s+)?ideas\b",
        r"\baclarar\s+(?:mis\s+)?ideas\b",
        r"\bno\s+se\s+(?:por\s+donde\s+)?empezar\b",
        r"\btengo\s+un\s+lio\s+en\s+la\s+cabeza\b",
        r"\bayudame\s+a\s+pensar\b",
        r"\btengo\s+que\s+decidir\b",
    )),
    (Intencion.IDENTIDAD, (
        r"\bquien\s+eres\b",
        r"\bque\s+eres\b",
        r"\bcomo\s+te\s+llamas\b",
        r"\btu\s+nombre\b",
        r"\bpresentate\b",
        r"\bquien\s+te\s+(?:creo|hizo|programo)\b",
        r"\btu\s+creador\b",
    )),
    (Intencion.CAPACIDADES, (
        r"\bque\s+(?:puedes|sabes)\s+hacer\b",
        r"\bpara\s+que\s+sirves\b",
        r"\ben\s+que\s+me\s+puedes\s+ayudar\b",
        r"\bque\s+opciones\s+(?:hay|tienes)\b",
    )),
    (Intencion.DESPEDIDA, (
        r"\badios\b", r"\bhasta\s+luego\b", r"\bnos\s+vemos\b", r"\bchao\b",
        r"\bme\s+voy\b", r"\bhasta\s+manana\b", r"\bgracias\s+por\s+todo\b",
    )),
    (Intencion.CONFIGURACION, (
        r"\b(?:abr\w*|ensena\w*|muestra\w*|pon\w*|entra\w*\s+(?:a|en)|ir\s+a|"
        r"ve\s+a|quiero\s+(?:ver|cambiar))\s+(?:la\s+|las\s+|los\s+|tu\s+|tus\s+)?"
        r"(?:configuracion|ajustes|preferencias)\b",
        r"^\s*(?:configuracion|ajustes)\s*$",
    )),
)

_COMPILADOS = tuple(
    (intencion, tuple(re.compile(p) for p in patrones))
    for intencion, patrones in _PATRONES
)


# Consultas que se contestan palabra por palabra, sin pasar por el modelo ni
# por el guion. La comparación es estricta sobre el texto ya normalizado: una
# formulación distinta, aunque signifique lo mismo, sigue su curso normal.
_LITERALES: dict[str, str] = {
    "quien es tu padre": "Mi creador es Mario.",
}


def respuesta_literal(texto: str) -> str | None:
    """Devuelve la respuesta fija de una consulta literal, si la hay."""
    return _LITERALES.get(normalizar(texto))


def detectar(texto: str) -> Intencion:
    plano = normalizar(texto)
    if not plano:
        return Intencion.CONVERSACION
    for intencion, patrones in _COMPILADOS:
        if any(patron.search(plano) for patron in patrones):
            return intencion
    return Intencion.CONVERSACION
