"""Selección del sintetizador disponible, con degradación ordenada."""
from __future__ import annotations

import json
from typing import Iterator

from .. import ajustes as mod_ajustes
from .. import registro, rutas
from .base import Sintetizador, limpiar, partir_en_frases
from .espeak import ErrorEspeak, VozEspeak
from .piper import ErrorPiper, VozPiper

log = registro.obtener("voz")

__all__ = ["Sintetizador", "crear", "limpiar", "partir_en_frases", "VozSilenciosa"]


class VozSilenciosa:
    """Sin motor de voz: la interfaz sigue funcionando, pero en silencio.

    Existe para que la ausencia de Piper y de espeak-ng no impida arrancar el
    robot: el rostro, las actividades y los textos en pantalla siguen activos.
    """

    nombre = "silenciosa"
    frecuencia = 22050

    def sintetizar(self, texto: str) -> Iterator[bytes]:
        return iter(())

    def cerrar(self) -> None:
        return None


def _velocidad_empaquetada() -> float:
    """La velocidad medida de la voz empaquetada (config/voces/claude.json)."""
    try:
        datos = json.loads((rutas.CONFIG_REPO / "voces" / "claude.json").read_text(encoding="utf-8"))
        return float(datos["velocidad"])
    except (OSError, ValueError, KeyError, TypeError):
        return 0.71


def crear(config: mod_ajustes.Ajustes) -> Sintetizador:
    preferencia = (config.voz.motor or "auto").lower()
    ruta = mod_ajustes.ruta_piper(config)

    if preferencia in ("auto", "piper"):
        try:
            return VozPiper(ruta, config.voz.max_caracteres,
                            config.voz.velocidad * config.voz.ajuste_velocidad)
        except ErrorPiper as exc:
            nivel = log.warning if preferencia == "piper" else log.info
            nivel("Piper no disponible (%s).", exc)
        # La voz elegida no está (p. ej. Daniela aún sin bajar): la que viaja
        # dentro del paquete antes que espeak-ng, que en un Windows limpio no
        # existe y dejaría al robot mudo.
        empaquetada = mod_ajustes.ruta_piper_empaquetada()
        if empaquetada is not None and empaquetada != ruta:
            try:
                voz = VozPiper(empaquetada, config.voz.max_caracteres,
                               _velocidad_empaquetada() * config.voz.ajuste_velocidad)
                log.info("Uso la voz empaquetada (%s) como respaldo.", empaquetada.name)
                return voz
            except ErrorPiper as exc:
                log.warning("La voz empaquetada tampoco carga (%s).", exc)

    if preferencia in ("auto", "espeak"):
        try:
            voz = VozEspeak(round(config.voz.velocidad_espeak / config.voz.ajuste_velocidad),
                            config.voz.max_caracteres)
            log.info("Uso espeak-ng como voz.")
            return voz
        except ErrorEspeak as exc:
            log.warning("espeak-ng no disponible (%s).", exc)

    log.warning("Sin motor de voz: EMOTI-BOT funcionará en silencio.")
    return VozSilenciosa()
