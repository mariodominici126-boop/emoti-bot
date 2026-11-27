#!/usr/bin/env python3
"""Qué hay instalado, qué falta y cómo instalarlo EN ESTE sistema.

Primer comando que conviene ejecutar en una máquina nueva. Distingue lo
imprescindible de lo opcional, y dice el comando concreto de Windows, macOS o
Linux en lugar de dar una receta genérica.

Nada de esto hace falta para que el robot arranque: el rostro, las actividades
y la ruta de seguridad funcionan solo con la biblioteca estándar y Tkinter.
Cada pieza añade una capacidad.

Uso:
    python bin/comprobar_entorno.py
"""
from __future__ import annotations

import logging
import platform
import shutil
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from emotibot import ajustes as mod_ajustes  # noqa: E402
from emotibot import credenciales, registro, rutas  # noqa: E402
from emotibot.agentes_opcionales import importar_opcional  # noqa: E402
from emotibot.audio import motores  # noqa: E402

ES_WINDOWS = sys.platform.startswith("win")
ES_MAC = sys.platform == "darwin"
ES_LINUX = sys.platform.startswith("linux")

OK = "[ OK ]"
FALTA = "[falta]"
AVISO = "[ ! ]"


def titulo(texto: str) -> None:
    print()
    print(texto)
    print("-" * len(texto))


def linea(marca: str, etiqueta: str, detalle: str = "") -> None:
    print(f"  {marca} {etiqueta:<26} {detalle}")


def pip_de_este_python() -> str:
    return f"{Path(sys.executable).name} -m pip install"


def comprobar_python() -> bool:
    titulo("Python")
    version = sys.version_info
    suficiente = version >= (3, 10)
    linea(OK if suficiente else FALTA, "versión",
          f"{version.major}.{version.minor}.{version.micro}")
    if not suficiente:
        print("     Hace falta Python 3.10 o superior.")
    linea(OK, "ejecutable", sys.executable)
    linea(OK, "sistema", f"{platform.system()} {platform.release()} "
                         f"({platform.machine()})")

    grafica = importar_opcional("tkinter") is not None
    if grafica:
        linea(OK, "tkinter (interfaz)", "disponible")
    else:
        linea(FALTA, "tkinter (interfaz)", "sin él no hay rostro")
        if ES_LINUX:
            print("     sudo apt install python3-tk")
        elif ES_WINDOWS:
            print("     Reinstala Python marcando «tcl/tk and IDLE».")
        else:
            print("     brew install python-tk")
    return suficiente and grafica


def comprobar_audio(config) -> bool:
    titulo("Audio (micrófono y altavoz)")
    elegido = motores.motor_preferido(config.audio)
    estados = motores.diagnostico_motores()
    for nombre, estado in estados.items():
        marca = OK if estado == "disponible" else FALTA
        flecha = "→" if nombre == elegido else " "
        linea(marca, f"{flecha} motor {nombre}", estado)

    hay = motores.hay_entrada(config.audio)
    if hay:
        print(f"\n  Se usará el motor «{elegido}».")
        return True

    print("\n  Sin motor de audio no hay micrófono ni voz hablada.")
    print("  El rostro y las actividades siguen funcionando.")
    if ES_LINUX and shutil.which("arecord") is None:
        print("     Opción A:  sudo apt install alsa-utils")
        print(f"     Opción B:  {pip_de_este_python()} sounddevice")
        print("                sudo apt install libportaudio2")
    else:
        print(f"     {pip_de_este_python()} sounddevice")
    return False


def comprobar_voz(config) -> None:
    titulo("Voz (síntesis)")

    piper = importar_opcional("piper")
    modelo = mod_ajustes.ruta_piper(config)
    if piper is None:
        linea(FALTA, "piper-tts", "voz neuronal, la que suena bien")
        print(f"     {pip_de_este_python()} piper-tts")
    elif not modelo.is_file():
        linea(AVISO, "piper-tts", "instalado, pero falta el modelo de voz")
        print(f"     esperado en: {modelo}")
        print(f"     {Path(sys.executable).name} -m piper.download_voices \\")
        print(f"         --data-dir {modelo.parent} es_MX-claude-high")
    else:
        linea(OK, "piper-tts", f"modelo {modelo.name}")

    if shutil.which("espeak-ng"):
        linea(OK, "espeak-ng", "respaldo disponible")
    else:
        linea(AVISO, "espeak-ng", "respaldo de voz no disponible")
        if ES_WINDOWS:
            print("     winget install eSpeak-NG.eSpeak-NG")
            print("     (y reabre la terminal para que entre en el PATH)")
        elif ES_MAC:
            print("     brew install espeak-ng")
        else:
            print("     sudo apt install espeak-ng")

    if piper is None and not shutil.which("espeak-ng"):
        print("\n  Sin ninguno de los dos, EMOTI-BOT funciona en silencio.")


