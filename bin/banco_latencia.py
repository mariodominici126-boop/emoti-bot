#!/usr/bin/env python3
"""Resumen de latencia y banco de pruebas de la síntesis de voz.

La auditoría dejó claro que "la nueva versión es más rápida" no es evidencia.
Evidencia es la mediana y el p90 de cada etapa, sobre un número suficiente de
interacciones, antes y después del cambio.

Uso:
    python3 bin/banco_latencia.py                 # resume logs/latencia.csv
    python3 bin/banco_latencia.py --sintesis      # mide solo el motor de voz
    python3 bin/banco_latencia.py --csv otro.csv
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from emotibot import ajustes as mod_ajustes  # noqa: E402
from emotibot import metricas, registro  # noqa: E402
from emotibot import voz as mod_voz  # noqa: E402
from emotibot.audio import senal  # noqa: E402

FRASES_PRUEBA = (
    "Hola, soy Emoti Bot.",
    "Te escucho. Cuéntame qué pasó, en una o dos frases.",
    "Vamos a respirar juntos. Inhala por la nariz, contando cuatro.",
    "Lo dejamos ahí: ya tienes un primer paso concreto para mañana.",
)


def resumir_csv(ruta: Path | None) -> int:
    filas = metricas.leer_csv(ruta)
    if not filas:
        destino = ruta or Path("logs/latencia.csv")
        print(f"No hay mediciones en {destino}.")
        print("Usa EMOTI-BOT unas 20 veces y vuelve a ejecutar esto.")
        return 1
    print(metricas.resumir(filas))
    print()
    proveedores: dict[str, int] = {}
    for fila in filas:
        proveedores[fila.get("proveedor", "?")] = \
            proveedores.get(fila.get("proveedor", "?"), 0) + 1
    print("Turnos por proveedor:")
    for nombre, cuenta in sorted(proveedores.items(), key=lambda x: -x[1]):
        print(f"  {nombre or '(ninguno)':<12} {cuenta}")
    return 0


def medir_sintesis() -> int:
    registro.configurar(a_archivo=False)
    config = mod_ajustes.cargar()
    voz = mod_voz.crear(config)
    print(f"Motor de voz: {voz.nombre} ({voz.frecuencia} Hz)")
    print()
    print(f"{'frase':<10}{'1.ª frase':>12}{'total':>10}{'audio':>10}"
          f"{'factor':>9}")

    primeras: list[float] = []
    for indice, texto in enumerate(FRASES_PRUEBA, start=1):
        inicio = time.monotonic()
        primera = 0.0
        total_bytes = 0
        for trozo in voz.sintetizar(texto):
            if primera == 0.0:
                primera = time.monotonic() - inicio
            total_bytes += len(trozo)
        total = time.monotonic() - inicio
        duracion = senal.duracion_s(b"\0" * total_bytes, voz.frecuencia)
        factor = (duracion / total) if total > 0 else 0.0
        primeras.append(primera)
        print(f"{indice:<10}{primera:>11.2f}s{total:>9.2f}s"
              f"{duracion:>9.2f}s{factor:>8.1f}x")

    print()
    if primeras:
        print(f"Tiempo hasta la primera frase · mediana "
              f"{statistics.median(primeras):.2f} s")
    print("El 'factor' es cuántos segundos de audio produce por segundo de")
    print("cálculo. Por debajo de 1x el motor no sostiene una conversación.")
    voz.cerrar()
    return 0


def main() -> int:
    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument("--sintesis", action="store_true",
                            help="Mide el motor de voz en lugar de leer el CSV.")
    analizador.add_argument("--csv", default="",
                            help="Ruta alternativa del CSV de latencia.")
    argumentos = analizador.parse_args()

    if argumentos.sintesis:
        return medir_sintesis()
    return resumir_csv(Path(argumentos.csv) if argumentos.csv else None)


if __name__ == "__main__":
    sys.exit(main())
