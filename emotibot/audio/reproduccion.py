"""Reproducción de voz con dueño único del dispositivo y envolvente real.

Funciona igual en la Raspberry Pi y en Windows: habla con un motor de salida
(`audio/motores.py`), no con `aplay` directamente.

Corrige dos defectos del prototipo:

1. CARRERA DE DATOS. En la versión 0.6 el hilo de voz hacía `voz = proceso`
   mientras el hilo de Tkinter leía y mataba `voz` desde `terminar_voz()`.
   Entre comprobar la cancelación y asignar la variable había una ventana en
   la que quedaba un `aplay` que nadie podía detener: el robot se hablaba
   encima y al salir dejaba el proceso vivo.
   Aquí SOLO el hilo trabajador toca el `Popen`. El resto del programa
   únicamente encola trabajos y mueve un contador de token.

2. ESTADO ADELANTADO. El prototipo emitía "voz_iniciada" antes de
   `communicate()`, así que el rostro decía HABLANDO sin que hubiera sonido.
   Aquí `al_primer_sonido` se dispara en el instante en que el primer bloque
   de PCM entra en el dispositivo (queda el retardo del búfer del sistema,
   que cada motor declara en `latencia_buffer_s`, y está documentado).

Además expone `nivel()`: la energía del audio que se está reproduciendo, para
que la boca del rostro se mueva con la voz real y no con un seno.
"""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable, Iterable

from .. import registro
from ..ajustes import AjustesAudio
from . import motores, senal
from .motores import ErrorMotor

log = registro.obtener("audio.reproduccion")

BYTES_ESCRITURA = 1024          # ~23 ms a 22 kHz: envolvente fluida
_CAIDA_NIVEL = 0.82             # suavizado exponencial de la envolvente


@dataclass
class Trabajo:
    token: int
    fuente: Iterable[bytes]
    frecuencia: int
    al_primer_sonido: Callable[[], None] | None = None
    al_terminar: Callable[[bool], None] | None = None


