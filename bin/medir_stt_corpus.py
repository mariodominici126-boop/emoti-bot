#!/usr/bin/env python3
"""Banco de regresión del reconocimiento con un corpus de voz real.

Transcribe el corpus con los DOS modelos del robot, por el mismo código que
usa la aplicación (`WhisperLocal`):
  - despertar: `stt.modelo_activacion` CON la pista del nombre;
  - conversación: `stt.modelo_whisper` SIN pista;
y mide, con varias pasadas:
  - aciertos por frase contra la referencia (exactas y, si la frase tiene
    una «clave», si la clave llegó);
  - segundos y CPU por frase (mediana, p90, máximo) y la proporción frente a
    la duración del audio;
  - tiempo de carga de cada modelo;
  - memoria: sin modelos, con el del despertar, con los dos cargados, y el
    pico (Linux: /proc/self/status; Windows: Get-Process);
  - temperatura de la CPU antes y después (Raspberry: vcgencmd).

PRIVACIDAD. El corpus es voz de una persona: NO va en el proyecto ni en el
paquete. Vive en la carpeta de configuración de la máquina (la de los
ajustes y las credenciales), por defecto `<config del usuario>/corpus/`:
  voz.wav          el audio (mono, 16 bits, 16 kHz)
  referencia.json  los segmentos [inicio, fin] en segundos y lo que se dijo
El resultado (`logs/mediciones/stt_corpus_*.json`) lleva solo números y
aciertos. Lo transcrito se ve en pantalla con --mostrar-textos y no se guarda.

Uso:
    python bin/medir_stt_corpus.py
    python bin/medir_stt_corpus.py --pasadas 5 --mostrar-textos
    python bin/medir_stt_corpus.py --corpus /ruta/al/corpus
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import statistics
import subprocess
import sys
import time
import unicodedata
import wave
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

from emotibot import ajustes as mod_ajustes, rutas  # noqa: E402
from emotibot.audio import dispositivos  # noqa: E402


def plano(texto: str) -> list[str]:
    t = unicodedata.normalize("NFD", (texto or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.findall(r"[a-zñ]+", t)


def exacta(referencia: str, texto: str) -> bool:
    return plano(referencia) == plano(texto)


def memoria_mb() -> dict[str, float]:
    """Memoria del proceso: actual y pico, en MB."""
    if Path("/proc/self/status").is_file():
        campos = {}
        for linea in Path("/proc/self/status").read_text().splitlines():
            if linea.startswith(("VmRSS:", "VmHWM:")):
                nombre, valor = linea.split(":")
                campos[nombre] = int(valor.split()[0]) / 1024
        return {"actual": campos.get("VmRSS", 0.0), "pico": campos.get("VmHWM", 0.0)}
    if os.name == "nt":
        orden = (f"$p=Get-Process -Id {os.getpid()}; "
                 "'{0} {1}' -f $p.WorkingSet64,$p.PeakWorkingSet64")
        salida = subprocess.run(["powershell", "-NoProfile", "-Command", orden],
                                capture_output=True, text=True).stdout.split()
        actual, pico = (int(v) / 2**20 for v in salida)
        return {"actual": actual, "pico": pico}
    return {"actual": 0.0, "pico": 0.0}


def leer_corpus(carpeta: Path, wav: Path | None = None) -> tuple[bytes, int, list[dict]]:
    with wave.open(str(wav or carpeta / "voz.wav")) as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise SystemExit("voz.wav tiene que ser mono y de 16 bits.")
        frecuencia, pcm = w.getframerate(), w.readframes(w.getnframes())
    referencia = json.loads((carpeta / "referencia.json").read_text(encoding="utf-8"))
    frases = []
    for frase in referencia["frases"]:
        a, b = referencia["segmentos"][frase["seg"]]
        frases.append({**frase, "pcm": pcm[int(a * frecuencia) * 2:int(b * frecuencia) * 2],
                       "duracion": b - a})
    return pcm, frecuencia, frases


def p90(valores):
    ordenados = sorted(valores)
    return ordenados[min(len(ordenados) - 1, int(0.9 * len(ordenados)))]


def medir_modelo(transcriptor, frases, frecuencia, pasadas, mostrar):
    textos = [[] for _ in frases]
    segundos, cpu = [[] for _ in frases], [[] for _ in frases]
    for _ in range(pasadas):
        for i, frase in enumerate(frases):
            w0, c0 = time.perf_counter(), time.process_time()
            texto = transcriptor.transcribir(frase["pcm"], frecuencia).texto
            segundos[i].append(time.perf_counter() - w0)
            cpu[i].append(time.process_time() - c0)
            textos[i].append(texto)
    filas = []
    for i, frase in enumerate(frases):
        bien = sum(exacta(frase["texto"], t) for t in textos[i])
        clave = frase.get("clave")
        con_clave = (sum(" ".join(plano(clave)) in " ".join(plano(t)) for t in textos[i])
                     if clave else None)
        filas.append({"n": frase["n"], "exactas": bien, "clave": con_clave,
                      "s": statistics.median(segundos[i]), "cpu": statistics.median(cpu[i]),
                      "duracion": frase["duracion"],
                      "iguales_entre_pasadas": len(set(textos[i])) == 1})
        if mostrar and bien < pasadas:
            print(f"      {frase['n']}. {sorted(set(textos[i]))}")
    return filas


def resumen(nombre, filas, pasadas, carga, numeros):
    sel = [f for f in filas if f["n"] in numeros]
    s = [f["s"] for f in sel]
    rtf = [f["s"] / f["duracion"] for f in sel]
    exactas = sum(f["exactas"] for f in sel)
    print(f"  {nombre}: carga {carga:.1f} s · exactas {exactas}/{len(sel) * pasadas} · "
          f"s/frase mediana {statistics.median(s):.2f}, p90 {p90(s):.2f}, máx {max(s):.2f} · "
          f"CPU/frase {statistics.median(f['cpu'] for f in sel):.2f} s · "
          f"×{statistics.median(rtf):.2f} del audio")
    for n in sorted(set(f["n"] for f in sel)):
        grupo = [f for f in sel if f["n"] == n]
        clave = [f["clave"] for f in grupo if f["clave"] is not None]
        print(f"     frase {n}: {sum(f['exactas'] for f in grupo)}/{len(grupo) * pasadas}"
              + (f" · clave {sum(clave)}/{len(clave) * pasadas}" if clave else ""))
    return {"carga_s": carga, "exactas": exactas, "total": len(sel) * pasadas,
            "s_mediana": statistics.median(s), "s_p90": p90(s), "s_max": max(s),
            "cpu_mediana": statistics.median(f["cpu"] for f in sel),
            "rtf_mediana": statistics.median(rtf), "por_frase": sel}


def main() -> int:
    analizador = argparse.ArgumentParser(description=__doc__,
                                         formatter_class=argparse.RawDescriptionHelpFormatter)
    analizador.add_argument("--corpus", type=Path, default=rutas.CONFIG_USUARIO / "corpus")
    analizador.add_argument("--wav", type=Path, default=None,
                            help="El audio, si no está como voz.wav dentro del corpus.")
    analizador.add_argument("--pasadas", type=int, default=3)
    analizador.add_argument("--mostrar-textos", action="store_true",
                            help="Enseña en pantalla lo transcrito cuando falla (no se guarda).")
    argumentos = analizador.parse_args()
    if not (argumentos.wav or argumentos.corpus / "voz.wav").is_file():
        print(f"No encuentro {argumentos.corpus / 'voz.wav'}. Copia allí el corpus "
              "(voz.wav y referencia.json); no va en el proyecto.")
        return 2

    from emotibot.stt.whisper_local import PISTA_NOMBRE, WhisperLocal
    config = mod_ajustes.cargar()
    _, frecuencia, frases = leer_corpus(argumentos.corpus, argumentos.wav)
    despertar = {f["n"] for f in frases if f.get("despertar")}
    conversacion = {f["n"] for f in frases} - despertar
    print(f"Corpus: {len(frases)} frases · {argumentos.pasadas} pasadas · "
          f"{platform.machine()} · {os.cpu_count()} núcleos")
    resultado = {"fecha": datetime.now().isoformat(timespec="seconds"),
                 "sistema": dispositivos.resumen_sistema(), "pasadas": argumentos.pasadas,
                 "temperatura_antes": dispositivos.temperatura_cpu(),
                 "memoria_mb": {"sin_modelos": memoria_mb()}}

    t = time.perf_counter()
    rapido = WhisperLocal(config.stt, modelo=config.stt.modelo_activacion, pista=PISTA_NOMBRE)
    carga_d = time.perf_counter() - t
    resultado["memoria_mb"]["con_despertar"] = memoria_mb()
    t = time.perf_counter()
    lento = WhisperLocal(config.stt, modelo=config.stt.modelo_whisper)
    carga_c = time.perf_counter() - t
    resultado["memoria_mb"]["con_los_dos"] = memoria_mb()

    print(f"\nDespertar: {config.stt.modelo_activacion} con pista")
    filas = medir_modelo(rapido, frases, frecuencia, argumentos.pasadas, argumentos.mostrar_textos)
    resultado["despertar"] = resumen("frases de despertar", filas, argumentos.pasadas, carga_d,
                                     despertar)
    print(f"\nConversación: {config.stt.modelo_whisper} sin pista")
    filas = medir_modelo(lento, frases, frecuencia, argumentos.pasadas, argumentos.mostrar_textos)
    resultado["conversacion"] = resumen("frases de conversación", filas, argumentos.pasadas,
                                        carga_c, conversacion)
    resultado["memoria_mb"]["final"] = memoria_mb()
    resultado["temperatura_despues"] = dispositivos.temperatura_cpu()

    m = resultado["memoria_mb"]
    print(f"\nMemoria (MB): sin modelos {m['sin_modelos']['actual']:.0f} · con el del "
          f"despertar {m['con_despertar']['actual']:.0f} · con los dos "
          f"{m['con_los_dos']['actual']:.0f} · pico {m['final']['pico']:.0f}")
    print(f"Temperatura: {resultado['temperatura_antes']} → {resultado['temperatura_despues']}")
    salida = rutas.LOGS / "mediciones" / f"stt_corpus_{datetime.now():%Y%m%d-%H%M%S}.json"
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Resultados (solo números): {salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
