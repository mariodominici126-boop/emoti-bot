#!/usr/bin/env python3
"""Diagnóstico del micrófono: distingue ganancia, ruido y límite físico.

Funciona en la Raspberry Pi y en Windows: usa el motor de audio del proyecto,
no `arecord` directamente.

Responde a la pregunta que quedó abierta en la auditoría: el micrófono
"escucha mal a distancia" ¿por el hardware, por la ganancia, por el ruido de
la sala, o porque el umbral del detector estaba mal calculado?

Mide el ruido de fondo y luego la voz a tres distancias, calcula la relación
señal-ruido y emite un veredicto con la acción concreta que corresponde. No
recomienda comprar nada sin haber medido primero.

Uso:
    python3 bin/diagnostico_audio.py
    python3 bin/diagnostico_audio.py --solo-inventario
"""
from __future__ import annotations

import argparse
import dataclasses
import math
import sys
import threading
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from emotibot import ajustes as mod_ajustes  # noqa: E402
from emotibot import registro  # noqa: E402
from emotibot.audio import dispositivos, motores, senal  # noqa: E402
from emotibot.audio.captura import ErrorCaptura, Microfono  # noqa: E402

DISTANCIAS = (30, 60, 100)
SEGUNDOS_MUESTRA = 3
FRASE = "Hola, soy Emoti Bot y estoy probando el micrófono."


def titulo(texto: str) -> None:
    print()
    print(texto)
    print("-" * len(texto))


def db(valor: float, referencia: float) -> float:
    if valor <= 0 or referencia <= 0:
        return 0.0
    return 20.0 * math.log10(valor / referencia)


def mostrar_inventario(config) -> dispositivos.Inventario:
    titulo("Sistema")
    for clave, valor in dispositivos.resumen_sistema().items():
        print(f"  {clave:<13} {valor}")

    titulo("Motores de audio")
    elegido = motores.motor_preferido(config.audio)
    for nombre, estado in motores.diagnostico_motores().items():
        marca = "→" if nombre == elegido else " "
        print(f"  {marca} {nombre:<11} {estado}")
    if config.audio.motor != "auto":
        print(f"  (forzado por configuración: {config.audio.motor})")

    inventario = dispositivos.inventariar(elegido)
    if inventario.predeterminado_captura:
        print(f"  entrada por defecto: {inventario.predeterminado_captura}")
    if inventario.predeterminado_salida:
        print(f"  salida por defecto:  {inventario.predeterminado_salida}")

    titulo("Dispositivos de captura")
    if not inventario.captura:
        print("  Ninguno detectado.")
    for tarjeta in inventario.captura:
        print(f"  tarjeta {tarjeta.indice}: {tarjeta.identificador} "
              f"[{tarjeta.descripcion}]")
        if inventario.motor == motores.ALSA:
            controles = dispositivos.controles_ganancia(tarjeta.indice)
            if controles:
                print(f"      controles: {', '.join(controles[:6])}")
                print(f"      ajusta con: alsamixer -c {tarjeta.indice}")
            else:
                print("      sin controles de ganancia expuestos por ALSA")

    titulo("Dispositivos de salida")
    if not inventario.salida:
        print("  Ninguno detectado.")
    for tarjeta in inventario.salida:
        print(f"  tarjeta {tarjeta.indice}: {tarjeta.identificador} "
              f"[{tarjeta.descripcion}]")

    if inventario.nombres_pcm_captura:
        titulo("Nombres PCM disponibles (para dispositivo_captura)")
        for nombre in inventario.nombres_pcm_captura[:12]:
            print(f"  {nombre}")

    if inventario.motor == motores.PORTAUDIO and inventario.captura:
        titulo("Cómo elegir un micrófono concreto")
        print("  Pon su número en config/ajustes.json → audio.dispositivo_captura")
        print("  o lanza con:  EMOTI_AUDIO_DISPOSITIVO_CAPTURA=1")
        print("  La ganancia se ajusta en el panel de sonido del sistema.")

    if inventario.herramientas_faltantes:
        titulo("Faltan herramientas")
        for falta in inventario.herramientas_faltantes:
            print(f"  {falta}")
    return inventario


def medir(config_audio, segundos: int) -> tuple[float, int]:
    """Graba un bloque fijo y devuelve (rms, pico)."""
    ajuste = dataclasses.replace(config_audio, segundos_grabacion_fija=segundos)
    captura = Microfono(ajuste).grabar_fijo(threading.Event())
    if not captura.pcm:
        raise ErrorCaptura("No se capturó audio.")
    return senal.rms(captura.pcm), senal.pico(captura.pcm)


