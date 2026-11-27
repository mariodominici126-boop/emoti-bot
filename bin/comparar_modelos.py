#!/usr/bin/env python3
"""Compara los modelos configurados con una batería fija en español.

Elegir modelo por lo que dice su ficha técnica es adivinar. Esto los pone a
los dos delante de las mismas preguntas —charla, malestar emocional,
razonamiento e identidad— y mide lo que de verdad importa en un robot que
habla: cuánto tarda y cuánto se enrolla. La calidad la juzgas tú leyendo las
respuestas, que es lo único que no se puede automatizar.

Consume cuota real: una consulta por pregunta y proveedor. Con `--rapido` usa
solo una pregunta de cada tipo.

Uso:
    python bin/comparar_modelos.py
    python bin/comparar_modelos.py --rapido
    python bin/comparar_modelos.py --proveedores conversacion,razonamiento
"""
from __future__ import annotations

import argparse
import logging
import statistics
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from emotibot import ajustes as mod_ajustes  # noqa: E402
from emotibot import credenciales, identidad as mod_identidad  # noqa: E402
from emotibot import registro, rutas  # noqa: E402
from emotibot.ia import enrutador  # noqa: E402
from emotibot.ia.base import ErrorProveedor, Peticion  # noqa: E402
from emotibot.ia.openai_compat import ProveedorOpenAI, cargar_endpoints  # noqa: E402
from emotibot.ia.presupuesto import Presupuesto  # noqa: E402
from emotibot.texto import palabras  # noqa: E402

BATERIA: tuple[tuple[str, str], ...] = (
    ("charla", "Hola, ¿qué tal estás?"),
    ("charla", "Cuéntame algo curioso, lo que quieras."),
    ("identidad", "¿Quién eres y para qué sirves?"),
    ("emocional", "Hoy me fue fatal y estoy agotado."),
    ("emocional", "Me siento solo últimamente."),
    ("razonamiento", "¿Por qué el cielo se ve azul?"),
    ("razonamiento", "Tengo que entregar un proyecto el viernes y me falta "
                     "la mitad. ¿Por dónde empiezo?"),
)

# Un robot que habla no puede soltar párrafos: a 2,5 palabras por segundo,
# 60 palabras son casi medio minuto hablando. Fase 1, B5: la cifra sale de
# config/longitud.json, por ruta, igual que el tope que se pide al modelo.
from emotibot.ia import longitud  # noqa: E402

_LONGITUDES = longitud.cargar()


def objetivo(papel: str) -> int:
    ruta = _LONGITUDES.get(papel)
    return ruta.palabras_objetivo if ruta else 45


PALABRAS_OBJETIVO = objetivo(enrutador.CONVERSACION)


def titulo(texto: str) -> None:
    print()
    print(texto)
    print("=" * len(texto))


def preparar(config, endpoints, nombres):
    presupuesto = Presupuesto(
        maximo_diario=200, maximo_por_minuto=10,
        ruta=rutas.ESTADO / "presupuesto_comparacion.json",
    )
    proveedores = {}
    for nombre in nombres:
        endpoint = endpoints.get(nombre)
        if endpoint is None:
            print(f"  (no existe el proveedor «{nombre}»)")
            continue
        if not endpoint.configurado:
            print(f"  {nombre}: sin configurar, falta url o modelo.")
            continue
        if endpoint.necesita_clave and not credenciales.cargar(endpoint.clave):
            print(f"  {nombre}: sin clave de «{endpoint.clave}».")
            continue
        proveedores[nombre] = ProveedorOpenAI(
            endpoint, presupuesto, credenciales.cargar,
            config.ia.timeout_remoto_ms,
        )
    return proveedores


