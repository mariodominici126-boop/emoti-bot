"""Qué hacer con una respuesta que llegó cortada por el tope de tokens.

Fase 1, A2. **Política PROVISIONAL**: la decisión §13.8a corresponde al
responsable y sigue abierta. Mientras tanto se aplica la opción
conservadora: recortar a la última frase completa y no añadir nada. Si no
queda ninguna frase completa, se usa el respaldo local.

Es determinista, no gasta cuota y no añade latencia: no se reintenta con más
tokens ni se pregunta a otro proveedor, porque eso duplicaría gasto y espera.

Reversión: un solo ajuste, `ia.politica_truncado` en `config/ajustes.json`.

- "recortar" (provisional, por defecto): lo descrito arriba.
- "ninguna": comportamiento de la v1.7. Se pronuncia tal cual llegó, y solo
  se cuenta. Si llegó vacía, también se usa el respaldo local, porque no hay
  nada que pronunciar.
"""
from __future__ import annotations

import re
from dataclasses import replace

from .base import Respuesta

RECORTAR = "recortar"
NINGUNA = "ninguna"
POLITICAS = (RECORTAR, NINGUNA)
POR_DEFECTO = RECORTAR

# Fin de frase: . ! ? o … seguido de comillas o paréntesis de cierre
# opcionales, y después espacio o final del texto. Que haga falta el espacio
# evita cortar en «3.5» o en «v1.8». Abreviaturas como «Sr.» se tomarían por
# fin de frase; en el peor caso se recorta de más, nunca se deja una frase
# a medias.
_FIN_DE_FRASE = re.compile(r"[.!?…]+[\"'»”’)\]]*(?=\s|$)")


def recortar_a_frase_completa(texto: str) -> str:
    """Devuelve el texto hasta la última frase completa, o "" si no hay."""
    limpio = (texto or "").rstrip()
    final = None
    for coincidencia in _FIN_DE_FRASE.finditer(limpio):
        final = coincidencia.end()
    if final is None:
        return ""
    return limpio[:final].strip()


def aplicar(respuesta: Respuesta, politica: str = POR_DEFECTO) -> Respuesta | None:
    """Trata una respuesta truncada. None significa «usar el respaldo local».

    Una respuesta que no está truncada se devuelve sin tocar.
    """
    if not respuesta.truncada:
        return respuesta
    politica = politica if politica in POLITICAS else POR_DEFECTO
    if politica == NINGUNA:
        return respuesta if respuesta.texto.strip() else None

    recortado = recortar_a_frase_completa(respuesta.texto)
    if not recortado:
        return None
    if recortado == respuesta.texto.strip():
        return respuesta
    return replace(respuesta, texto=recortado, recortada=True)