class Altavoz:
    """Cola de reproducción servida por un único hilo trabajador."""

    def __init__(self, ajustes: AjustesAudio) -> None:
        self.ajustes = ajustes
        self._cola: queue.Queue[Trabajo | None] = queue.Queue()
        self._lock = threading.Lock()
        self._token_vigente = 0
        self._siguiente_token = 1
        self._nivel = 0.0
        self._hablando = False
        # Volumen de la configuración (0-1). La boca sigue al audio ORIGINAL:
        # con el volumen bajo, la cara no deja de hablar.
        self.volumen = max(0.0, min(1.0, float(getattr(ajustes, "volumen", 1.0))))
        self._cerrado = threading.Event()
        # El motor de salida lo crea y lo usa EXCLUSIVAMENTE el hilo
        # trabajador: ni los flujos de PortAudio ni un Popen son seguros si
        # dos hilos los tocan a la vez.
        self._salida: motores.SalidaAudio | None = None
        self._hilo = threading.Thread(
            target=self._trabajar, name="emotibot-altavoz", daemon=True
        )
        self._hilo.start()

    # ------------------------------------------------------------------ estado
    def disponible(self) -> bool:
        return motores.hay_salida(self.ajustes)

    def motor(self) -> str:
        return motores.motor_preferido(self.ajustes)

    def nivel(self) -> float:
        """Energía 0..1 del audio en curso. Seguro desde cualquier hilo."""
        with self._lock:
            return self._nivel

    def hablando(self) -> bool:
        with self._lock:
            return self._hablando

    # ------------------------------------------------------------------ órdenes
    def hablar(
        self,
        fuente: Iterable[bytes],
        frecuencia: int,
        al_primer_sonido: Callable[[], None] | None = None,
        al_terminar: Callable[[bool], None] | None = None,
    ) -> int:
        """Encola audio. `fuente` puede ser un generador: se consume en el
        hilo trabajador, de modo que la síntesis de la frase 2 ocurre mientras
        suena la frase 1."""
        with self._lock:
            token = self._siguiente_token
            self._siguiente_token += 1
            self._token_vigente = token
        self._cola.put(
            Trabajo(token, fuente, frecuencia, al_primer_sonido, al_terminar)
        )
        return token

    def detener(self) -> None:
        """Corta lo que suene y descarta lo pendiente.

        Invalidar el token basta para que el trabajador abandone el trabajo
        actual; además se vacía el búfer del sistema, que de otro modo
        seguiría sonando un instante.
        """
        with self._lock:
            self._token_vigente = self._siguiente_token
            self._siguiente_token += 1
            self._nivel = 0.0
        self._vaciar_cola()

    def cerrar(self) -> None:
        self.detener()
        self._cerrado.set()
        self._cola.put(None)
        self._hilo.join(timeout=2.0)

    # ------------------------------------------------------------- trabajador
    def _vigente(self, token: int) -> bool:
        with self._lock:
            return token == self._token_vigente

    def _vaciar_cola(self) -> None:
        while True:
            try:
                self._cola.get_nowait()
            except queue.Empty:
                return

    def _trabajar(self) -> None:
        while not self._cerrado.is_set():
            trabajo = self._cola.get()
            if trabajo is None:
                break
            if not self._vigente(trabajo.token):
                self._consumir_descartado(trabajo)
                continue
            completo = False
            try:
                completo = self._reproducir(trabajo)
            except Exception as exc:  # el hilo nunca debe morir
                log.error("Fallo al reproducir: %s", registro.redactar(exc))
            finally:
                with self._lock:
                    self._hablando = False
                    self._nivel = 0.0
                if trabajo.al_terminar:
                    try:
                        trabajo.al_terminar(completo)
                    except Exception:
                        log.debug("Error en el callback al_terminar",
                                  exc_info=True)
        self._cerrar_salida()

    @staticmethod
    def _consumir_descartado(trabajo: Trabajo) -> None:
        """Agota el generador de un trabajo obsoleto para liberar recursos."""
        try:
            for _ in trabajo.fuente:
                break
        except Exception:
            pass
        if trabajo.al_terminar:
            try:
                trabajo.al_terminar(False)
            except Exception:
                pass

    def _asegurar_salida(self, frecuencia: int) -> motores.SalidaAudio:
        """Solo lo llama el hilo trabajador."""
        if self._salida is None:
            self._salida = motores.crear_salida(self.ajustes)
        self._salida.abrir(frecuencia)
        return self._salida

    def _cerrar_salida(self) -> None:
        if self._salida is not None:
            try:
                self._salida.cerrar()
            except Exception:  # pragma: no cover
                pass

    def _reproducir(self, trabajo: Trabajo) -> bool:
        try:
            salida = self._asegurar_salida(trabajo.frecuencia)
        except ErrorMotor as exc:
            log.warning("Sin salida de audio (%s): la interfaz sigue activa.",
                        exc)
            return False
        primer_bloque = True

        for trozo in trabajo.fuente:
            if not trozo:
                continue
            if not self._vigente(trabajo.token):
                # Interrumpido: hay que descartar lo que ya está en el búfer
                # del sistema, o seguiría sonando un instante.
                salida.vaciar()
                return False
            for parte in senal.trocear(trozo, BYTES_ESCRITURA):
                if not self._vigente(trabajo.token):
                    salida.vaciar()
                    return False
                if primer_bloque:
                    primer_bloque = False
                    with self._lock:
                        self._hablando = True
                    if trabajo.al_primer_sonido:
                        try:
                            trabajo.al_primer_sonido()
                        except Exception:
                            log.debug("Error en al_primer_sonido", exc_info=True)
                try:
                    salida.escribir(senal.escalar(parte, self.volumen))
                except ErrorMotor as exc:
                    log.error("Fallo en la salida de audio: %s", exc)
                    self._cerrar_salida()
                    self._salida = None
                    return False
                self._actualizar_nivel(senal.nivel_normalizado(parte))

        # Dejar que el sistema drene lo escrito antes de dar el turno por
        # terminado; si no, el rostro cerraría la boca antes de tiempo.
        self._drenar(salida, trabajo)
        return self._vigente(trabajo.token)

    def _actualizar_nivel(self, nuevo: float) -> None:
        with self._lock:
            self._nivel = max(nuevo, self._nivel * _CAIDA_NIVEL)

    def _drenar(self, salida: motores.SalidaAudio, trabajo: Trabajo) -> None:
        """Espera aproximadamente lo que el motor tiene en su búfer."""
        fin = time.monotonic() + max(0.0, salida.latencia_buffer_s)
        while time.monotonic() < fin:
            if not self._vigente(trabajo.token):
                return
            time.sleep(0.02)
            self._actualizar_nivel(0.0)
