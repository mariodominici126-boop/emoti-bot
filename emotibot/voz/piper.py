"""Síntesis neuronal local con Piper, frase a frase.

Mejora frente al prototipo: la versión 0.6 construía el WAV COMPLETO de toda
la respuesta en memoria y solo entonces lo pasaba a `aplay`. El tiempo de esa
síntesis no se medía en ningún sitio y se pagaba íntegro antes del primer
sonido. Aquí cada frase se sintetiza y se entrega por separado, de modo que la
primera empieza a sonar mientras la siguiente se genera.
"""
from __future__ import annotations

import io
import wave
from pathlib import Path
from typing import Iterator

from .. import registro
from ..audio import senal
from . import base

log = registro.obtener("voz.piper")

FRECUENCIA_SUPUESTA = 22050


class ErrorPiper(RuntimeError):
    pass


class VozPiper:
    nombre = "piper"

    def __init__(self, modelo: Path, max_caracteres: int = 700,
                 velocidad: float = 1.0) -> None:
        self.modelo = modelo
        self.max_caracteres = max_caracteres
        # length_scale es el inverso de la velocidad: menor = habla más
        # rápido. Se acota para no llegar a un resultado ininteligible.
        self.length_scale = max(0.55, min(1.6, float(velocidad) or 1.0))
        if not modelo.is_file():
            raise ErrorPiper(f"No encontré el modelo de voz en {modelo}")
        try:
            from piper import PiperVoice  # import tardío: es opcional
        except ImportError as exc:
            raise ErrorPiper("piper-tts no está instalado.") from exc
        try:
            self._voz = PiperVoice.load(str(modelo))
        except Exception as exc:
            raise ErrorPiper(f"Piper no pudo cargar el modelo: {exc}") from exc
        self._config_sintesis = self._preparar_velocidad()
        self.frecuencia = self._descubrir_frecuencia()
        log.info("Piper listo (%s, %d Hz, velocidad %.2f).",
                 modelo.name, self.frecuencia, self.length_scale)

    def _preparar_velocidad(self):
        """Ajusta la velocidad del habla según la versión de piper-tts.

        Las versiones recientes aceptan un `SynthesisConfig` por llamada; las
        antiguas solo tienen el valor en la configuración de la voz. Se
        intentan las dos y, si ninguna funciona, se habla a velocidad normal
        en lugar de fallar.
        """
        if abs(self.length_scale - 1.0) < 0.01:
            return None
        try:
            from piper import SynthesisConfig  # type: ignore
            return SynthesisConfig(length_scale=self.length_scale)
        except Exception:
            pass
        config = getattr(self._voz, "config", None)
        if config is not None and hasattr(config, "length_scale"):
            try:
                config.length_scale = self.length_scale
                return None
            except Exception:
                pass
        log.info("Esta versión de piper-tts no deja ajustar la velocidad.")
        return None

    def _descubrir_frecuencia(self) -> int:
        """La ruta del atributo cambia entre versiones de piper-tts."""
        for ruta in (("config", "sample_rate"), ("sample_rate",),
                     ("config", "audio", "sample_rate")):
            objeto: object = self._voz
            for paso in ruta:
                objeto = getattr(objeto, paso, None)
                if objeto is None:
                    break
            if isinstance(objeto, int) and 8000 <= objeto <= 48000:
                return objeto
        # Último recurso: sintetizar una muestra mínima y leer su cabecera.
        try:
            _, frecuencia = senal.de_wav(self._wav_de("Hola."))
            return frecuencia
        except Exception:
            log.warning("No pude determinar la frecuencia de Piper; asumo %d Hz.",
                        FRECUENCIA_SUPUESTA)
            return FRECUENCIA_SUPUESTA

    def _escribir_wav(self, texto: str, config) -> bytes:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as destino:
            if config is not None:
                self._voz.synthesize_wav(texto, destino, syn_config=config)
            else:
                self._voz.synthesize_wav(texto, destino)
        return buffer.getvalue()

    def _wav_de(self, texto: str) -> bytes:
        if self._config_sintesis is not None:
            try:
                return self._escribir_wav(texto, self._config_sintesis)
            except TypeError:
                # Esta versión de piper-tts no acepta el parámetro: se deja
                # de usar y se sigue a velocidad normal.
                log.info("piper-tts no acepta syn_config; velocidad normal.")
                self._config_sintesis = None
        return self._escribir_wav(texto, None)

    def sintetizar(self, texto: str) -> Iterator[bytes]:
        for frase in base.partir_en_frases(
            base.limpiar(texto, self.max_caracteres)
        ):
            try:
                pcm, _ = senal.de_wav(self._wav_de(frase))
            except Exception as exc:
                log.error("Piper falló en una frase: %s", exc)
                raise ErrorPiper(str(exc)) from exc
            if pcm:
                yield pcm

    def cerrar(self) -> None:
        self._voz = None
