"""Inventario de dispositivos de audio, en Linux y en Windows.

Responde a las incógnitas que la documentación del proyecto marcaba como
pendientes: qué micrófono y qué altavoz hay realmente conectados, si existe
control de ganancia y cuánta señal entrega el micrófono.

Dos fuentes según el motor: `arecord -l` / `aplay -l` / `amixer` en la
Raspberry Pi, y `sounddevice.query_devices()` en cualquier sistema donde haya
PortAudio. El `indice` de una tarjeta PortAudio es el que se pone en
`dispositivo_captura` para elegirla.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field

from .. import registro

log = registro.obtener("audio.dispositivos")

_TIEMPO_LIMITE = 8


@dataclass
class Tarjeta:
    indice: int
    identificador: str
    descripcion: str


@dataclass
class Inventario:
    motor: str = ""
    captura: list[Tarjeta] = field(default_factory=list)
    salida: list[Tarjeta] = field(default_factory=list)
    nombres_pcm_captura: list[str] = field(default_factory=list)
    herramientas_faltantes: list[str] = field(default_factory=list)
    predeterminado_captura: str = ""
    predeterminado_salida: str = ""


_RE_TARJETA = re.compile(
    r"^tarjeta\s+(\d+):\s*(\S+)\s*\[(.*?)\]|^card\s+(\d+):\s*(\S+)\s*\[(.*?)\]",
    re.IGNORECASE,
)


def _ejecutar(args: list[str]) -> str:
    try:
        resultado = subprocess.run(
            args, capture_output=True, text=True, timeout=_TIEMPO_LIMITE, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.debug("No pude ejecutar %s: %s", args[0], exc)
        return ""
    return (resultado.stdout or "") + (resultado.stderr or "")


def _parsear_tarjetas(salida: str) -> list[Tarjeta]:
    tarjetas: list[Tarjeta] = []
    for linea in salida.splitlines():
        coincidencia = _RE_TARJETA.match(linea.strip())
        if not coincidencia:
            continue
        grupos = [g for g in coincidencia.groups() if g is not None]
        if len(grupos) >= 3:
            try:
                tarjetas.append(Tarjeta(int(grupos[0]), grupos[1], grupos[2]))
            except ValueError:
                continue
    return tarjetas


def inventariar(motor: str = "") -> Inventario:
    """Lista los dispositivos del motor indicado, o del que se usaría."""
    from . import motores  # import tardío: evita un ciclo con ajustes

    elegido = motor or (motores.ALSA if shutil.which("arecord")
                        else motores.PORTAUDIO)
    if elegido == motores.PORTAUDIO:
        return _inventariar_portaudio()
    return _inventariar_alsa()


def _inventariar_portaudio() -> Inventario:
    from . import motores

    inventario = Inventario(motor=motores.PORTAUDIO)
    try:
        sd = motores.cargar_sounddevice()
    except motores.ErrorMotor as exc:
        inventario.herramientas_faltantes.append(str(exc))
        return inventario

    try:
        dispositivos = sd.query_devices()
    except Exception as exc:
        inventario.herramientas_faltantes.append(
            f"PortAudio no pudo listar dispositivos: {exc}")
        return inventario

    for indice, datos in enumerate(dispositivos):
        nombre = str(datos.get("name", "?"))
        api = ""
        try:
            api = str(sd.query_hostapis(datos["hostapi"])["name"])
        except Exception:
            api = ""
        descripcion = f"{nombre} [{api}]" if api else nombre
        if int(datos.get("max_input_channels", 0)) > 0:
            inventario.captura.append(Tarjeta(indice, str(indice), descripcion))
        if int(datos.get("max_output_channels", 0)) > 0:
            inventario.salida.append(Tarjeta(indice, str(indice), descripcion))

    try:
        entrada, salida = sd.default.device
        if entrada is not None and entrada >= 0:
            inventario.predeterminado_captura = str(
                sd.query_devices(entrada)["name"])
        if salida is not None and salida >= 0:
            inventario.predeterminado_salida = str(
                sd.query_devices(salida)["name"])
    except Exception:
        pass
    return inventario


def _inventariar_alsa() -> Inventario:
    from . import motores

    inventario = Inventario(motor=motores.ALSA)
    for herramienta in ("arecord", "aplay", "amixer"):
        if shutil.which(herramienta) is None:
            inventario.herramientas_faltantes.append(herramienta)

    if shutil.which("arecord"):
        inventario.captura = _parsear_tarjetas(_ejecutar(["arecord", "-l"]))
        inventario.nombres_pcm_captura = [
            linea.strip()
            for linea in _ejecutar(["arecord", "-L"]).splitlines()
            if linea and not linea.startswith((" ", "\t"))
        ][:40]
    if shutil.which("aplay"):
        inventario.salida = _parsear_tarjetas(_ejecutar(["aplay", "-l"]))
    return inventario


def controles_ganancia(indice_tarjeta: int) -> list[str]:
    """Controles de captura de ALSA, para saber si hay ganancia ajustable.

    En Windows la ganancia se ajusta en el panel de sonido del sistema, no
    desde aquí; esta función devuelve una lista vacía y el diagnóstico lo
    explica.
    """
    if shutil.which("amixer") is None:
        return []
    salida = _ejecutar(["amixer", "-c", str(indice_tarjeta), "scontrols"])
    controles = re.findall(r"'([^']+)'", salida)
    interesantes = [
        c for c in controles
        if any(p in c.lower() for p in ("mic", "capture", "boost", "input", "pga"))
    ]
    return interesantes or controles[:10]


def temperatura_cpu() -> str:
    if shutil.which("vcgencmd"):
        salida = _ejecutar(["vcgencmd", "measure_temp"]).strip()
        if salida:
            return salida
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", encoding="utf-8") as origen:
            return f"temp={int(origen.read().strip()) / 1000:.1f}'C"
    except (OSError, ValueError):
        return "desconocida"


def resumen_sistema() -> dict[str, str]:
    import platform

    datos: dict[str, str] = {"plataforma": f"{platform.system()} "
                                           f"{platform.release()}"}
    if not sys.platform.startswith("linux"):
        datos["modelo"] = platform.machine()
        datos["sistema"] = platform.platform()
        datos["memoria"] = "no consultada en este sistema"
        datos["temperatura"] = "no disponible"
        return datos
    try:
        with open("/proc/device-tree/model", encoding="utf-8", errors="replace") as f:
            datos["modelo"] = f.read().strip("\x00").strip()
    except OSError:
        datos["modelo"] = "desconocido"
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for linea in f:
                if linea.startswith("MemTotal:"):
                    kb = int(linea.split()[1])
                    datos["memoria"] = f"{kb / 1048576:.1f} GiB"
                    break
    except (OSError, ValueError, IndexError):
        datos["memoria"] = "desconocida"
    try:
        with open("/etc/os-release", encoding="utf-8") as f:
            for linea in f:
                if linea.startswith("PRETTY_NAME="):
                    datos["sistema"] = linea.split("=", 1)[1].strip().strip('"')
                    break
    except OSError:
        datos["sistema"] = "desconocido"
    datos["temperatura"] = temperatura_cpu()
    return datos
