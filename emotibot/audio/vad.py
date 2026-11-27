"""Detector de actividad de voz por energía, con fases explícitas.

ESTE MÓDULO CORRIGE EL DEFECTO MÁS DAÑINO DEL PROTOTIPO ANTERIOR.

En las versiones 0.5–0.6.2, `DeteccionVoz` calibraba el ruido de fondo con los
primeros 4 bloques (400 ms) de audio, mientras la interfaz ya había mostrado
"Habla ahora". Si la persona empezaba a hablar dentro de esos 400 ms —lo
normal—, la calibración medía su propia voz como ruido de fondo y fijaba el
umbral en 3x su voz. A partir de ahí la voz nunca superaba el umbral, el bucle
agotaba `MAX_AUDIO` y el programa respondía:

    "No detecté voz. Acércate al micrófono."

Es decir: un error de software que se presentaba como un problema de
distancia, y que contaminó el diagnóstico del micrófono.

Las correcciones son cuatro:

1. Fases explícitas. ASENTANDO descarta el arranque del dispositivo ALSA (los
   primeros milisegundos traen basura y continua). CALIBRANDO mide ruido. Solo
   al entrar en ESPERANDO_VOZ se avisa a la persona de que puede hablar.
2. Si durante la calibración la energía sube de forma sostenida, se descarta
   esa calibración por contaminada y se vuelve a calibrar una vez; si vuelve a
   pasar, se usa el piso absoluto en lugar de un umbral imposible.
3. Histéresis: el umbral para EMPEZAR a detectar voz es más alto que el umbral
   para CONSIDERAR que la voz sigue. Sin esto, una sílaba suave en medio de una
   frase corta la grabación.
4. `primera_voz` y `ultima_voz` se exponen de verdad. En el código anterior se
   calculaban y se tiraban, y eran justamente la métrica que hacía falta.

Lo que este detector NO es: un VAD neuronal. Compara energía con el ruido de
fondo. No distingue voz humana de un portazo. Para eso hace falta un modelo
(Silero y similares), que está previsto como paso posterior.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field

from .. import registro
from . import senal

log = registro.obtener("audio.vad")


class Fase(enum.Enum):
    ASENTANDO = "asentando"
    CALIBRANDO = "calibrando"
    ESPERANDO_VOZ = "esperando_voz"
    EN_VOZ = "en_voz"
    TERMINADO = "terminado"


MENSAJES_FASE = {
    Fase.ASENTANDO: "Preparando el micrófono…",
    Fase.CALIBRANDO: "Escuchando el ruido de la sala, espera un momento…",
    Fase.ESPERANDO_VOZ: "Te escucho: habla cuando quieras.",
    Fase.EN_VOZ: "Te escucho…",
    Fase.TERMINADO: "Listo.",
}


@dataclass
class Diagnostico:
    """Lo que el detector aprendió. Útil para el script de diagnóstico."""

    ruido_base: float = 0.0
    umbral_inicio: float = 0.0
    umbral_continuidad: float = 0.0
    calibracion_contaminada: bool = False
    rms_maximo_observado: float = 0.0
    bloques_totales: int = 0


@dataclass
class DetectorVoz:
    """Máquina de estados sobre bloques de PCM de duración fija.

    `procesar()` se llama con cada bloque y devuelve True cuando considera que
    la intervención terminó.
    """

    segundos_bloque: float
    ms_asentamiento: int = 250
    ms_calibracion: int = 450
    factor_umbral: float = 2.2
    piso_umbral_rms: float = 120.0
    histeresis: float = 0.65
    bloques_confirmacion: int = 3
    silencio_final_s: float = 0.85
    umbral_manual: float = 0.0

    fase: Fase = Fase.ASENTANDO
    primera_voz: float | None = None
    ultima_voz: float | None = None
    # Índice del bloque en que empezó y terminó la voz. El recorte usa esto y
    # no las marcas de tiempo: convertir tiempo a índice da por supuesto que
    # los bloques llegan a ritmo real, cierto con un dispositivo de verdad
    # pero no con un archivo, una prueba o una fuente que se adelante.
    indice_primera_voz: int | None = None
    indice_ultima_voz: int | None = None
    diagnostico: Diagnostico = field(default_factory=Diagnostico)

    _muestras_ruido: list[float] = field(default_factory=list, repr=False)
    _bloques_vistos: int = field(default=0, repr=False)
    _consecutivos: int = field(default=0, repr=False)
    _recalibraciones: int = field(default=0, repr=False)
    _umbral_inicio: float = field(default=0.0, repr=False)
    _umbral_continuidad: float = field(default=0.0, repr=False)

    def __post_init__(self) -> None:
        self.histeresis = min(0.95, max(0.3, self.histeresis))
        self.bloques_confirmacion = max(1, self.bloques_confirmacion)
        if self.umbral_manual > 0:
            # Umbral fijo: salta la calibración por completo. Es la vía de
            # escape cuando el micrófono tiene una respuesta muy atípica.
            self._fijar_umbrales(self.umbral_manual)
            self.fase = Fase.ESPERANDO_VOZ
            self.diagnostico.ruido_base = 0.0
            log.info("Umbral manual fijado en %.0f RMS; sin calibración.",
                     self.umbral_manual)

    # ---------------------------------------------------------------- umbrales
    def _fijar_umbrales(self, inicio: float) -> None:
        self._umbral_inicio = inicio
        self._umbral_continuidad = max(self.piso_umbral_rms * 0.5,
                                       inicio * self.histeresis)
        self.diagnostico.umbral_inicio = self._umbral_inicio
        self.diagnostico.umbral_continuidad = self._umbral_continuidad

    def _bloques_para(self, milisegundos: int) -> int:
        if self.segundos_bloque <= 0:
            return 1
        return max(1, round((milisegundos / 1000.0) / self.segundos_bloque))

    def _calibracion_sospechosa(self) -> bool:
        """Detecta que la persona habló durante la calibración.

        Criterio: la voz sube la energía de forma SOSTENIDA. Un pico suelto no
        cuenta, y por eso se descarta el cuartil superior de las muestras: el
        clic de la tecla con la que se inicia el turno, un golpe en la mesa o
        el chasquido del ratón son transitorios, no voz, y antes bastaba uno
        solo para invalidar la medición y caer al piso absoluto.
        """
        if len(self._muestras_ruido) < 4:
            return False
        ordenadas = sorted(self._muestras_ruido)
        recortadas = ordenadas[: max(3, int(len(ordenadas) * 0.75))]
        mediana_recortada = recortadas[len(recortadas) // 2]

        mitad = len(self._muestras_ruido) // 2
        primera = sorted(self._muestras_ruido[:mitad])
        segunda = sorted(self._muestras_ruido[mitad:])
        if not primera or not segunda:
            return False
        mediana_primera = primera[len(primera) // 2]
        mediana_segunda = segunda[len(segunda) // 2]

        # Subida sostenida de la primera a la segunda mitad…
        subida = mediana_segunda > max(self.piso_umbral_rms,
                                       mediana_primera * 3.0)
        # …o un nivel de fondo tan alto que no puede ser una sala en silencio.
        alto = mediana_recortada > self.piso_umbral_rms * 3.0
        return bool(subida or alto)

    def _cerrar_calibracion(self) -> None:
        if self._calibracion_sospechosa() and self._recalibraciones == 0:
            self._recalibraciones += 1
            self.diagnostico.calibracion_contaminada = True
            self._muestras_ruido.clear()
            self._bloques_vistos = 0
            log.info("Calibración contaminada por voz; repito la medición una vez.")
            return

        if self._muestras_ruido:
            ordenadas = sorted(self._muestras_ruido)
            ruido = ordenadas[len(ordenadas) // 2]
        else:
            ruido = 0.0

        if self.diagnostico.calibracion_contaminada and self._recalibraciones >= 1 \
                and self._calibracion_sospechosa():
            # Segundo intento también contaminado: no inventamos un umbral
            # sobre una medición mala. Usamos el piso absoluto.
            log.warning("Calibración contaminada otra vez; uso el piso absoluto "
                        "(%0.f RMS) en lugar de un umbral calculado.",
                        self.piso_umbral_rms)
            ruido = 0.0

        self.diagnostico.ruido_base = ruido
        self._fijar_umbrales(max(self.piso_umbral_rms, ruido * self.factor_umbral))
        self.fase = Fase.ESPERANDO_VOZ
        log.info(
            "Ruido base %.0f RMS · umbral inicio %.0f · continuidad %.0f",
            ruido, self._umbral_inicio, self._umbral_continuidad,
        )

    # ---------------------------------------------------------------- proceso
    def procesar(self, bloque: bytes, ahora: float) -> bool:
        """Consume un bloque. Devuelve True si la intervención terminó."""
        energia = senal.rms(bloque)
        self.diagnostico.bloques_totales += 1
        self.diagnostico.rms_maximo_observado = max(
            self.diagnostico.rms_maximo_observado, energia
        )

        if self.fase is Fase.ASENTANDO:
            self._bloques_vistos += 1
            if self._bloques_vistos >= self._bloques_para(self.ms_asentamiento):
                self._bloques_vistos = 0
                self.fase = Fase.CALIBRANDO
            return False

        if self.fase is Fase.CALIBRANDO:
            self._muestras_ruido.append(energia)
            self._bloques_vistos += 1
            if self._bloques_vistos >= self._bloques_para(self.ms_calibracion):
                self._cerrar_calibracion()
            return False

        indice = self.diagnostico.bloques_totales - 1

        if self.fase is Fase.ESPERANDO_VOZ:
            if energia >= self._umbral_inicio:
                self._consecutivos += 1
                if self._consecutivos >= self.bloques_confirmacion:
                    self.fase = Fase.EN_VOZ
                    # La voz empezó `bloques_confirmacion` bloques atrás.
                    self.primera_voz = ahora - (
                        self.bloques_confirmacion * self.segundos_bloque
                    )
                    self.indice_primera_voz = max(
                        0, indice - self.bloques_confirmacion + 1
                    )
                    self.ultima_voz = ahora
                    self.indice_ultima_voz = indice
            else:
                self._consecutivos = 0
            return False

        if self.fase is Fase.EN_VOZ:
            if energia >= self._umbral_continuidad:
                self.ultima_voz = ahora
                self.indice_ultima_voz = indice
            elif self.ultima_voz is not None and \
                    ahora - self.ultima_voz >= self.silencio_final_s:
                self.fase = Fase.TERMINADO
                return True
            return False

        return True

    # ---------------------------------------------------------------- consulta
    @property
    def detecto_voz(self) -> bool:
        return self.primera_voz is not None

    @property
    def calibrando(self) -> bool:
        return self.fase in (Fase.ASENTANDO, Fase.CALIBRANDO)

    def mensaje(self) -> str:
        return MENSAJES_FASE.get(self.fase, "")
