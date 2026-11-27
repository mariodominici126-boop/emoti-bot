"""Normalización de texto compartida.

La usan la guardia de seguridad, la detección de intención, el guion local y
el enrutador de modelos. Estaba duplicada en varios sitios y una copia que se
desvía es una fuente silenciosa de fallos: un patrón deja de casar y nadie
entiende por qué.
"""
from __future__ import annotations

import re

_SIN_ACENTOS = str.maketrans("áéíóúüñÁÉÍÓÚÜÑ", "aeiouunAEIOUUN")
_NO_ALFANUMERICO = re.compile(r"[^a-z0-9\s]+")
_ESPACIOS = re.compile(r"\s+")


def normalizar(texto: object) -> str:
    """Minúsculas, sin acentos, sin puntuación y con espacios colapsados."""
    plano = str(texto).lower().translate(_SIN_ACENTOS)
    return _ESPACIOS.sub(" ", _NO_ALFANUMERICO.sub(" ", plano)).strip()


def palabras(texto: object) -> int:
    normalizado = normalizar(texto)
    return len(normalizado.split()) if normalizado else 0
