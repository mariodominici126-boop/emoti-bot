"""Captura desde el micrófono: VAD, recorte y métricas.

Independiente del sistema operativo: habla con un motor de entrada
(`audio/motores.py`), que en la Raspberry Pi es `arecord` y en Windows o macOS
es PortAudio. Toda la lógica de esta capa es la misma en ambos casos.

Dos mejoras frente al prototipo:

- El aviso "habla cuando quieras" lo emite el detector al entrar en su fase
  ESPERANDO_VOZ, no antes de abrir el micrófono. Mientras calibra, la interfaz
  dice que está calibrando.
- El audio se RECORTA a la parte útil antes de salir de aquí. El prototipo
  enviaba la grabación completa, calibración y cola de silencio incluidas:
  hasta 8 s a 16 kHz/16 bits son ~256 KB por turno, y el audio es con mucha
  diferencia la parte más costosa de una consulta a un modelo remoto.
"""
from __future__ import annotations

import enum
import threading
import time
from dataclasses import dataclass
from typing import Callable

from .. import registro
from ..ajustes import AjustesAudio
from . import motores, senal
from .motores import ErrorMotor
from .vad import DetectorVoz, Fase

log = registro.obtener("audio.captura")

SEGUNDOS_BLOQUE = 0.05  # 50 ms: suficiente para la envolvente y el VAD
PRE_VOZ_S = 0.20        # se conserva un poco antes del primer sonido detectado


class MotivoFin(enum.Enum):
    SILENCIO = "silencio"
    LIMITE = "limite"
    SIN_VOZ = "sin_voz"
    CANCELADO = "cancelado"
    FIJA = "grabacion_fija"


class ErrorCaptura(RuntimeError):
    """Fallo del dispositivo de entrada, no del usuario."""


@dataclass
class Captura:
    pcm: bytes
    frecuencia: int
    motivo: MotivoFin
    duracion_bruta_s: float
    duracion_util_s: float
    t_primera_voz: float
    instante_ultima_voz: float
    detector: DetectorVoz | None = None

    @property
    def hay_voz(self) -> bool:
        return bool(self.pcm) and self.motivo in (
            MotivoFin.SILENCIO, MotivoFin.LIMITE, MotivoFin.FIJA
        )


