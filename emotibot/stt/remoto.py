"""Reconocimiento remoto: respaldo cuando no hay Whisper local.

Conserva la capacidad del prototipo (enviar audio al modelo) pero de forma
explícita y acotada: solo transcribe, y el presupuesto cuenta cada llamada
igual que cualquier otra. No es el camino preferido, porque el audio cuesta
mucho más que el texto y porque manda la voz de la persona a un tercero.
"""
from __future__ import annotations

import time

from .. import registro
from ..audio import senal
from ..ia.base import ErrorProveedor
from .base import ErrorStt, Transcripcion

log = registro.obtener("stt.remoto")


class SttRemoto:
    nombre = "remoto"

    def __init__(self, proveedor_remoto, idioma: str = "es") -> None:
        self._proveedor = proveedor_remoto
        self.idioma = idioma

    def disponible(self) -> bool:
        return bool(self._proveedor) and self._proveedor.disponible()

    def transcribir(self, pcm: bytes, frecuencia: int) -> Transcripcion:
        if not pcm:
            return Transcripcion("", self.nombre)
        inicio = time.monotonic()
        wav = senal.a_wav(pcm, frecuencia)
        log.info("Transcripción remota de %.1f KiB de audio.", len(wav) / 1024)
        try:
            texto = self._proveedor.transcribir(wav, self.idioma)
        except ErrorProveedor as exc:
            raise ErrorStt(exc.mensaje_usuario()) from exc
        return Transcripcion(
            texto=texto,
            motor=self.nombre,
            segundos=time.monotonic() - inicio,
            idioma=self.idioma,
        )

    def cerrar(self) -> None:
        return None
