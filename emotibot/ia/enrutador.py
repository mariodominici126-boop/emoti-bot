"""Elige qué modelo contesta cada turno.

Dos modelos con papeles distintos:

- **conversación**: escuchar, acompañar y responder rápido. Es el camino
  normal, y la latencia importa más que la profundidad.
- **razonamiento**: comparar, analizar, calcular, decidir. Vale la pena
  esperar un poco más y gastar más tokens.

La decisión se toma en el dispositivo, con patrones, antes de llamar a nadie:
preguntarle a un modelo cuál de los dos modelos usar costaría una consulta
entera y añadiría justo la latencia que se quiere evitar.

Ante la duda, conversación: equivocarse hacia el modelo rápido se nota menos
que hacer esperar a alguien que solo dijo «hola».
"""
from __future__ import annotations

import re

from ..texto import normalizar, palabras

CONVERSACION = "conversacion"
RAZONAMIENTO = "razonamiento"

# Pedir explícitamente un análisis, una comparación o una decisión.
_MARCAS_RAZONAMIENTO = (
    r"\bpor\s+que\b", r"\bpor\s+qu\b",
    r"\bexplica\w*\b", r"\bexplicame\b",
    r"\bcompara\w*\b", r"\bdiferencia[s]?\s+entre\b",
    r"\banaliza\w*\b", r"\bcalcula\w*\b", r"\bresuelve\b",
    r"\bcual\s+(?:es\s+)?(?:el\s+|la\s+)?mejor\b",
    r"\bventajas?\b", r"\bdesventajas?\b", r"\bpros\s+y\s+contras\b",
    r"\bpaso\s+a\s+paso\b",
    r"\bayudame\s+a\s+(?:decidir|elegir|pensar|resolver|entender)\b",
    r"\bque\s+pasaria\s+si\b", r"\bque\s+harias\s+(?:tu\s+)?si\b",
    r"\bcomo\s+funciona\b", r"\bcomo\s+puedo\b", r"\bcomo\s+hago\b",
    r"\bconviene\b", r"\bme\s+recomiendas\b", r"\bdeberia\b",
    r"\bno\s+se\s+si\b.*\bo\b",     # dudar entre dos opciones
    r"\bque\s+hago\s+con\b", r"\bmerece\s+la\s+pena\b",
    r"\bplanifica\w*\b", r"\borganiza\w*\s+un\b",
    r"\bcuanto\s+(?:es|seria|cuesta|tarda)\b",
    r"\bdemuestra\b", r"\bjustifica\b",
)
_RE_RAZONAMIENTO = tuple(re.compile(p) for p in _MARCAS_RAZONAMIENTO)

# Charla corriente: aunque la frase sea larga, no pide análisis.
_MARCAS_CHARLA = (
    r"^\s*(?:hola|buenas|que\s+tal|como\s+estas|adios|gracias|hasta\s+luego)",
    r"\bcomo\s+(?:te\s+llamas|estas|te\s+sientes)\b",
    r"\bquien\s+eres\b", r"\bque\s+eres\b",
)
_RE_CHARLA = tuple(re.compile(p) for p in _MARCAS_CHARLA)

PALABRAS_PARA_RAZONAR = 24


def papel(texto: str) -> str:
    """Devuelve CONVERSACION o RAZONAMIENTO para este turno."""
    plano = normalizar(texto)
    if not plano:
        return CONVERSACION
    if any(patron.search(plano) for patron in _RE_CHARLA):
        return CONVERSACION
    if any(patron.search(plano) for patron in _RE_RAZONAMIENTO):
        return RAZONAMIENTO
    # Una intervención larga suele traer contexto que hay que ordenar.
    if palabras(plano) >= PALABRAS_PARA_RAZONAR:
        return RAZONAMIENTO
    return CONVERSACION


def ordenar(orden_base, texto: str) -> list[str]:
    """Pone delante el proveedor que corresponde al papel de este turno."""
    orden = [n for n in orden_base]
    elegido = papel(texto)
    if elegido in orden:
        orden.remove(elegido)
        orden.insert(0, elegido)
    return orden
