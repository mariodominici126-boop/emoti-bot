"""Longitud de respuesta por ruta (Fase 1, B5). Ver `config/longitud.json`.

Una cifra por ruta, y todas las piezas mandan desde aquí: el tope de tokens
que se pide, la longitud objetivo que usan el comparador y el medidor, y la
frase de longitud opcional en las instrucciones.

Las rutas locales (actividades, respuestas literales) y la de seguridad no
pasan por aquí: no llaman a ningún modelo y su texto está escrito a mano.

Si el archivo no existe, `cargar()` devuelve un diccionario vacío y cada
proveedor usa su propio `max_tokens`, como en la v1.7. Esa es la reversión.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .. import registro, rutas

log = registro.obtener("ia.longitud")

ARCHIVO = rutas.CONFIG_REPO / "longitud.json"
# Español hablado: ~0,66 palabras por token (120 tokens ≈ 79 palabras) y
# ~2,5 palabras por segundo con la voz actual. Son referencias para el
# diseño y la validación, no mediciones de este dispositivo.
PALABRAS_POR_TOKEN = 0.66
PALABRAS_POR_SEGUNDO = 2.5


@dataclass(frozen=True)
class Ruta:
    max_tokens: int
    palabras_objetivo: int
    instruccion: str = ""

    @property
    def segundos_objetivo(self) -> float:
        return self.palabras_objetivo / PALABRAS_POR_SEGUNDO


def cargar(archivo: Path | None = None) -> dict[str, Ruta]:
    ruta = archivo or ARCHIVO
    if not ruta.is_file():
        return {}
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.error("No pude leer %s (%s): uso los topes de cada proveedor.",
                  ruta.name, exc)
        return {}
    rutas_: dict[str, Ruta] = {}
    for nombre, crudo in (datos.items() if isinstance(datos, dict) else ()):
        if nombre.startswith("_") or not isinstance(crudo, dict):
            continue
        try:
            entrada = Ruta(
                max_tokens=max(16, int(crudo.get("max_tokens", 120))),
                palabras_objetivo=max(1, int(crudo.get("palabras_objetivo", 45))),
                instruccion=str(crudo.get("instruccion", "") or "").strip()[:300],
            )
        except (TypeError, ValueError):
            log.warning("Ruta de longitud «%s» inválida; la ignoro.", nombre)
            continue
        # Coherencia: la longitud objetivo debe caber con holgura en el tope,
        # o el modelo se cortará justo cuando hace lo que se le pide.
        necesarios = entrada.palabras_objetivo / PALABRAS_POR_TOKEN
        if necesarios > entrada.max_tokens * 0.8:
            log.warning(
                "Ruta «%s»: %d palabras objetivo necesitan ~%.0f tokens y el "
                "tope es %d. Se truncarán respuestas.", nombre,
                entrada.palabras_objetivo, necesarios, entrada.max_tokens)
        rutas_[nombre] = entrada
    return rutas_


def para(papel: str, tabla: dict[str, Ruta] | None = None) -> Ruta | None:
    tabla = cargar() if tabla is None else tabla
    return tabla.get(papel)
