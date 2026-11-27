#!/usr/bin/env python3
"""B1 — Línea base del reconocimiento de voz: 30 intervenciones con guion.

INSTRUMENTO. La medición la hace el responsable, delante del micrófono. Este
script no produce ningún resultado sin una persona hablando.

Qué hace, para cada una de las 30 frases fijas del guion:
  1. Muestra la frase y espera a que pulses Enter.
  2. Graba con la misma cadena que el robot (calibración + VAD), o con
     grabación fija si usas --fijo.
  3. Transcribe con el mismo motor STT configurado.
  4. Te enseña en la terminal lo que se reconoció, junto con una categoría
     automática, y te deja corregirla.

Categorías (§B1): correcta · error_reconocimiento · transcripcion_vacia ·
fallo_motor · corte_prematuro · fallo_captura · sin_voz.

PRIVACIDAD. Lo reconocido se ve en la terminal y no se guarda. El archivo de
resultados lleva el número de la frase, la categoría, los errores de palabra
y los tiempos. Ni texto ni audio. Di solo las frases del guion.

Uso (desde la raíz del proyecto, con el intérprete del entorno virtual):
    .venv\\Scripts\\python.exe bin\\medir_stt.py
    .venv\\Scripts\\python.exe bin\\medir_stt.py --fijo
    .venv\\Scripts\\python.exe bin\\medir_stt.py --desde 12      # retomar
    .venv\\Scripts\\python.exe bin\\medir_stt.py --resumir logs\\mediciones\\b1_stt_....csv
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import platform
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

from emotibot import __version__, metricas, registro, rutas  # noqa: E402
from emotibot import ajustes as mod_ajustes  # noqa: E402
from emotibot import stt as mod_stt  # noqa: E402
from emotibot.audio.captura import ErrorCaptura, Microfono, MotivoFin  # noqa: E402
from emotibot.medicion import (CATEGORIAS_STT, GUION_STT, clasificar_stt,  # noqa: E402
                               errores_de_palabra, intervalo_wilson)

COLUMNAS = ("indice", "frase", "palabras_ref", "errores", "categoria_auto",
            "categoria", "corregida", "modo", "motivo_captura", "t_primera_voz",
            "t_voz_util", "t_stt")
ATAJOS = {"c": "correcta", "r": "error_reconocimiento", "v": "transcripcion_vacia",
          "m": "fallo_motor", "p": "corte_prematuro", "d": "fallo_captura",
          "s": "sin_voz"}
TECNICOS = ("fallo_motor", "fallo_captura")


def condiciones(argumentos, config, microfono, stt) -> dict:
    print("\nCondiciones de la prueba (se guardan con los resultados).")
    lugar = input("  Sala y ruido (p. ej. «salón, ventana cerrada, TV apagada»): ").strip()
    distancia = input("  Micrófono y distancia (p. ej. «USB, 40 cm»): ").strip()
    hablante = input("  Hablante (iniciales o «responsable»; sin datos personales): ").strip()
    return {
        "fecha": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "version_emotibot": __version__,
        "python": sys.executable,
        "sistema": f"{platform.system()} {platform.release()} {platform.machine()}",
        "motor_audio": microfono.motor(),
        "dispositivo_captura": config.audio.dispositivo_captura,
        "motor_stt": stt.nombre,
        "modelo_whisper": config.stt.modelo_whisper,
        "computo_whisper": config.stt.computo_whisper,
        "silencio_final_s": config.audio.silencio_final_s,
        "modo": "fija" if argumentos.fijo else "automatica",
        "sala": lugar, "microfono_distancia": distancia, "hablante": hablante,
    }


def una_intervencion(indice, frase, microfono, stt, fijo) -> dict:
    cancelar = threading.Event()
    fila = {"indice": indice, "frase": indice, "palabras_ref": len(frase.split()),
            "modo": "fija" if fijo else "automatica", "errores": "",
            "motivo_captura": "", "t_primera_voz": "", "t_voz_util": "", "t_stt": ""}
    try:
        if fijo:
            print("  ● Grabando… habla ya.")
            captura = microfono.grabar_fijo(cancelar)
        else:
            captura = microfono.escuchar(
                cancelar, al_cambiar_fase=lambda _f, texto: print(f"  · {texto}"))
    except ErrorCaptura as exc:
        print(f"  ✗ Fallo de captura: {exc}")
        fila["categoria_auto"] = clasificar_stt(frase, None, error_captura=True)
        return fila
    fila["motivo_captura"] = captura.motivo.value
    fila["t_primera_voz"] = round(captura.t_primera_voz, 3)
    fila["t_voz_util"] = round(captura.duracion_util_s, 3)
    if not captura.hay_voz:
        fila["categoria_auto"] = clasificar_stt(frase, None, sin_voz=True)
        print("  ✗ No se detectó voz.")
        return fila

    try:
        transcripcion = stt.transcribir(captura.pcm, captura.frecuencia)
    except mod_stt.ErrorStt as exc:
        print(f"  ✗ Fallo del motor STT: {exc}")
        fila["categoria_auto"] = clasificar_stt(frase, None, error_motor=True)
        return fila
    fila["t_stt"] = round(transcripcion.segundos, 3)
    errores, _ = errores_de_palabra(frase, transcripcion.texto)
    fila["errores"] = errores
    fila["categoria_auto"] = clasificar_stt(frase, transcripcion.texto)
    if captura.motivo is MotivoFin.LIMITE and fila["categoria_auto"] == "correcta":
        print("  (aviso: se alcanzó el máximo de grabación)")
    # Solo en pantalla. No se guarda.
    print(f"  Whisper oyó: «{transcripcion.texto}»")
    print(f"  Errores de palabra: {errores}")
    return fila


def preguntar_categoria(fila: dict) -> str | None:
    auto = fila["categoria_auto"]
    opciones = " ".join(f"{k}={v}" for k, v in ATAJOS.items())
    respuesta = input(f"  Categoría automática: {auto}. Enter acepta; corrige "
                      f"con una letra ({opciones}); x repite: ").strip().lower()
    if respuesta == "x":
        return None
    return ATAJOS.get(respuesta, auto)


def resumir(filas: list[dict], meta: dict | None = None) -> str:
    total = len(filas)
    lineas = [f"Intervenciones: {total}"]
    if not total:
        return "Sin intervenciones."
    for categoria in CATEGORIAS_STT:
        n = sum(1 for f in filas if f["categoria"] == categoria)
        bajo, alto = intervalo_wilson(n, total)
        lineas.append(f"  {categoria:<22}{n:>4}  {n / total:6.1%}  "
                      f"(IC95 {bajo:.1%}–{alto:.1%})")
    tecnicos = sum(1 for f in filas if f["categoria"] in TECNICOS)
    bajo, alto = intervalo_wilson(tecnicos, total)
    lineas.append(f"Fallos técnicos: {tecnicos}/{total} = {tecnicos / total:.1%} "
                  f"(IC95 {bajo:.1%}–{alto:.1%})")
    errores = sum(int(f["errores"]) for f in filas if str(f["errores"]).strip())
    palabras = sum(int(f["palabras_ref"]) for f in filas if str(f["errores"]).strip())
    if palabras:
        lineas.append(f"Tasa de error de palabra (WER), sobre las transcritas: "
                      f"{errores / palabras:.1%} ({errores}/{palabras})")
    corregidas = sum(1 for f in filas if str(f.get("corregida")) in ("1", "True"))
    lineas.append(f"Categorías corregidas a mano: {corregidas}")
    lineas.append("Ojo: 30 intervenciones sin fallos no demuestran fiabilidad "
                  "perfecta; el intervalo de arriba dice hasta dónde puede llegar.")
    lineas.append("")
    lineas.append(comparar_con_registros_previos())
    return "\n".join(lineas)


def comparar_con_registros_previos() -> str:
    """Referencia: los registros previos daban 4 fallos técnicos en 22 (18 %)."""
    filas = metricas.leer_csv()
    if not filas:
        return "Registros previos: logs/latencia.csv vacío o inexistente."
    fallos = sum(1 for f in filas if f.get("resultado") in ("error_stt", "error_audio"))
    return (f"Registros previos (logs/latencia.csv, uso normal, sin guion): "
            f"{fallos} fallos técnicos en {len(filas)} interacciones "
            f"({fallos / len(filas):.0%}). No es la misma prueba: sirve de "
            f"orientación, no de comparación estricta.")


def main() -> int:
    analizador = argparse.ArgumentParser(description=__doc__,
                                         formatter_class=argparse.RawDescriptionHelpFormatter)
    analizador.add_argument("--fijo", action="store_true",
                            help="Grabación de duración fija, sin VAD.")
    analizador.add_argument("--desde", type=int, default=1,
                            help="Frase por la que empezar (1-30).")
    analizador.add_argument("--resumir", type=Path, default=None,
                            help="Solo resume un CSV ya hecho.")
    argumentos = analizador.parse_args()
    registro.configurar(a_archivo=False)
    logging.getLogger("emotibot").setLevel(logging.WARNING)
    try:                       # consola de Windows en cp1252
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    if argumentos.resumir:
        with argumentos.resumir.open(newline="", encoding="utf-8") as origen:
            print(resumir(list(csv.DictReader(origen))))
        return 0

    config = mod_ajustes.cargar()
    microfono = Microfono(config.audio)
    if not microfono.disponible():
        print("No hay micrófono disponible. Ejecuta bin/diagnostico_audio.py.")
        return 1
    stt = mod_stt.crear(config, None)       # sin respaldo remoto: no gasta cuota
    if not stt.disponible():
        print("No hay motor STT local. Revisa faster-whisper.")
        return 1

    destino_dir = rutas.LOGS / "mediciones"
    rutas.asegurar_directorio(destino_dir)
    marca = time.strftime("%Y%m%d-%H%M%S")
    destino = destino_dir / f"b1_stt_{marca}.csv"
    meta = condiciones(argumentos, config, microfono, stt)
    (destino_dir / f"b1_stt_{marca}.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    filas: list[dict] = []
    with destino.open("w", newline="", encoding="utf-8") as salida:
        escritor = csv.DictWriter(salida, fieldnames=list(COLUMNAS))
        escritor.writeheader()
        indice = max(1, argumentos.desde)
        while indice <= len(GUION_STT):
            frase = GUION_STT[indice - 1]
            print(f"\n[{indice}/{len(GUION_STT)}] Di con naturalidad:\n    «{frase}»")
            input("  Pulsa Enter y espera a «Te escucho»… ")
            fila = una_intervencion(indice, frase, microfono, stt, argumentos.fijo)
            categoria = preguntar_categoria(fila)
            if categoria is None:
                continue                         # repetir la misma frase
            fila["categoria"] = categoria
            fila["corregida"] = int(categoria != fila["categoria_auto"])
            escritor.writerow(fila)
            salida.flush()
            filas.append(fila)
            indice += 1

    print("\n" + resumir(filas, meta))
    print(f"\nResultados: {destino}")
    stt.cerrar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