class Microfono:
    def __init__(self, ajustes: AjustesAudio) -> None:
        self.ajustes = ajustes
        self._bytes_bloque = int(
            ajustes.frecuencia_captura * SEGUNDOS_BLOQUE
        ) * senal.ANCHO_MUESTRA

    # ----------------------------------------------------------- disponibilidad
    def disponible(self) -> bool:
        return motores.hay_entrada(self.ajustes)

    def motor(self) -> str:
        return motores.motor_preferido(self.ajustes)

    def _abrir(self) -> motores.EntradaAudio:
        try:
            entrada = motores.crear_entrada(self.ajustes, self._bytes_bloque)
            entrada.iniciar()
        except ErrorMotor as exc:
            raise ErrorCaptura(str(exc)) from exc
        return entrada

    # ------------------------------------------------------------------ escucha
    def escuchar(
        self,
        cancelar: threading.Event,
        al_cambiar_fase: Callable[[Fase, str], None] | None = None,
        al_nivel: Callable[[float], None] | None = None,
    ) -> Captura:
        """Graba hasta detectar el final de la intervención."""
        detector = DetectorVoz(
            segundos_bloque=SEGUNDOS_BLOQUE,
            ms_asentamiento=self.ajustes.ms_asentamiento,
            ms_calibracion=self.ajustes.ms_calibracion,
            factor_umbral=self.ajustes.factor_umbral,
            piso_umbral_rms=float(self.ajustes.piso_umbral_rms),
            histeresis=self.ajustes.histeresis,
            bloques_confirmacion=self.ajustes.bloques_confirmacion,
            silencio_final_s=self.ajustes.silencio_final_s,
        )

        entrada = self._abrir()
        inicio = time.monotonic()
        bloques: list[bytes] = []
        pendiente = bytearray()
        fase_anunciada: Fase | None = None
        motivo = MotivoFin.LIMITE

        if al_cambiar_fase:
            al_cambiar_fase(detector.fase, detector.mensaje())
            fase_anunciada = detector.fase

        try:
            while True:
                if cancelar.is_set():
                    motivo = MotivoFin.CANCELADO
                    break
                if time.monotonic() - inicio >= self.ajustes.max_audio_s:
                    motivo = (MotivoFin.LIMITE if detector.detecto_voz
                              else MotivoFin.SIN_VOZ)
                    break

                try:
                    datos = entrada.leer(self._bytes_bloque)
                except ErrorMotor as exc:
                    raise ErrorCaptura(str(exc)) from exc
                if not datos:
                    continue
                pendiente.extend(datos)

                termino = False
                while len(pendiente) >= self._bytes_bloque:
                    bloque = bytes(pendiente[: self._bytes_bloque])
                    del pendiente[: self._bytes_bloque]
                    bloques.append(bloque)
                    ahora = time.monotonic()
                    if detector.procesar(bloque, ahora):
                        motivo = MotivoFin.SILENCIO
                        termino = True
                        break
                    if al_nivel and detector.fase in (Fase.ESPERANDO_VOZ,
                                                      Fase.EN_VOZ):
                        al_nivel(senal.nivel_normalizado(bloque))
                    if al_cambiar_fase and detector.fase is not fase_anunciada:
                        fase_anunciada = detector.fase
                        al_cambiar_fase(detector.fase, detector.mensaje())
                if termino:
                    break
        finally:
            entrada.cerrar()

        return self._componer(bloques, inicio, motivo, detector)

    def grabar_fijo(self, cancelar: threading.Event) -> Captura:
        """Respaldo sin detección: duración fija, como la versión 0.4.

        Se implementa leyendo bloques durante N segundos en lugar de delegar
        en `arecord -d`, para que se comporte igual en los dos motores.
        """
        segundos = float(self.ajustes.segundos_grabacion_fija)
        entrada = self._abrir()
        inicio = time.monotonic()
        trozos: list[bytes] = []
        try:
            while time.monotonic() - inicio < segundos:
                if cancelar.is_set():
                    break
                try:
                    datos = entrada.leer(self._bytes_bloque)
                except ErrorMotor as exc:
                    raise ErrorCaptura(str(exc)) from exc
                if datos:
                    trozos.append(datos)
        finally:
            entrada.cerrar()

        pcm = b"".join(trozos)
        fin = time.monotonic()
        if not pcm and not cancelar.is_set():
            raise ErrorCaptura("No se capturó audio del micrófono.")
        return Captura(
            pcm=pcm,
            frecuencia=self.ajustes.frecuencia_captura,
            motivo=MotivoFin.CANCELADO if cancelar.is_set() else MotivoFin.FIJA,
            duracion_bruta_s=fin - inicio,
            duracion_util_s=senal.duracion_s(pcm,
                                             self.ajustes.frecuencia_captura),
            t_primera_voz=0.0,
            instante_ultima_voz=fin,
        )

    # -------------------------------------------------------------- auxiliares
    def _componer(
        self,
        bloques: list[bytes],
        inicio: float,
        motivo: MotivoFin,
        detector: DetectorVoz,
    ) -> Captura:
        bruta = senal.duracion_s(
            b"".join(bloques), self.ajustes.frecuencia_captura
        ) if bloques else 0.0

        if motivo in (MotivoFin.SIN_VOZ, MotivoFin.CANCELADO) \
                or not detector.detecto_voz:
            return Captura(
                pcm=b"",
                frecuencia=self.ajustes.frecuencia_captura,
                motivo=MotivoFin.CANCELADO if motivo is MotivoFin.CANCELADO
                else MotivoFin.SIN_VOZ,
                duracion_bruta_s=bruta,
                duracion_util_s=0.0,
                t_primera_voz=0.0,
                instante_ultima_voz=time.monotonic(),
                detector=detector,
            )

        primera = detector.primera_voz or inicio
        ultima = detector.ultima_voz or time.monotonic()

        # Recorte por índice de bloque, no por marca de tiempo: así no depende
        # de que el audio llegue exactamente a ritmo real.
        bloques_pre = max(0, round(PRE_VOZ_S / SEGUNDOS_BLOQUE))
        bloques_cola = max(0, round(self.ajustes.margen_cola_s
                                    / SEGUNDOS_BLOQUE))
        indice_inicio = detector.indice_primera_voz
        indice_fin = detector.indice_ultima_voz
        if indice_inicio is None or indice_fin is None:
            desde, hasta = 0, len(bloques)
        else:
            desde = max(0, indice_inicio - bloques_pre)
            hasta = min(len(bloques), indice_fin + bloques_cola + 1)
        if hasta <= desde:
            desde, hasta = 0, len(bloques)
        pcm = b"".join(bloques[desde:hasta])

        util = senal.duracion_s(pcm, self.ajustes.frecuencia_captura)
        if bruta > 0:
            log.info(
                "Audio recortado: %.2f s brutos → %.2f s útiles (%.0f%% menos).",
                bruta, util, max(0.0, (1 - util / bruta) * 100),
            )
        return Captura(
            pcm=pcm,
            frecuencia=self.ajustes.frecuencia_captura,
            motivo=motivo,
            duracion_bruta_s=bruta,
            duracion_util_s=util,
            t_primera_voz=max(0.0, primera - inicio),
            instante_ultima_voz=ultima,
            detector=detector,
        )
