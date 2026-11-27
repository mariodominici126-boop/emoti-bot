"""Respaldo de voz con espeak-ng. Robótica, pero siempre disponible."""
from __future__ import annotations

import shutil
import subprocess
from typing import Iterator

from .. import registro
from ..audio import senal
from . import base

log = registro.obtener("voz.espeak")

FRECUENCIA = 22050
_TIEMPO_LIMITE = 20


class ErrorEspeak(RuntimeError):
    pass


class VozEspeak:
    nombre = "espeak-ng"

    def __init__(self, velocidad: int = 150, max_caracteres: int = 700) -> None:
        if shutil.which("espeak-ng") is None:
            raise ErrorEspeak("espeak-ng no está instalado.")
        self.velocidad = max(80, min(260, int(velocidad)))
        self.max_caracteres = max_caracteres
        self.frecuencia = FRECUENCIA

    def _pcm_de(self, frase: str) -> bytes:
        # --stdout escribe un WAV en la salida estándar; el texto va como
        # argumento de una lista, nunca por una shell.
        resultado = subprocess.run(
            ["espeak-ng", "-v", "es", "-s", str(self.velocidad), "--stdout", frase],
            capture_output=True, timeout=_TIEMPO_LIMITE, check=False,
        )
        if resultado.returncode != 0 or len(resultado.stdout) < 64:
            detalle = resultado.stderr.decode("utf-8", "replace")[:160].strip()
            raise ErrorEspeak(detalle or "espeak-ng no generó audio.")
        pcm, frecuencia = senal.de_wav(resultado.stdout)
        self.frecuencia = frecuencia or FRECUENCIA
        return pcm

    def sintetizar(self, texto: str) -> Iterator[bytes]:
        for frase in base.partir_en_frases(
            base.limpiar(texto, self.max_caracteres)
        ):
            try:
                pcm = self._pcm_de(frase)
            except subprocess.TimeoutExpired as exc:
                raise ErrorEspeak("espeak-ng tardó demasiado.") from exc
            if pcm:
                yield pcm

    def cerrar(self) -> None:
        return None
