"""C4 — Prueba de legibilidad de expresiones: preparación y análisis.

Lógica pura y comprobable. La generación de láminas y la página de la prueba
están en `bin/legibilidad_rostro.py`.

Diseño de la prueba:
- 14 láminas sin etiqueta: 7 expresiones × 2 diseños (A producción, B
  prototipo), con códigos neutrales (L-3F9A…) que no delatan ni el diseño
  ni la expresión.
- Cada participante las ve en un orden aleatorio propio y elige una de las
  opciones fijas, o «no sé».
- La clave código ↔ (diseño, expresión) va en un archivo aparte.
- Se analiza por diseño y expresión: acierto, intervalo de confianza y
  confusiones, frente a un umbral fijado ANTES de ver resultados (§13.8c).

Limitación declarada: cada persona ve los dos diseños, así que puede
aprender de uno al otro. El orden aleatorio reparte ese efecto entre los dos
diseños, pero no lo elimina.
"""
from __future__ import annotations

import csv
import json
import secrets
from pathlib import Path

from emotibot.medicion import intervalo_wilson

OPCIONES = ("en reposo", "escuchando", "pensando", "hablando", "feliz",
            "curioso", "preocupado", "no sé")
# Nombre interno de la expresión → la opción que la describe.
RESPUESTA_CORRECTA = {
    "reposo": "en reposo", "escuchando": "escuchando", "pensando": "pensando",
    "hablando": "hablando", "feliz": "feliz", "curioso": "curioso",
    "preocupado": "preocupado",
}


def codigos(expresiones, disenos=("A", "B")) -> dict[str, dict]:
    """{código neutral: {"diseno", "expresion"}}."""
    usados, clave = set(), {}
    for diseno in disenos:
        for expresion in expresiones:
            while True:
                codigo = "L-" + secrets.token_hex(2).upper()
                if codigo not in usados:
                    usados.add(codigo)
                    break
            clave[codigo] = {"diseno": diseno, "expresion": expresion}
    return clave


def umbral_valido(ruta_umbral: Path, hojas: list[Path]) -> tuple[bool, str]:
    """El umbral no puede haberse tocado después de la primera hoja."""
    if not ruta_umbral.is_file():
        return False, "No existe el archivo de umbral."
    if not hojas:
        return True, ""
    primera = min(h.stat().st_mtime for h in hojas)
    if ruta_umbral.stat().st_mtime > primera:
        return False, ("El umbral se modificó DESPUÉS de la primera hoja de "
                       "respuestas. §13.8c exige fijarlo antes de ver resultados.")
    return True, ""


def leer_respuestas(rutas_csv: list[Path]) -> list[dict]:
    filas = []
    for ruta in rutas_csv:
        with ruta.open(newline="", encoding="utf-8-sig") as origen:
            for fila in csv.DictReader(origen):
                filas.append({"participante": fila["participante"].strip(),
                              "lamina": fila["lamina"].strip(),
                              "respuesta": fila["respuesta"].strip().lower()})
    return filas


def analizar(filas: list[dict], clave: dict, umbral: dict) -> dict:
    participantes = sorted({f["participante"] for f in filas})
    datos: dict[str, dict[str, dict]] = {}
    for fila in filas:
        destino = clave.get(fila["lamina"])
        if destino is None:
            continue
        celda = datos.setdefault(destino["diseno"], {}).setdefault(
            destino["expresion"], {"n": 0, "aciertos": 0, "respuestas": {}})
        celda["n"] += 1
        correcta = RESPUESTA_CORRECTA[destino["expresion"]]
        celda["aciertos"] += fila["respuesta"] == correcta
        celda["respuestas"][fila["respuesta"]] = \
            celda["respuestas"].get(fila["respuesta"], 0) + 1

    minimo = float(umbral["acierto_minimo_por_expresion"])
    confusion_max = float(umbral["confusion_maxima_con_otra"])
    suficientes = len(participantes) >= int(umbral["participantes_minimos"])
    resultado = {"participantes": len(participantes), "suficientes": suficientes,
                 "umbral_provisional": bool(umbral.get("provisional")),
                 "disenos": {}}
    for diseno, expresiones in sorted(datos.items()):
        detalle, todas = {}, True
        for expresion, celda in expresiones.items():
            correcta = RESPUESTA_CORRECTA[expresion]
            acierto = celda["aciertos"] / celda["n"]
            otras = {r: c for r, c in celda["respuestas"].items()
                     if r not in (correcta, "no sé")}
            peor = max(otras.items(), key=lambda x: x[1]) if otras else (None, 0)
            pasa = acierto >= minimo and peor[1] / celda["n"] <= confusion_max
            todas &= pasa
            bajo, alto = intervalo_wilson(celda["aciertos"], celda["n"])
            detalle[expresion] = {
                "n": celda["n"], "acierto": acierto, "ic95": [bajo, alto],
                "confusion_principal": peor[0],
                "confusion_principal_pct": peor[1] / celda["n"],
                "respuestas": celda["respuestas"], "pasa": pasa,
            }
        resultado["disenos"][diseno] = {"expresiones": detalle,
                                        "pasan_todas": todas}
    return resultado


def guardar_json(ruta: Path, datos) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")
