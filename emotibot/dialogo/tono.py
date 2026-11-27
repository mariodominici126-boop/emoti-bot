"""¿La persona está contando algo que le pesa? Detección LOCAL, solo para la
cara: mientras alguien cuenta un problema, el robot no sonríe (neutro y
atento). No decide nada del diálogo ni de la seguridad (eso es la guardia),
no se registra y no sale del equipo.
"""
from __future__ import annotations

import re

from ..texto import normalizar

_MALESTAR = re.compile(
    r"\b(?:mal\s+dia|me\s+fue\s+mal|estoy\s+mal|me\s+siento\s+\w+|triste\w*|deprimid\w*|"
    r"angusti\w*|ansied\w*|ansios\w*|agobi\w*|estresad\w*|preocupad\w*|llor\w*|"
    r"me\s+duele|no\s+se\s+que\s+hacer|cosas\s+malas|problema\w*|discut\w*|pelea\w*|"
    r"me\s+grit\w*|humill\w*|harto|harta|frustrad\w*|miedo|nervios\w*|me\s+siento\s+sol[oa]|"
    r"no\s+lo\s+se|no\s+se\b|tonto|tonta|fatal|horrible|duro|dificil)\b"
)
_ALIVIO = re.compile(r"\b(?:me\s+fue\s+bien|estoy\s+bien|genial|content[oa]|feliz|"
                     r"buena\s+noticia|ya\s+estoy\s+mejor|me\s+siento\s+mejor)\b")
# Turnos que la cara sigue neutra tras la última señal de malestar.
TURNOS_DE_MALESTAR = 3


def senal(texto: str) -> str:
    """«malestar», «alivio» o ""."""
    plano = normalizar(texto)
    if _ALIVIO.search(plano):
        return "alivio"
    if _MALESTAR.search(plano):
        return "malestar"
    return ""
