"""Modelos que NO van en el paquete y se bajan a petición, con progreso.

- Voz «daniela» (Piper es_AR-daniela-high, CC BY-SA 4.0): no se reparte
  dentro del ejecutable; se baja cuando alguien la elige.
- Whisper «base» (solo el despertar por voz): se baja cuando se enciende la
  activación por voz. La conversación usa «small», que sí va dentro.

Lo que va DENTRO del paquete (voz «claude», Apache-2.0, y Whisper «small»)
se busca en `rutas.RECURSOS`. Nada de esto se descarga en el hilo de la
interfaz: quien llama lo hace en un hilo y recibe el progreso (0-1).
"""
from __future__ import annotations

import os
import threading
import urllib.request
from pathlib import Path
from typing import Callable

from . import registro, rutas

log = registro.obtener("descargas")

Progreso = Callable[[float], None]

# Voces que se pueden bajar: archivo .onnx → carpeta en rhasspy/piper-voices.
_PIPER = "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
VOCES_DESCARGABLES = {
    "es_AR-daniela-high.onnx": ("es/es_AR/daniela/high/", "CC BY-SA 4.0"),
    "es_MX-claude-high.onnx": ("es/es_MX/claude/high/", "Apache-2.0"),
}

# Tamaño aproximado de cada modelo de Whisper (int8 en disco), solo para el
# porcentaje: la descarga la hace faster-whisper.
TAMANO_WHISPER = {"tiny": 75e6, "base": 145e6, "small": 486e6, "medium": 1.5e9}


class ErrorDescarga(RuntimeError):
    pass


# ------------------------------------------------------------------- voces
def voz_descargable(ruta: Path) -> bool:
    return ruta.name in VOCES_DESCARGABLES


def licencia_voz(ruta: Path) -> str:
    return VOCES_DESCARGABLES.get(ruta.name, ("", ""))[1]


def descargar_voz(ruta: Path, al_progreso: Progreso | None = None,
                  tiempo_s: float = 30.0) -> Path:
    """Baja el .onnx y su .onnx.json a la carpeta de voces del usuario.
    Escribe en `.parte` y renombra al final: una descarga cortada no deja
    un modelo roto que luego Piper intente cargar."""
    if not voz_descargable(ruta):
        raise ErrorDescarga(f"No sé de dónde bajar {ruta.name}.")
    carpeta, _ = VOCES_DESCARGABLES[ruta.name]
    destino_dir = rutas.asegurar_directorio(rutas.VOCES_USUARIO)
    archivos = [ruta.name + ".json", ruta.name]          # el pequeño primero
    hechos = 0
    for indice, nombre in enumerate(archivos):
        url = _PIPER + carpeta + nombre
        destino = destino_dir / nombre
        parte = destino.with_name(nombre + ".parte")
        try:
            with urllib.request.urlopen(url, timeout=tiempo_s) as respuesta, \
                    open(parte, "wb") as salida:
                total = int(respuesta.headers.get("Content-Length") or 0)
                leidos = 0
                while True:
                    bloque = respuesta.read(1 << 16)
                    if not bloque:
                        break
                    salida.write(bloque)
                    leidos += len(bloque)
                    if al_progreso and total and indice == len(archivos) - 1:
                        al_progreso(min(1.0, leidos / total))
            os.replace(parte, destino)
            hechos += 1
        except OSError as exc:
            try:
                parte.unlink()
            except OSError:
                pass
            raise ErrorDescarga(f"No pude bajar {nombre}: {exc}") from exc
    log.info("Voz descargada: %s (%s).", ruta.name, licencia_voz(ruta))
    return destino_dir / ruta.name


# ----------------------------------------------------------------- whisper
def whisper_empaquetado(nombre: str) -> Path | None:
    """La carpeta del modelo si va dentro del paquete."""
    carpeta = rutas.RECURSOS / "modelos" / f"whisper-{nombre}"
    return carpeta if (carpeta / "model.bin").is_file() else None


def whisper_en_disco(nombre: str) -> bool:
    """Si el modelo se puede cargar SIN red: empaquetado o ya en la caché."""
    if whisper_empaquetado(nombre) is not None:
        return True
    try:
        from faster_whisper.utils import download_model
        download_model(nombre, local_files_only=True)
        return True
    except Exception:
        return False


def descargar_whisper(nombre: str, al_progreso: Progreso | None = None) -> None:
    """Baja el modelo a la caché de Hugging Face (lo hace faster-whisper).
    El progreso se calcula por el tamaño de lo ya escrito en la caché."""
    from faster_whisper.utils import download_model
    error: list[BaseException] = []
    listo = threading.Event()

    def bajar() -> None:
        try:
            download_model(nombre)
        except BaseException as exc:        # se relanza en quien llama
            error.append(exc)
        finally:
            listo.set()

    threading.Thread(target=bajar, name=f"bajar-whisper-{nombre}", daemon=True).start()
    carpeta = _cache_hf() / f"models--Systran--faster-whisper-{nombre}"
    esperado = TAMANO_WHISPER.get(nombre, 0)
    while not listo.wait(0.5):
        if al_progreso and esperado:
            al_progreso(min(0.99, _tamano(carpeta) / esperado))
    if error:
        raise ErrorDescarga(f"No pude bajar Whisper «{nombre}»: {error[0]}") from error[0]
    if al_progreso:
        al_progreso(1.0)
    log.info("Whisper «%s» descargado.", nombre)


def _cache_hf() -> Path:
    if os.environ.get("HF_HUB_CACHE"):
        return Path(os.environ["HF_HUB_CACHE"])
    base = os.environ.get("HF_HOME") or Path.home() / ".cache" / "huggingface"
    return Path(base) / "hub"


def _tamano(carpeta: Path) -> int:
    total = 0
    for raiz, _, archivos in os.walk(carpeta):
        for nombre in archivos:
            try:
                total += os.path.getsize(os.path.join(raiz, nombre))
            except OSError:
                pass
    return total


def porcentaje(fraccion: float) -> str:
    return f"{int(fraccion * 100)} %"


__all__ = ["ErrorDescarga", "descargar_voz", "descargar_whisper", "licencia_voz",
           "porcentaje", "voz_descargable", "whisper_empaquetado", "whisper_en_disco"]
