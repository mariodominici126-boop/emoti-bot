"""Evaluación a ciegas con varios evaluadores (Fase 1, B6, decisión D2).

Lógica pura, comprobable sin red: preparar las hojas anónimas y agregar las
puntuaciones. La generación de respuestas y la interacción están en
`bin/evaluacion_ciegas.py`. El protocolo completo está en
`docs/fase1/B6_PROTOCOLO_EVALUACION.md`.

Garantías del diseño:
- Cada respuesta lleva un identificador neutral y aleatorio (R-7F3A…) que no
  deja deducir la configuración ni el orden de generación.
- Cada evaluador recibe las respuestas en un orden distinto y aleatorio.
- El vínculo respuesta ↔ configuración va en un archivo aparte (la clave),
  que no se entrega a los evaluadores.
- Ninguna función inventa puntuaciones: `resumir` solo agrega lo que los
  evaluadores escribieron, y rechaza hojas incompletas o fuera de rango.
"""
from __future__ import annotations

import csv
import json
import random
import secrets
import statistics
from dataclasses import dataclass
from pathlib import Path

CRITERIOS = ("comprension", "utilidad", "coherencia", "naturalidad", "adecuacion")
MARCAS = ("error_factual", "truncada", "fallo_identidad")
COLUMNAS_HOJA = ("orden", "id", "tipo", "contexto", "pregunta", "respuesta",
                 *CRITERIOS, *MARCAS, "comentario")
MINIMO_EVALUADORES = 3


@dataclass(frozen=True)
class Situacion:
    id: str
    tipo: str
    turnos: tuple[str, ...]


def cargar_bateria(ruta: Path) -> tuple[int, list[Situacion]]:
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    situaciones = [Situacion(s["id"], s["tipo"], tuple(s["turnos"]))
                   for s in datos["situaciones"]]
    ids = [s.id for s in situaciones]
    if len(ids) != len(set(ids)):
        raise ValueError("La batería tiene identificadores repetidos.")
    return int(datos.get("version", 1)), situaciones


def _identificador(usados: set[str]) -> str:
    while True:
        candidato = "R-" + secrets.token_hex(3).upper()
        if candidato not in usados:
            usados.add(candidato)
            return candidato


def preparar(respuestas: dict[str, dict], evaluadores: int,
             semilla: int | None = None) -> tuple[list[list[dict]], dict]:
    """Hojas anónimas, una por evaluador, y la clave aparte.

    `respuestas` = {configuracion: {"situaciones": {id: {"tipo", "turnos",
    "respuestas"}}}}, donde "respuestas" es la lista de lo que el robot
    contestó a cada turno. Se evalúa la última; las anteriores son contexto.
    """
    if evaluadores < 1:
        raise ValueError("Hace falta al menos un evaluador.")
    configuraciones = sorted(respuestas)
    comunes = set.intersection(*(set(respuestas[c]["situaciones"])
                                 for c in configuraciones))
    usados: set[str] = set()
    elementos, clave = [], {}
    for configuracion in configuraciones:
        for sid in sorted(comunes):
            s = respuestas[configuracion]["situaciones"][sid]
            turnos, dichas = s["turnos"], s["respuestas"]
            contexto = " | ".join(
                f"Persona: {t} → Robot: {r}" for t, r in zip(turnos[:-1], dichas[:-1]))
            identificador = _identificador(usados)
            clave[identificador] = {"configuracion": configuracion, "situacion": sid}
            elementos.append({"id": identificador, "tipo": s["tipo"],
                              "contexto": contexto, "pregunta": turnos[-1],
                              "respuesta": dichas[-1]})
    azar = random.Random(semilla if semilla is not None else secrets.randbits(64))
    hojas = []
    for _ in range(evaluadores):
        orden = elementos[:]
        azar.shuffle(orden)
        hojas.append([{**e, "orden": i + 1, **{c: "" for c in CRITERIOS},
                       **{m: "" for m in MARCAS}, "comentario": ""}
                      for i, e in enumerate(orden)])
    return hojas, clave


def escribir_hoja(ruta: Path, filas: list[dict]) -> None:
    # utf-8-sig: que Excel en Windows muestre bien las tildes.
    with ruta.open("w", newline="", encoding="utf-8-sig") as destino:
        escritor = csv.DictWriter(destino, fieldnames=list(COLUMNAS_HOJA),
                                  extrasaction="ignore")
        escritor.writeheader()
        escritor.writerows(filas)


def leer_hoja(ruta: Path) -> list[dict]:
    with ruta.open(newline="", encoding="utf-8-sig") as origen:
        texto = origen.read()
    dialecto = csv.Sniffer().sniff(texto.splitlines()[0], delimiters=",;\t")
    return list(csv.DictReader(texto.splitlines(), dialect=dialecto))


def validar_hoja(filas: list[dict]) -> list[str]:
    """Problemas que impiden usar una hoja. Lista vacía = válida."""
    problemas = []
    for fila in filas:
        for criterio in CRITERIOS:
            valor = (fila.get(criterio) or "").strip()
            if valor not in ("1", "2", "3", "4", "5"):
                problemas.append(f"{fila.get('id')}: «{criterio}» = «{valor}» "
                                 "(debe ser 1-5)")
        for marca in MARCAS:
            valor = (fila.get(marca) or "").strip().lower()
            if valor not in ("", "0", "1", "x", "si", "sí", "no"):
                problemas.append(f"{fila.get('id')}: «{marca}» = «{valor}»")
    return problemas


def _marcada(valor: str) -> bool:
    return (valor or "").strip().lower() in ("1", "x", "si", "sí")


def resumir(hojas: dict[str, list[dict]], clave: dict) -> dict:
    """Agrega por configuración. `hojas` = {evaluador: filas}."""
    puntuaciones: dict[str, dict[str, list[int]]] = {}
    marcas: dict[str, dict[str, int]] = {}
    por_elemento: dict[str, dict[str, list[int]]] = {}
    desconocidos = set()
    for evaluador, filas in hojas.items():
        for fila in filas:
            identificador = fila.get("id", "")
            if identificador not in clave:
                desconocidos.add(identificador)
                continue
            configuracion = clave[identificador]["configuracion"]
            destino = puntuaciones.setdefault(configuracion, {c: [] for c in CRITERIOS})
            for criterio in CRITERIOS:
                valor = int(fila[criterio])
                destino[criterio].append(valor)
                por_elemento.setdefault(identificador, {}).setdefault(criterio, []).append(valor)
            cuenta = marcas.setdefault(configuracion, {m: 0 for m in MARCAS})
            for marca in MARCAS:
                cuenta[marca] += _marcada(fila.get(marca, ""))

    # Acuerdo entre evaluadores: proporción de pares que difieren en ≤ 1 punto.
    pares = acuerdos = 0
    for criterios in por_elemento.values():
        for valores in criterios.values():
            for i in range(len(valores)):
                for j in range(i + 1, len(valores)):
                    pares += 1
                    acuerdos += abs(valores[i] - valores[j]) <= 1
    resultado = {
        "evaluadores": len(hojas),
        "valido_segun_D2": len(hojas) >= MINIMO_EVALUADORES,
        "acuerdo_pm1": acuerdos / pares if pares else None,
        "ids_desconocidos": sorted(desconocidos),
        "configuraciones": {},
    }
    for configuracion, criterios in puntuaciones.items():
        resultado["configuraciones"][configuracion] = {
            "criterios": {c: {"media": statistics.mean(v), "n": len(v),
                              "desv": statistics.pstdev(v)}
                          for c, v in criterios.items() if v},
            "marcas": marcas[configuracion],
        }
    return resultado
