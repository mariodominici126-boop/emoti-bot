"""Activación por voz: «Hola Emoti», «Buenos días, Emoti», «Buenas tardes, Emoti».

Escucha ligera con lo que ya hay: el VAD de `Microfono.escuchar` recorta una
intervención y Whisper LOCAL la transcribe. Si la frase es una de las de
activación, empieza un turno normal. Nada sale del equipo antes de activar:
sin Whisper local (reconocimiento remoto o ninguno), no se activa.

Contra las activaciones falsas:
- solo intervenciones cortas (`MAX_SEGUNDOS_FRASE` de voz útil): una
  conversación de fondo no llega ni a transcribirse;
- la frase tiene que EMPEZAR por el saludo y llevar el nombre justo detrás,
  con pocas palabras de más;
- el nombre se compara con tolerancia (Whisper escribe «Emoti», «Emotti»,
  «Imoti», «E moti»…), pero no tanta como para aceptar «remoto».
No escucha mientras el robot habla ni durante un turno, y deja un margen
tras hablar para no oírse a sí mismo. El texto reconocido no se guarda ni se
registra.
"""
from __future__ import annotations

import difflib
import random
import re
import threading
import time
import unicodedata
from typing import Callable

from . import registro

log = registro.obtener("activacion")

NOMBRE = "emoti"
SALUDOS = (("hola",), ("buenos", "dias"), ("buenas", "tardes"))
SIMILITUD_NOMBRE = 0.78
SIMILITUD_SALUDO = 0.75
MAX_PALABRAS_DELANTE = 1          # «oye, hola Emoti»
MAX_PALABRAS_DETRAS = 3           # «hola Emoti, ¿cómo estás?»
MAX_SEGUNDOS_FRASE = 3.5          # voz útil
MARGEN_TRAS_HABLAR_S = 1.0        # que no se oiga a sí mismo


def normalizar(texto: str) -> list[str]:
    plano = unicodedata.normalize("NFD", (texto or "").lower())
    plano = "".join(c for c in plano if unicodedata.category(c) != "Mn")
    return re.findall(r"[a-zñ]+", plano)


def _parecido(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


# Respuesta al saludo, LOCAL y fija (ningún modelo la escribe), variada.
RESPUESTAS = {
    "hola": ("¡Hola! Aquí estoy, dime.", "Hola, te escucho.", "¡Hola! ¿Qué tal? Cuéntame.",
             "Hola, ¿cómo estás?", "Aquí estoy. ¿Qué me cuentas?"),
    "buenos dias": ("¡Buenos días! Te escucho.", "Buenos días, ¿cómo amaneciste?",
                    "¡Buenos días! ¿Qué tal empieza el día?"),
    "buenas tardes": ("¡Buenas tardes! Aquí estoy.", "Buenas tardes, ¿cómo va todo?",
                      "¡Buenas tardes! Cuéntame."),
}
_azar = random.Random()


def respuesta_saludo(saludo: str, anterior: str = "") -> str:
    """Una respuesta al saludo, distinta de la anterior."""
    opciones = [r for r in RESPUESTAS.get(saludo, RESPUESTAS["hola"]) if r != anterior]
    return _azar.choice(opciones)


def es_activacion(texto: str) -> bool:
    """¿Es una de las frases de activación?"""
    return bool(que_saludo(texto))


def que_saludo(texto: str) -> str:
    """El saludo de la frase de activación («hola», «buenos dias»,
    «buenas tardes»), o "" si no es una."""
    palabras = normalizar(texto)
    for delante in range(0, MAX_PALABRAS_DELANTE + 1):
        for saludo in SALUDOS:
            fin_saludo = delante + len(saludo)
            trozo = palabras[delante:fin_saludo]
            if len(trozo) != len(saludo) or any(
                    _parecido(p, s) < SIMILITUD_SALUDO for p, s in zip(trozo, saludo)):
                continue
            resto = palabras[fin_saludo:]
            # El nombre, en una palabra o partido en dos («e moti»).
            for largo in (1, 2):
                nombre = "".join(resto[:largo])
                if len(resto) >= largo and _parecido(nombre, NOMBRE) >= SIMILITUD_NOMBRE:
                    if len(resto) - largo <= MAX_PALABRAS_DETRAS:
                        return " ".join(saludo)
    return ""


class EscuchaActivacion:
    """Hilo de escucha ligera. `puede_escuchar()` lo consulta antes de cada
    escucha; `pausar()` corta la escucha en curso y espera a que el micrófono
    quede libre (lo usa la aplicación antes de un turno)."""

    def __init__(self, microfono, transcriptor, puede_escuchar: Callable[[], bool],
                 al_activar: Callable[[str], None]) -> None:
        self.microfono = microfono
        self.transcriptor = transcriptor
        self.puede_escuchar = puede_escuchar
        self.al_activar = al_activar
        self._cancelar = threading.Event()
        self._parar = threading.Event()
        self._libre = threading.Event()
        self._libre.set()
        # Decidir «abro el micrófono» y «suéltalo» no pueden cruzarse.
        self._cerrojo = threading.Lock()
        self._hilo: threading.Thread | None = None

    @staticmethod
    def admite(transcriptor) -> bool:
        """Solo con reconocimiento LOCAL: el audio no sale antes de activar."""
        return getattr(transcriptor, "nombre", "") == "whisper-local"

    def iniciar(self) -> None:
        if self._hilo is None:
            self._hilo = threading.Thread(target=self._bucle, name="emotibot-activacion",
                                          daemon=True)
            self._hilo.start()

    def pausar(self, espera_max: float = 2.0) -> None:
        """Suelta el micrófono ya (lo pide un turno, que antes se ha marcado
        como en curso para que `puede_escuchar()` dé False)."""
        with self._cerrojo:
            self._cancelar.set()
        self._libre.wait(espera_max)

    def detener(self) -> None:
        self._parar.set()
        self._cancelar.set()

    def _bucle(self) -> None:
        while not self._parar.is_set():
            with self._cerrojo:
                abrir = self.puede_escuchar()
                if abrir:
                    self._cancelar.clear()
                    self._libre.clear()
            if not abrir:
                time.sleep(0.2)
                continue
            try:
                self.escuchar_una_vez()
            except Exception as exc:          # nunca tumba la aplicación
                log.warning("Escucha de activación: %s", registro.resumen_excepcion(exc))
                time.sleep(1.0)

    def escuchar_una_vez(self) -> bool:
        """Una intervención: True si era una frase de activación."""
        try:
            captura = self.microfono.escuchar(self._cancelar)
        finally:
            self._libre.set()
        if (self._cancelar.is_set() or not captura.hay_voz
                or captura.duracion_util_s > MAX_SEGUNDOS_FRASE
                or not self.puede_escuchar()):
            return False
        texto = self.transcriptor.transcribir(captura.pcm, captura.frecuencia).texto
        saludo = que_saludo(texto)
        if not saludo or not self.puede_escuchar():
            return False
        log.info("Frase de activación reconocida.")
        self.al_activar(saludo)
        return True
