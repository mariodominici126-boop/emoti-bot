"""Selección del motor de reconocimiento de voz."""
from __future__ import annotations

from .. import registro
from ..ajustes import Ajustes
from .base import ErrorStt, Transcripcion, Transcriptor
from .remoto import SttRemoto
from .whisper_local import WhisperLocal

log = registro.obtener("stt")

__all__ = ["ErrorStt", "SinTranscriptor", "Transcripcion", "Transcriptor", "crear"]


class SinTranscriptor:
    """Sin reconocimiento: el robot sigue abriendo y las actividades funcionan.

    Es un estado honesto, no un error: se le dice a la persona que ahora mismo
    no puede entender voz, en lugar de grabar audio que no va a servir.
    """

    nombre = "ninguno"

    def disponible(self) -> bool:
        return False

    def transcribir(self, pcm: bytes, frecuencia: int) -> Transcripcion:
        raise ErrorStt("No hay motor de reconocimiento de voz instalado.")

    def cerrar(self) -> None:
        return None


def crear(config: Ajustes, proveedor_remoto=None) -> Transcriptor:
    preferencia = (config.stt.motor or "auto").lower()

    if preferencia in ("auto", "whisper"):
        try:
            return WhisperLocal(config.stt)
        except ErrorStt as exc:
            nivel = log.warning if preferencia == "whisper" else log.info
            nivel("Whisper local no disponible (%s).", exc)

    if preferencia in ("auto", "remoto") and proveedor_remoto is not None:
        log.info("Uso reconocimiento remoto como respaldo (consume cuota).")
        return SttRemoto(proveedor_remoto, config.stt.idioma)

    log.warning("Sin reconocimiento de voz: solo actividades y teclado.")
    return SinTranscriptor()
