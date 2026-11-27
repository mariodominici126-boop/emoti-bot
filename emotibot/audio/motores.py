"""Motores de audio: la capa que hace al proyecto multiplataforma.

El prototipo hablaba directamente con `arecord` y `aplay`, que son de ALSA y
solo existen en Linux. Eso ataba el desarrollo a la Raspberry Pi: no se podía
probar voz ni micrófono en otra máquina, y eso es media jornada de trabajo
perdida cada vez que hay que diagnosticar algo.

Aquí la entrada y la salida pasan por una interfaz mínima con dos
implementaciones:

- **ALSA** (`arecord` / `aplay`): la vía probada en la Pi. Sin dependencias de
  Python, un proceso por flujo.
- **PortAudio** (paquete `sounddevice`): Windows, macOS y Linux. En Windows la
  rueda de pip trae las bibliotecas nativas incluidas, así que basta un
  `pip install sounddevice`.

Selección automática: en Linux se prefiere ALSA porque ya está validada en el
dispositivo real; en el resto, PortAudio. Se puede forzar con el ajuste
`audio.motor` o con `EMOTI_AUDIO_MOTOR=portaudio`.

La frontera es estrecha a propósito: leer bloques y escribir bloques. Toda la
lógica de VAD, recorte, envolvente y turnos vive por encima y no sabe en qué
sistema operativo está corriendo.
"""
from __future__ import annotations

import os
import select
import shutil
import subprocess
import sys
import time
from typing import Protocol

from .. import registro
from ..ajustes import AjustesAudio, dispositivo_valido
from . import senal

log = registro.obtener("audio.motores")

ALSA = "alsa"
PORTAUDIO = "portaudio"

LATENCIA_ALSA_US = 120_000      # búfer de aplay, acota el retardo al oído
_ESPERA_LECTURA_S = 0.2


class ErrorMotor(RuntimeError):
    """El dispositivo de audio no está disponible o falló."""


# --------------------------------------------------------------- interfaces
class EntradaAudio(Protocol):
    nombre: str

    def iniciar(self) -> None: ...

    def leer(self, max_bytes: int) -> bytes:
        """Hasta `max_bytes` de PCM. b'' si todavía no hay datos."""
        ...

    def cerrar(self) -> None: ...


class SalidaAudio(Protocol):
    nombre: str
    latencia_buffer_s: float

    def abrir(self, frecuencia: int) -> None: ...

    def escribir(self, pcm: bytes) -> None: ...

    def vaciar(self) -> None:
        """Descarta lo que aún no ha sonado. Para interrumpir al robot."""
        ...

    def cerrar(self) -> None: ...


# -------------------------------------------------------------------- ALSA
class EntradaAlsa:
    nombre = ALSA

    def __init__(self, frecuencia: int, dispositivo: str | None = None,
                 duracion_fija: int | None = None) -> None:
        self.frecuencia = frecuencia
        # El dispositivo acaba en los argumentos de un subproceso: se valida.
        self.dispositivo = dispositivo_valido(dispositivo)
        self.duracion_fija = duracion_fija
        self._proceso: subprocess.Popen | None = None

    @staticmethod
    def disponible() -> bool:
        return shutil.which("arecord") is not None

    def _argumentos(self) -> list[str]:
        args = ["arecord", "-q", "-t", "raw", "-f", "S16_LE",
                "-r", str(self.frecuencia), "-c", "1"]
        if self.dispositivo:
            args += ["-D", self.dispositivo]
        if self.duracion_fija:
            args += ["-d", str(self.duracion_fija)]
        return args

    def iniciar(self) -> None:
        try:
            self._proceso = subprocess.Popen(
                self._argumentos(), stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0,
            )
        except OSError as exc:
            raise ErrorMotor(f"No pude iniciar arecord: {exc}") from exc

    def leer(self, max_bytes: int) -> bytes:
        proceso = self._proceso
        if proceso is None or proceso.stdout is None:
            raise ErrorMotor("El micrófono no está abierto.")
        if proceso.poll() is not None:
            raise ErrorMotor(self._explicar_salida())
        listos, _, _ = select.select([proceso.stdout], [], [],
                                     _ESPERA_LECTURA_S)
        if not listos:
            return b""
        datos = os.read(proceso.stdout.fileno(), max_bytes)
        if not datos:
            raise ErrorMotor("El micrófono dejó de entregar muestras.")
        return datos

    def _explicar_salida(self) -> str:
        detalle = ""
        try:
            if self._proceso is not None and self._proceso.stderr is not None:
                detalle = self._proceso.stderr.read(400).decode(
                    "utf-8", "replace").strip()
        except (OSError, ValueError):
            detalle = ""
        if "busy" in detalle.lower():
            return ("El dispositivo de audio está ocupado por otro programa. "
                    "Cierra lo que esté usando el micrófono.")
        return detalle or "arecord terminó antes de tiempo."

    def cerrar(self) -> None:
        proceso, self._proceso = self._proceso, None
        if proceso is None:
            return
        try:
            if proceso.poll() is None:
                proceso.terminate()
                try:
                    proceso.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    proceso.kill()
                    proceso.wait(timeout=1.0)
        except Exception:  # pragma: no cover
            pass
        for flujo in (proceso.stdout, proceso.stderr):
            if flujo is not None:
                try:
                    flujo.close()
                except OSError:
                    pass