def main() -> int:
    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument("--rapido", action="store_true",
                            help="Una pregunta por tipo en lugar de todas.")
    analizador.add_argument("--proveedores", default="",
                            help="Lista separada por comas.")
    argumentos = analizador.parse_args()

    registro.configurar(a_archivo=False)
    logging.getLogger("emotibot").setLevel(logging.ERROR)
    config = mod_ajustes.cargar()
    identidad = mod_identidad.cargar()
    endpoints = cargar_endpoints(rutas.ARCHIVO_PROVEEDORES)

    nombres = ([n.strip() for n in argumentos.proveedores.split(",") if n.strip()]
               or [n for n in endpoints if n != "local"])

    titulo("Proveedores")
    proveedores = preparar(config, endpoints, nombres)
    for nombre, proveedor in proveedores.items():
        print(f"  {nombre:14} {proveedor.modelo}")
    if not proveedores:
        print("\nNingún proveedor listo. Revisa config/proveedores.json y las claves.")
        return 1

    preguntas = list(BATERIA)
    if argumentos.rapido:
        vistos, filtradas = set(), []
        for tipo, texto in preguntas:
            if tipo not in vistos:
                vistos.add(tipo)
                filtradas.append((tipo, texto))
        preguntas = filtradas

    tiempos: dict[str, list[float]] = {n: [] for n in proveedores}
    longitudes: dict[str, list[int]] = {n: [] for n in proveedores}

    for tipo, texto in preguntas:
        titulo(f"[{tipo}] {texto}")
        papel = enrutador.papel(texto)
        print(f"  el enrutador mandaría esto a: {papel}")
        ruta = _LONGITUDES.get(papel)
        # Mismo tope que en producción: el de la ruta, no el del proveedor.
        peticion = Peticion(texto=texto,
                            instrucciones=identidad.instrucciones(),
                            max_tokens=ruta.max_tokens if ruta else None)
        for nombre, proveedor in proveedores.items():
            inicio = time.monotonic()
            try:
                respuesta = proveedor.responder(peticion)
            except ErrorProveedor as exc:
                print(f"\n  ── {nombre}: FALLO ({exc.clase.value})")
                print(f"     {exc.detalle[:220]}")
                continue
            segundos = time.monotonic() - inicio
            n_palabras = palabras(respuesta.texto)
            tiempos[nombre].append(segundos)
            longitudes[nombre].append(n_palabras)
            marca = "  (largo)" if n_palabras > objetivo(papel) else ""
            if respuesta.truncada:
                marca += "  (TRUNCADA)"
            print(f"\n  ── {nombre}  {segundos:.2f}s · "
                  f"{n_palabras} palabras{marca}")
            for linea in _envolver(respuesta.texto, 72):
                print(f"     {linea}")

    titulo("Resumen")
    print(f"{'proveedor':<16}{'mediana':>9}{'p90':>8}{'palabras':>11}{'fallos':>8}")
    for nombre in proveedores:
        t = tiempos[nombre]
        l = longitudes[nombre]
        fallos = len(preguntas) - len(t)
        if not t:
            print(f"{nombre:<16}{'—':>9}{'—':>8}{'—':>11}{fallos:>8}")
            continue
        p90 = sorted(t)[min(len(t) - 1, int(0.9 * (len(t) - 1)))]
        print(f"{nombre:<16}{statistics.median(t):>8.2f}s{p90:>7.2f}s"
              f"{statistics.median(l):>11.0f}{fallos:>8}")
    print()
    print("Objetivo de longitud (config/longitud.json, provisional): "
          f"conversación {objetivo(enrutador.CONVERSACION)} palabras, "
          f"razonamiento {objetivo(enrutador.RAZONAMIENTO)}. Por encima, el")
    print("robot está dando discursos en vez de conversando.")
    print("La calidad júzgala leyendo las respuestas; eso no lo mide un script.")
    return 0


def _envolver(texto: str, ancho: int) -> list[str]:
    lineas, actual = [], ""
    for palabra in str(texto).split():
        if len(actual) + len(palabra) + 1 > ancho:
            lineas.append(actual)
            actual = palabra
        else:
            actual = f"{actual} {palabra}".strip()
    if actual:
        lineas.append(actual)
    return lineas or [""]


if __name__ == "__main__":
    sys.exit(main())