def comprobar_reconocimiento(config) -> None:
    titulo("Reconocimiento de voz")
    if importar_opcional("faster_whisper") is None:
        linea(FALTA, "faster-whisper", "sin él no entiende lo que dices")
        print(f"     {pip_de_este_python()} faster-whisper")
        print("     La primera ejecución descarga el modelo "
              f"«{config.stt.modelo_whisper}» (~150 MB).")
    else:
        linea(OK, "faster-whisper", f"modelo {config.stt.modelo_whisper}")
        print("     El audio se reconoce en el equipo: no sale de aquí.")


def comprobar_inteligencia(config) -> None:
    from emotibot.ia.openai_compat import cargar_endpoints

    titulo("Inteligencia")
    endpoints = cargar_endpoints(rutas.ARCHIVO_PROVEEDORES)
    if not endpoints:
        linea(AVISO, "config/proveedores.json", "sin proveedores definidos")

    for nombre, endpoint in endpoints.items():
        if not endpoint.configurado:
            linea(FALTA, nombre, "falta url o modelo")
            print(f"     Edita config/proveedores.json → {nombre}.url")
            continue
        clave = credenciales.cargar(endpoint.clave) if endpoint.clave else ""
        if endpoint.necesita_clave and not clave:
            linea(AVISO, nombre, f"{endpoint.modelo}, sin clave")
            print(f"     Pulsa K en EMOTI-BOT y elige «{endpoint.clave}», o")
            print(f"     exporta EMOTI_CLAVE_{endpoint.clave.upper()}")
        else:
            detalle = endpoint.modelo
            if endpoint.necesita_clave:
                detalle += f" · {credenciales.huella(clave)}"
            linea(OK, nombre, detalle)

    if importar_opcional("google.genai") is None:
        linea(AVISO, "google-genai", "respaldo de Gemini no instalado")
    else:
        clave = credenciales.cargar("gemini")
        linea(OK if clave else AVISO, "gemini (respaldo)",
              f"{config.ia.modelo_remoto} · {credenciales.huella(clave)}")

    print(f"\n  Las claves se guardan en {rutas.ARCHIVO_CREDENCIALES}")
    print("  Sin claves ni conexión, el robot responde con su guion local y")
    print("  las actividades funcionan igual.")


def comprobar_seguridad() -> None:
    titulo("Ruta de seguridad")
    from emotibot.dialogo import Guardia

    guardia = Guardia()
    avisos = guardia.advertencias_arranque()
    if not avisos:
        linea(OK, "config/crisis.json", "verificado")
        return
    linea(AVISO, "config/crisis.json", "revisar antes de usar con otras personas")
    for aviso in avisos:
        print(f"     · {aviso}")


def resumen(listo_basico: bool, hay_audio: bool) -> None:
    titulo("Qué puedes hacer ahora")
    if listo_basico:
        print("  python bin/vista_previa_rostro.py     ver las expresiones")
        print("  python -m unittest discover -s tests -t .   pruebas")
        print("  python bin/emotibot.py                abrir el robot")
    else:
        print("  Instala primero Python 3.10+ con tkinter.")
        return
    if hay_audio:
        print("  python bin/diagnostico_audio.py       medir el micrófono")
    else:
        print("  (el micrófono y la voz necesitan un motor de audio)")


def main() -> int:
    # Sin ruido de registro: este script ya explica cada hallazgo en su
    # sección. El nivel se fija sobre el logger, porque importar los módulos
    # del proyecto ya dejó el registro configurado.
    registro.configurar(a_archivo=False)
    logging.getLogger("emotibot").setLevel(logging.ERROR)
    config = mod_ajustes.cargar()
    print("EMOTI-BOT · comprobación del entorno")

    listo_basico = comprobar_python()
    hay_audio = comprobar_audio(config)
    comprobar_voz(config)
    comprobar_reconocimiento(config)
    comprobar_inteligencia(config)
    comprobar_seguridad()
    resumen(listo_basico, hay_audio)
    print()
    return 0 if listo_basico else 1


if __name__ == "__main__":
    sys.exit(main())
