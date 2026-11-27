#!/usr/bin/env python3
"""B3 — Evaluación del VAD con pausas controladas.

INSTRUMENTO. La medición la hace el responsable, hablando. Con --sintetico
solo se comprueba que el instrumento funciona: esa salida NO es una medición
y lo dice en cada línea.

Por qué así. Pedir a una persona que haga una pausa «de 0,8 s» no da
0,8 s. Por eso:

  1. Se graban 2 s de ruido de la sala, sin hablar.
  2. Se graba cada frase del guion en DOS MITADES por separado (5 frases,
     10 grabaciones cortas de duración fija). El recorte de cada mitad se
     hace por energía, sin el VAD que se evalúa.
  3. Se unen las mitades con una pausa EXACTA de ruido real de la sala:
     0,3 · 0,5 · 0,8 · 1,2 s. Son 20 intervenciones por umbral.
  4. Cada intervención pasa por el detector real, con el umbral vigente
     (0,6 s) y con 0,8 · 1,0 · 1,2 s, sobre las mismas grabaciones.

Como se sabe que la 2.ª mitad continúa la 1.ª, un cierre durante la pausa
es un corte prematuro, nunca una intervención nueva legítima. Se registra:
pausa, si hubo corte, si se conservó la intervención completa, el tiempo
desde la última voz hasta el cierre y, con --transcribir, los errores de
palabra de lo que habría llegado a Whisper.

PRIVACIDAD. Todo el audio vive en memoria y se descarta al terminar. El
archivo de resultados lleva números, no audio ni texto reconocido.

Uso:
    .venv\\Scripts\\python.exe bin\\medir_vad.py
    .venv\\Scripts\\python.exe bin\\medir_vad.py --transcribir
    .venv\\Scripts\\python.exe bin\\medir_vad.py --sintetico     # autoprueba
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import logging
import sys
import threading
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))
try:  # consola de Windows en cp1252: que se vean tildes y símbolos
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

from emotibot import __version__, registro, rutas  # noqa: E402
from emotibot import ajustes as mod_ajustes  # noqa: E402
from emotibot.audio import senal  # noqa: E402
from emotibot.medicion import (GUION_VAD, PAUSAS_B3, SILENCIOS_B3,  # noqa: E402
                               errores_de_palabra, recortar_a_voz,
                               ruido_sintetico, simular_pausa, tabla_pausas,
                               voz_sintetica)

SEGUNDOS_POR_MITAD = 4


def grabar_mitades(config) -> tuple[bytes, list[tuple[bytes, bytes]], int]:
    from emotibot.audio.captura import Microfono
    audio = dataclasses.replace(config.audio,
                                segundos_grabacion_fija=SEGUNDOS_POR_MITAD)
    microfono = Microfono(audio)
    if not microfono.disponible():
        raise SystemExit("No hay micrófono disponible.")
    cancelar = threading.Event()
    frecuencia = audio.frecuencia_captura

    input("\n1) Ruido de la sala: pulsa Enter y NO hables durante 4 s… ")
    ruido = microfono.grabar_fijo(cancelar).pcm
    ruido = ruido[len(ruido) // 4:]            # sin el arranque del dispositivo
    ruido_rms = senal.rms(ruido)
    print(f"   Ruido medido: {ruido_rms:.0f} RMS")

    pares: list[tuple[bytes, bytes]] = []
    for n, (a, b) in enumerate(GUION_VAD, 1):
        mitades = []
        for parte, texto in (("1.ª", a), ("2.ª", b)):
            while True:
                input(f"\n[{n}/5] {parte} mitad. Enter y di: «{texto}» "
                      f"(tienes {SEGUNDOS_POR_MITAD} s)… ")
                pcm = recortar_a_voz(microfono.grabar_fijo(cancelar).pcm,
                                     frecuencia, ruido_rms,
                                     float(audio.piso_umbral_rms))
                if senal.duracion_s(pcm, frecuencia) >= 0.3:
                    print(f"   Voz: {senal.duracion_s(pcm, frecuencia):.2f} s")
                    mitades.append(pcm)
                    break
                print("   No te oí bien; repetimos esa mitad.")
        pares.append((mitades[0], mitades[1]))
    return ruido, pares, frecuencia


def sinteticas(config) -> tuple[bytes, list[tuple[bytes, bytes]], int]:
    frecuencia = config.audio.frecuencia_captura
    pares = [(voz_sintetica(1.0 + 0.1 * i, frecuencia, semilla=10 + i),
              voz_sintetica(1.4, frecuencia, semilla=50 + i))
             for i in range(len(GUION_VAD))]
    return ruido_sintetico(2.0, frecuencia), pares, frecuencia


def main() -> int:
    analizador = argparse.ArgumentParser(description=__doc__,
                                         formatter_class=argparse.RawDescriptionHelpFormatter)
    analizador.add_argument("--sintetico", action="store_true",
                            help="Autoprueba del instrumento con señal sintética.")
    analizador.add_argument("--transcribir", action="store_true",
                            help="Transcribe cada intervención (Whisper local).")
    argumentos = analizador.parse_args()
    registro.configurar(a_archivo=False)
    logging.getLogger("emotibot").setLevel(logging.WARNING)
    try:                       # consola de Windows en cp1252
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    config = mod_ajustes.cargar()

    etiqueta = "SINTETICO-NO-ES-MEDICION" if argumentos.sintetico else "real"
    ruido, pares, frecuencia = (sinteticas(config) if argumentos.sintetico
                                else grabar_mitades(config))

    stt = None
    if argumentos.transcribir and not argumentos.sintetico:
        from emotibot import stt as mod_stt
        stt = mod_stt.crear(config, None)
        if not stt.disponible():
            print("Sin STT local: sigo sin transcribir.")
            stt = None

    filas, resultados = [], []
    for silencio in SILENCIOS_B3:
        for n, (a, b) in enumerate(pares, 1):
            for pausa in PAUSAS_B3:
                r = simular_pausa(a, b, ruido, pausa, frecuencia, config.audio,
                                  silencio_final_s=silencio)
                resultados.append(r)
                errores = ""
                if stt is not None and r.pcm_recortado:
                    referencia = " ".join(GUION_VAD[n - 1])
                    texto = stt.transcribir(r.pcm_recortado, frecuencia).texto
                    errores = errores_de_palabra(referencia, texto)[0]
                filas.append({
                    "origen": etiqueta, "silencio_final_s": silencio,
                    "frase": n, "pausa_s": pausa,
                    "corte_prematuro": int(r.corte_prematuro),
                    "intervencion_completa": int(r.intervencion_completa),
                    "cierre_desde_ultima_voz_s":
                        "" if r.cierre_desde_ultima_voz_s is None
                        else round(r.cierre_desde_ultima_voz_s, 3),
                    "sin_voz": int(r.sin_voz),
                    "errores_palabra": errores,
                })

    tabla = tabla_pausas(resultados)
    print(f"\nTabla pausa → tasa de corte  [{etiqueta}]")
    print(f"{'umbral':>7} {'pausa':>6} {'n':>3} {'cortes':>7} {'tasa':>6} "
          f"{'IC95':>13} {'cierre':>7}")
    for f in tabla:
        cierre = "" if f["cierre_mediano_s"] is None else f"{f['cierre_mediano_s']:.2f}s"
        print(f"{f['silencio_final_s']:>6.1f}s {f['pausa_s']:>5.1f}s {f['n']:>3} "
              f"{f['cortes']:>7} {f['tasa_corte']:>6.0%} "
              f"{f['ic95_bajo']:>5.0%}–{f['ic95_alto']:<5.0%} {cierre:>7}")
    print("\n«cierre» es el tiempo desde la última voz hasta cerrar el turno: lo")
    print("que se gana en cortes se paga en espera. Elige con las dos columnas.")
    if argumentos.sintetico:
        print("\nAUTOPRUEBA: señal sintética. No sirve para elegir el umbral.")

    destino_dir = rutas.LOGS / "mediciones"
    rutas.asegurar_directorio(destino_dir)
    marca = time.strftime("%Y%m%d-%H%M%S")
    prefijo = destino_dir / f"b3_vad_{etiqueta.lower()}_{marca}"
    with prefijo.with_suffix(".csv").open("w", newline="", encoding="utf-8") as s:
        escritor = csv.DictWriter(s, fieldnames=list(filas[0]))
        escritor.writeheader()
        escritor.writerows(filas)
    prefijo.with_suffix(".json").write_text(json.dumps({
        "origen": etiqueta, "fecha": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "version_emotibot": __version__, "python": sys.executable,
        "ajustes_audio": dataclasses.asdict(config.audio), "tabla": tabla,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nResultados: {prefijo.with_suffix('.csv')}")
    if stt is not None:
        stt.cerrar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
