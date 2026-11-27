#!/usr/bin/env python3
"""B5 — Longitud de las respuestas en uso real, por ruta y por proveedor.

No hace ninguna consulta: lee logs/latencia.csv, que desde la v1.8 guarda
por turno la ruta (conversacion/razonamiento), el número de palabras, el
motivo de fin y los tokens. Nunca el texto.

Para cada ruta y proveedor da:
- turnos y respuestas de longitud conocida;
- palabras: mediana y p90, y % por encima del objetivo de config/longitud.json;
- truncadas (cortadas por el tope) y recortadas a la última frase;
- duración hablada: medida (fin de habla − primer sonido) y estimada
  (palabras ÷ 2,5 por segundo).

Es la medición que precede a los valores definitivos (§13.8b). Lo que NO
mide es si la respuesta contestaba bien la pregunta: eso es la evaluación a
ciegas (B6).

Uso:
    .venv\\Scripts\\python.exe bin\\medir_longitud.py
    .venv\\Scripts\\python.exe bin\\medir_longitud.py --csv otra.csv
"""
from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))
try:  # consola de Windows en cp1252: que se vean tildes y símbolos
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

from emotibot import metricas  # noqa: E402
from emotibot.ia import longitud  # noqa: E402


def _num(valor) -> float | None:
    try:
        texto = str(valor).strip()
        return float(texto) if texto else None
    except (TypeError, ValueError):
        return None


def _p90(valores: list[float]) -> float:
    ordenados = sorted(valores)
    return ordenados[min(len(ordenados) - 1, round(0.9 * (len(ordenados) - 1)))]


def resumir(filas: list[dict], tabla: dict) -> list[dict]:
    grupos: dict[tuple[str, str], list[dict]] = {}
    for fila in filas:
        papel = (fila.get("papel") or "").strip()
        if not papel:
            continue                    # filas de la v1.7 o turnos locales
        grupos.setdefault((papel, fila.get("proveedor") or "?"), []).append(fila)

    salida = []
    for (papel, proveedor), lista in sorted(grupos.items()):
        palabras = [p for p in (_num(f.get("palabras_respuesta")) for f in lista)
                    if p]
        ruta = tabla.get(papel)
        objetivo = ruta.palabras_objetivo if ruta else None
        hablada = []
        for f in lista:
            total, primero = _num(f.get("t_total")), _num(f.get("t_primer_sonido"))
            if total and primero and total > primero:
                hablada.append(total - primero)
        salida.append({
            "papel": papel, "proveedor": proveedor, "turnos": len(lista),
            "con_longitud": len(palabras),
            "palabras_mediana": statistics.median(palabras) if palabras else None,
            "palabras_p90": _p90(palabras) if palabras else None,
            "objetivo": objetivo,
            "sobre_objetivo": (sum(p > objetivo for p in palabras) / len(palabras)
                               if palabras and objetivo else None),
            "truncadas": sum(f.get("motivo_fin") == "truncada" for f in lista),
            "recortadas": sum((f.get("recortada") or "") == "1" for f in lista),
            "hablada_mediana_s": statistics.median(hablada) if hablada else None,
            "estimada_mediana_s": (statistics.median(palabras)
                                   / longitud.PALABRAS_POR_SEGUNDO
                                   if palabras else None),
        })
    return salida


def _f(valor, formato="{:.0f}") -> str:
    return "—" if valor is None else formato.format(valor)


def main() -> int:
    analizador = argparse.ArgumentParser(description=__doc__,
                                         formatter_class=argparse.RawDescriptionHelpFormatter)
    analizador.add_argument("--csv", type=Path, default=None)
    argumentos = analizador.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    filas = metricas.leer_csv(argumentos.csv)
    resumen = resumir(filas, longitud.cargar())
    if not resumen:
        print("Todavía no hay turnos con ruta registrada (columna «papel»).")
        print("Se anotan desde la v1.8: usa el robot con conexión y vuelve.")
        return 1
    print(f"{'ruta':<13}{'proveedor':<14}{'turnos':>7}{'pal.med':>8}"
          f"{'p90':>5}{'obj':>5}{'>obj':>6}{'trunc':>6}{'recort':>7}"
          f"{'habla':>7}{'estim':>7}")
    for r in resumen:
        print(f"{r['papel']:<13}{r['proveedor']:<14}{r['turnos']:>7}"
              f"{_f(r['palabras_mediana']):>8}{_f(r['palabras_p90']):>5}"
              f"{_f(r['objetivo']):>5}{_f(r['sobre_objetivo'], '{:.0%}'):>6}"
              f"{r['truncadas']:>6}{r['recortadas']:>7}"
              f"{_f(r['hablada_mediana_s'], '{:.1f}s'):>7}"
              f"{_f(r['estimada_mediana_s'], '{:.1f}s'):>7}")
    print("\nhabla = duración medida (fin de habla − primer sonido); estim =")
    print("palabras ÷ 2,5/s. Los objetivos son PROVISIONALES (§13.8b).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