class SalidaAlsa:
    nombre = ALSA
    latencia_buffer_s = LATENCIA_ALSA_US / 1_000_000.0

    def __init__(self, dispositivo: str | None = None) -> None:
        self.dispositivo = dispositivo_valido(dispositivo)
        self._proceso: subprocess.Popen | None = None
        self._frecuencia = 0

    @staticmethod
    def disponible() -> bool:
        return shutil.which("aplay") is not None

    def abrir(self, frecuencia: int) -> None:
        if (self._proceso is not None and self._proceso.poll() is None
                and self._frecuencia == frecuencia):
            return
        self.cerrar()
        args = ["aplay", "-q", "-t", "raw", "-f", "S16_LE",
                "-r", str(frecuencia), "-c", "1",
                f"--buffer-time={LATENCIA_ALSA_US}"]
        if self.dispositivo:
            args += ["-D", self.dispositivo]
        try:
            self._proceso = subprocess.Popen(
                args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE, bufsize=0,
            )
        except OSError as exc:
            raise ErrorMotor(f"No pude iniciar aplay: {exc}") from exc
        self._frecuencia = frecuencia

    def escribir(self, pcm: bytes) -> None:
        if self._proceso is None or self._proceso.stdin is None:
            raise ErrorMotor("El altavoz no está abierto.")
        try:
            self._proceso.stdin.write(pcm)
        except (BrokenPipeError, OSError) as exc:
            raise ErrorMotor(f"aplay cerró la entrada: {exc}") from exc

    def vaciar(self) -> None:
        # ALSA sigue sonando lo que ya tiene en su búfer: la única forma
        # fiable de callar al instante es cerrar el proceso.
        self.cerrar()

    def cerrar(self) -> None:
        proceso, self._proceso = self._proceso, None
        self._frecuencia = 0
        if proceso is None:
            return
        try:
            if proceso.stdin:
                try:
                    proceso.stdin.close()
                except OSError:
                    pass
            if proceso.poll() is None:
                proceso.terminate()
                try:
                    proceso.wait(timeout=0.6)
                except subprocess.TimeoutExpired:
                    proceso.kill()
                    proceso.wait(timeout=0.6)
        except Exception:  # pragma: no cover
            pass
        finally:
            if proceso.stderr:
                try:
                    proceso.stderr.close()
                except OSError:
                    pass


