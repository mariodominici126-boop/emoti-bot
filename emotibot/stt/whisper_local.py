"""Reconocimiento de voz local con faster-whisper.

Es el cambio de arquitectura con más palanca del proyecto: separar el
reconocimiento del razonamiento. Consecuencias:

- Al proveedor remoto solo le llega texto, no audio. El consumo por turno baja
  de forma drástica.
- El audio NO sale del dispositivo. La afirmación de privacidad del proyecto
  pasa de dudosa a defendible: se transmite texto, no la voz de la persona.
- El reconocimiento sigue funcionando sin Internet.

Expectativa realista en Raspberry Pi 5, según mediciones publicadas: el modelo
`tiny` responde por debajo del segundo en frases cortas y `base` entre uno y
dos segundos, con bastante mejor precisión. `small` ya va por debajo del
tiempo real y no sirve para conversar.

Contrapartida honesta: Whisper en español con un micrófono mediocre cometerá
errores de transcripción que antes absorbía el modelo remoto al oír el audio
directamente. Hay que medirlo, no suponerlo.

El audio se pasa en memoria; este módulo nunca escribe audio a disco.

Se entrega como arreglo de numpy, no como WAV. La razón no es solo velocidad:
si se pasa un archivo o un objeto tipo archivo, faster-whisper lo decodifica
con PyAV, y las versiones recientes de PyAV ya no aceptan el argumento
`metadata_errors` que faster-whisper les pasa. El fallo que se ve es:

    Whisper falló: open() got an unexpected keyword argument 'metadata_errors'

Nuestra captura ya es exactamente lo que Whisper espera —PCM mono de 16 bits a
16 kHz—, así que convertirla a float32 y entregarla directamente salta el
decodificador por completo. Sin fijar versiones y sin la ida y vuelta por WAV.
"""
from __future__ import annotations

import io
import time

from .. import registro
from .. import descargas
from ..agentes_opcionales import importar_opcional
from ..ajustes import AjustesStt
from ..audio import senal
from .base import ErrorStt, Transcripcion

log = registro.obtener("stt.whisper")


PISTA_NOMBRE = "Emoti, Emoti-Bot."


class WhisperLocal:
    nombre = "whisper-local"

    def __init__(self, config: AjustesStt, modelo: str | None = None,
                 pista: str | None = None) -> None:
        """`modelo`: el de la conversación si no se dice otro. `pista`: texto
        que orienta a Whisper (solo el despertar la usa: en la conversación
        la pista del nombre rompía otras frases, ver bitácora 27-11)."""
        modulo = importar_opcional("faster_whisper")
        if modulo is None:
            raise ErrorStt(
                "faster-whisper no está instalado "
                "(pip install faster-whisper)."
            )
        self.config = config
        self.modelo = modelo or config.modelo_whisper
        self.pista = pista
        inicio = time.monotonic()
        try:
            # Dentro del paquete va «small» (la conversación): se carga de su
            # carpeta, sin red. Los demás, por nombre (caché o descarga).
            empaquetado = descargas.whisper_empaquetado(self.modelo)
            self._modelo = modulo.WhisperModel(
                str(empaquetado) if empaquetado else self.modelo,
                device="cpu",
                compute_type=config.computo_whisper,
            )
        except Exception as exc:
            raise ErrorStt(f"No pude cargar el modelo Whisper: {exc}") from exc
        self._np = importar_opcional("numpy")
        if self._np is None:
            log.warning(
                "numpy no disponible: el audio irá como WAV y lo decodificará "
                "PyAV, que puede fallar según su versión."
            )
        log.info(
            "Whisper '%s' (%s%s) cargado en %.1f s.",
            self.modelo, config.computo_whisper, ", con pista" if pista else "",
            time.monotonic() - inicio,
        )

    FRECUENCIA_WHISPER = 16000

    def _preparar(self, pcm: bytes, frecuencia: int):
        """PCM 16 bits → float32 en [-1, 1] a 16 kHz, o WAV si falta numpy."""
        np = self._np
        if np is None:
            return io.BytesIO(senal.a_wav(pcm, frecuencia))

        muestras = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
        muestras /= 32768.0
        if frecuencia != self.FRECUENCIA_WHISPER and muestras.size:
            # Interpolación lineal. Basta para voz y evita otra dependencia;
            # de todos modos la captura ya trabaja a 16 kHz.
            destino = int(round(muestras.size * self.FRECUENCIA_WHISPER
                                / frecuencia))
            if destino > 0:
                muestras = np.interp(
                    np.linspace(0.0, muestras.size - 1, destino,
                                dtype=np.float32),
                    np.arange(muestras.size, dtype=np.float32),
                    muestras,
                ).astype(np.float32)
        return np.ascontiguousarray(muestras)

    def disponible(self) -> bool:
        return self._modelo is not None

    def transcribir(self, pcm: bytes, frecuencia: int) -> Transcripcion:
        if not pcm:
            return Transcripcion("", self.nombre)
        inicio = time.monotonic()
        audio = self._preparar(pcm, frecuencia)
        try:
            segmentos, _ = self._modelo.transcribe(
                audio,
                language=self.config.idioma,
                beam_size=1,            # el haz amplio no compensa en CPU
                vad_filter=False,       # el VAD propio ya recortó el audio
                condition_on_previous_text=False,
                # La pista del nombre, SOLO en el despertar: con base arregla
                # «Emoti» (27/28 frente a 11/28), pero en la conversación
                # rompía «no sé qué hacer» → «no se cace» (corpus, 27-11).
                initial_prompt=self.pista,
            )
            texto = " ".join(segmento.text.strip() for segmento in segmentos).strip()
        except TypeError as exc:
            if "metadata_errors" in str(exc):
                raise ErrorStt(
                    "PyAV y faster-whisper no son compatibles en esta "
                    "instalación. Instala numpy para que el audio no pase "
                    "por PyAV: pip install numpy"
                ) from exc
            raise ErrorStt(f"Whisper falló: {exc}") from exc
        except Exception as exc:
            raise ErrorStt(f"Whisper falló: {exc}") from exc
        return Transcripcion(
            texto=texto,
            motor=self.nombre,
            segundos=time.monotonic() - inicio,
            idioma=self.config.idioma,
        )

    def cerrar(self) -> None:
        self._modelo = None