def veredicto(ruido: float, lecturas: dict[int, float], piso: float) -> None:
    titulo("Veredicto")
    lejana = lecturas.get(max(lecturas), 0.0) if lecturas else 0.0
    snr_lejana = db(lejana, ruido) if ruido > 0 else 0.0

    print(f"  Ruido de fondo:        {ruido:7.0f} RMS")
    for distancia in sorted(lecturas):
        valor = lecturas[distancia]
        print(f"  Voz a {distancia:3d} cm:        {valor:7.0f} RMS   "
              f"SNR {db(valor, ruido):5.1f} dB")
    print(f"  Piso configurado:      {piso:7.0f} RMS")

    print()
    if not lecturas:
        print("  Sin lecturas de voz: no puedo concluir nada.")
        return

    import sys as _sys
    en_linux = _sys.platform.startswith("linux")

    from emotibot.audio import prueba
    codigo = prueba.clasificar(ruido, lejana, piso)   # el mismo que la pantalla
    if codigo == "bajo":
        print("  La voz a la distancia mayor NO alcanza el piso absoluto del")
        print("  detector. Dos causas posibles, en este orden:")
        if en_linux:
            print("    1. Ganancia de entrada baja  → sube el control de")
            print("       captura con alsamixer y repite esta prueba.")
        else:
            print("    1. Ganancia de entrada baja  → Configuración de")
            print("       Windows > Sonido > Entrada > Propiedades del")
            print("       dispositivo, sube el volumen, y repite la prueba.")
        print("    2. Si no hay control de ganancia o ya está al máximo, es un")
        print("       límite físico del micrófono. Entonces, y solo entonces,")
        print("       tiene sentido plantear otro micrófono.")
        print(f"    Mientras tanto puedes bajar el piso: "
              f"EMOTI_AUDIO_PISO_UMBRAL_RMS={int(lejana * 0.7)}")
    elif codigo == "ruido":
        print("  La voz llega, pero el ruido de la sala está muy cerca de ella")
        print(f"  (SNR {snr_lejana:.1f} dB). El detector por energía va a")
        print("  confundirse. Acciones: reducir ruido de fondo, acercar el")
        print("  micrófono, o pasar a un VAD neuronal (Silero), que es el paso")
        print("  previsto para discriminar voz de ruido.")
    else:
        print("  El micrófono es suficiente a esta distancia: la voz supera el")
        print("  piso y la relación señal-ruido es razonable.")
        print("  Si antes 'no te oía', la causa estaba en el cálculo del")
        print("  umbral, no en el hardware. Es exactamente el defecto que")
        print("  corregía emotibot/audio/vad.py.")
        sugerido = max(ruido * 2.2, ruido + 60)
        print(f"  Umbral de inicio que usaría ahora: {sugerido:.0f} RMS")


def main() -> int:
    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument("--solo-inventario", action="store_true",
                            help="No graba nada; solo lista dispositivos.")
    argumentos = analizador.parse_args()

    registro.configurar(a_archivo=False)
    print("EMOTI-BOT · diagnóstico de audio")
    config = mod_ajustes.cargar()
    mostrar_inventario(config)

    if argumentos.solo_inventario:
        return 0
    if not motores.hay_entrada(config.audio):
        print()
        if motores.motor_preferido(config.audio) == motores.ALSA:
            print("Sin arecord no puedo medir: sudo apt install alsa-utils")
        else:
            print("Sin motor de audio no puedo medir: pip install sounddevice")
        return 2

    titulo("Medición de ruido de fondo")
    print(f"  Guarda silencio {SEGUNDOS_MUESTRA} s. Pulsa Enter para empezar.")
    input()
    try:
        ruido, pico_ruido = medir(config.audio, SEGUNDOS_MUESTRA)
    except ErrorCaptura as exc:
        print(f"  Fallo al grabar: {exc}")
        return 2
    print(f"  Ruido: {ruido:.0f} RMS (pico {pico_ruido})")

    lecturas: dict[int, float] = {}
    for distancia in DISTANCIAS:
        titulo(f"Voz a {distancia} cm")
        print(f'  Colócate a {distancia} cm y di, con volumen normal:')
        print(f'    "{FRASE}"')
        print("  Pulsa Enter y empieza a hablar enseguida.")
        input()
        try:
            valor, pico = medir(config.audio, SEGUNDOS_MUESTRA)
        except ErrorCaptura as exc:
            print(f"  Fallo al grabar: {exc}")
            continue
        lecturas[distancia] = valor
        recorte = "  ¡OJO: señal recortada, baja la ganancia!" if pico >= 32700 else ""
        print(f"  Voz: {valor:.0f} RMS (pico {pico}){recorte}")

    veredicto(ruido, lecturas, float(config.audio.piso_umbral_rms))
    print()
    print("Guarda esta salida en docs/BITACORA.md junto con la fecha y el")
    print("equipo donde la mediste: los números de tu PC y los del CrowPi no")
    print("son comparables entre sí.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