# --------------------------------------------------------------- PortAudio
def cargar_sounddevice():
    """Importa sounddevice distinguiendo los dos fallos posibles.

    El paquete de Python puede estar instalado y faltar la biblioteca nativa
    PortAudio: es lo que pasa en Linux sin `libportaudio2`. El mensaje tiene
    que decir cuál de las dos cosas falta, porque la solución es distinta.
    """
    try:
        import sounddevice  # type: ignore
    except ImportError as exc:
        raise ErrorMotor(
            "Falta el paquete sounddevice (pip install sounddevice)."
        ) from exc
    except OSError as exc:
        if "portaudio" in str(exc).lower():
            consejo = ("sudo apt install libportaudio2"
                       if sys.platform.startswith("linux")
                       else "reinstala sounddevice")
            raise ErrorMotor(
                f"sounddevice está instalado pero falta la biblioteca "
                f"PortAudio del sistema: {consejo}."
            ) from exc
        raise ErrorMotor(f"sounddevice no pudo cargarse: {exc}") from exc
    return sounddevice


class EntradaPortAudio:
    nombre = PORTAUDIO

    def __init__(self, frecuencia: int, dispositivo: str | None = None,
                 bytes_bloque: int = 1600) -> None:
        self.frecuencia = frecuencia
        self.dispositivo = _dispositivo_portaudio(dispositivo)
        self.frames_bloque = max(64, bytes_bloque // senal.ANCHO_MUESTRA)
        self._sd = None
        self._flujo = None

    @staticmethod
    def disponible() -> bool:
        try:
            cargar_sounddevice()
            return True
        except ErrorMotor:
            return False

    def iniciar(self) -> None:
        self._sd = cargar_sounddevice()
        try:
            self._flujo = self._sd.RawInputStream(
                samplerate=self.frecuencia,
                blocksize=self.frames_bloque,
                device=self.dispositivo,
                channels=1,
                dtype="int16",
            )
            self._flujo.start()
        except Exception as exc:
            self._flujo = None
            raise ErrorMotor(f"No pude abrir el micrófono: {exc}") from exc

    def leer(self, max_bytes: int) -> bytes:
        if self._flujo is None:
            raise ErrorMotor("El micrófono no está abierto.")
        frames = max(1, min(self.frames_bloque,
                            max_bytes // senal.ANCHO_MUESTRA))
        try:
            datos, desbordado = self._flujo.read(frames)
        except Exception as exc:
            raise ErrorMotor(f"Fallo al leer del micrófono: {exc}") from exc
        if desbordado:
            # No es fatal: el sistema no nos dio tiempo. Se anota una vez por
            # turno en depuración para no llenar el registro.
            log.debug("Desbordamiento de entrada: se perdieron muestras.")
        return bytes(datos)

    def cerrar(self) -> None:
        flujo, self._flujo = self._flujo, None
        if flujo is None:
            return
        try:
            flujo.abort(ignore_errors=True)
        except Exception:
            pass
        try:
            flujo.close(ignore_errors=True)
        except Exception:
            pass


class SalidaPortAudio:
    nombre = PORTAUDIO
    latencia_buffer_s = 0.12

    def __init__(self, dispositivo: str | None = None) -> None:
        self.dispositivo = _dispositivo_portaudio(dispositivo)
        self._sd = None
        self._flujo = None
        self._frecuencia = 0

    @staticmethod
    def disponible() -> bool:
        return EntradaPortAudio.disponible()

    def abrir(self, frecuencia: int) -> None:
        if self._flujo is not None and self._frecuencia == frecuencia:
            return
        self.cerrar()
        self._sd = cargar_sounddevice()
        try:
            self._flujo = self._sd.RawOutputStream(
                samplerate=frecuencia,
                device=self.dispositivo,
                channels=1,
                dtype="int16",
            )
            self._flujo.start()
        except Exception as exc:
            self._flujo = None
            raise ErrorMotor(f"No pude abrir el altavoz: {exc}") from exc
        self._frecuencia = frecuencia
        try:
            self.latencia_buffer_s = float(self._flujo.latency) or 0.12
        except (TypeError, ValueError):
            self.latencia_buffer_s = 0.12

    def escribir(self, pcm: bytes) -> None:
        if self._flujo is None:
            raise ErrorMotor("El altavoz no está abierto.")
        try:
            self._flujo.write(pcm)
        except Exception as exc:
            raise ErrorMotor(f"Fallo al reproducir: {exc}") from exc

    def vaciar(self) -> None:
        """Corta al instante sin cerrar el dispositivo.

        Ventaja frente a ALSA: `abort()` descarta lo pendiente y el flujo se
        puede reanudar, así que interrumpir al robot no cuesta reabrir nada.
        """
        if self._flujo is None:
            return
        try:
            self._flujo.abort(ignore_errors=True)
            self._flujo.start()
        except Exception as exc:
            log.debug("No pude vaciar el búfer de salida: %s", exc)
            self.cerrar()

    def cerrar(self) -> None:
        flujo, self._flujo = self._flujo, None
        self._frecuencia = 0
        if flujo is None:
            return
        try:
            flujo.abort(ignore_errors=True)
        except Exception:
            pass
        try:
            flujo.close(ignore_errors=True)
        except Exception:
            pass


def _dispositivo_portaudio(valor: str | None):
    """PortAudio acepta índice numérico o parte del nombre del dispositivo.

    No se valida con el patrón estricto de ALSA porque aquí el valor no llega
    a ningún subproceso: va a una llamada de biblioteca. Y los nombres en
    Windows llevan espacios y paréntesis («Micrófono (Realtek Audio)»).
    """
    if valor is None or str(valor).strip() == "":
        return None
    texto = str(valor).strip()
    if texto.lstrip("-").isdigit():
        return int(texto)
    return texto


# ------------------------------------------------------------- selección
def motor_preferido(config: AjustesAudio) -> str:
    solicitado = (getattr(config, "motor", "auto") or "auto").lower()
    if solicitado in (ALSA, PORTAUDIO):
        return solicitado
    if sys.platform.startswith("linux") and EntradaAlsa.disponible():
        return ALSA
    if EntradaPortAudio.disponible():
        return PORTAUDIO
    if EntradaAlsa.disponible():
        return ALSA
    return PORTAUDIO  # para que el mensaje de error explique qué instalar


def diagnostico_motores() -> dict[str, str]:
    """Estado de cada motor, en lenguaje claro, para los diagnósticos."""
    estado: dict[str, str] = {}
    estado[ALSA] = ("disponible" if EntradaAlsa.disponible()
                    else "no (falta arecord; es solo para Linux)")
    try:
        cargar_sounddevice()
        estado[PORTAUDIO] = "disponible"
    except ErrorMotor as exc:
        estado[PORTAUDIO] = f"no ({exc})"
    return estado


def crear_entrada(config: AjustesAudio, bytes_bloque: int,
                  duracion_fija: int | None = None) -> EntradaAudio:
    motor = motor_preferido(config)
    if motor == ALSA:
        if not EntradaAlsa.disponible():
            raise ErrorMotor(
                "Falta arecord (paquete alsa-utils). En Windows usa el motor "
                "portaudio: pip install sounddevice."
            )
        return EntradaAlsa(config.frecuencia_captura,
                           config.dispositivo_captura, duracion_fija)
    return EntradaPortAudio(config.frecuencia_captura,
                            config.dispositivo_captura, bytes_bloque)


def crear_salida(config: AjustesAudio) -> SalidaAudio:
    motor = motor_preferido(config)
    if motor == ALSA:
        if not SalidaAlsa.disponible():
            raise ErrorMotor("Falta aplay (paquete alsa-utils).")
        return SalidaAlsa(config.dispositivo_salida)
    return SalidaPortAudio(config.dispositivo_salida)


def hay_entrada(config: AjustesAudio) -> bool:
    motor = motor_preferido(config)
    return (EntradaAlsa.disponible() if motor == ALSA
            else EntradaPortAudio.disponible())


def hay_salida(config: AjustesAudio) -> bool:
    motor = motor_preferido(config)
    return (SalidaAlsa.disponible() if motor == ALSA
            else SalidaPortAudio.disponible())


def esperar(segundos: float) -> None:
    """Pequeña espera, usada al drenar la salida."""
    time.sleep(max(0.0, segundos))
