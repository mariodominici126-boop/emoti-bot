#!/usr/bin/env python3
"""B6 — Evaluación a ciegas con varios evaluadores. Protocolo completo:
docs/fase1/B6_PROTOCOLO_EVALUACION.md

Tres pasos:

  generar   Pasa la batería fija (config/evaluacion_bateria.json) por el robot
            de verdad —gestor, enrutador, identidad, longitud y truncado— con
            una configuración con nombre. Gasta cuota real: una solicitud por
            turno (23 por configuración).
  preparar  Mezcla las respuestas de varias configuraciones, les pone
            identificadores neutrales y escribe una hoja por evaluador, cada
            una en un orden aleatorio distinto. La clave respuesta ↔
            configuración va en un archivo APARTE que no se entrega.
  resumir   Lee las hojas rellenas y la clave, y agrega. Avisa si hay menos
            de 3 evaluadores (D2) y rechaza hojas incompletas.

Reglas de cuota (§13.5) que el script hace cumplir:
- No genera con un proveedor que ese mismo día ya se usó para medir latencia
  (B4).
- Las solicitudes a OpenRouter cuentan para el tope de 16 de la Fase 1B. Si
  la generación lo superara, se niega, salvo que el responsable lo haya
  autorizado expresamente (--autorizacion "quién y cuándo"; queda anotado).

Uso:
    .venv\\Scripts\\python.exe bin\\evaluacion_ciegas.py generar --nombre v18 --orden conversacion,guion
    .venv\\Scripts\\python.exe bin\\evaluacion_ciegas.py generar --nombre gpt_oss --orden candidato_gpt_oss_20b,guion
    .venv\\Scripts\\python.exe bin\\evaluacion_ciegas.py preparar --configuraciones v18,otra --evaluadores 3
    .venv\\Scripts\\python.exe bin\\evaluacion_ciegas.py resumir
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))
try:  # consola de Windows en cp1252: que se vean tildes y símbolos
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

from emotibot import __version__, credenciales, registro, rutas  # noqa: E402
from emotibot import ajustes as mod_ajustes  # noqa: E402
from emotibot import evaluacion  # noqa: E402
from emotibot import identidad as mod_identidad  # noqa: E402

BATERIA = rutas.CONFIG_REPO / "evaluacion_bateria.json"
DIRECTORIO = rutas.LOGS / "evaluacion"
HOJAS = DIRECTORIO / "hojas"
CLAVE = DIRECTORIO / "clave_NO_ENTREGAR" / "clave.json"
REGISTRO_B4 = rutas.LOGS / "mediciones" / "b4_registro.json"
TOPE_OPENROUTER_FASE = 16


def _leer_registro() -> dict:
    try:
        return json.loads(REGISTRO_B4.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"franjas": {}, "total": {}}


def _anfitrion(url: str) -> str:
    return url.split("//", 1)[-1].split("/", 1)[0]


def generar(argumentos) -> int:
    from emotibot.dialogo import Gestor, Guardia
    from emotibot.ia import Orquestador

    config = mod_ajustes.cargar()
    orden = tuple(n.strip() for n in argumentos.orden.split(",") if n.strip())
    config = dataclasses.replace(
        config, ia=dataclasses.replace(config.ia, orden_proveedores=orden))
    identidad = mod_identidad.cargar()
    version, situaciones = evaluacion.cargar_bateria(BATERIA)
    llamadas_max = sum(len(s.turnos) for s in situaciones)

    orquestador = Orquestador(config, identidad, credenciales.cargar)
    archivo_longitud = ""
    if argumentos.longitud:
        # Longitud propia de ESTA configuración (p. ej. más tope para un modelo
        # de razonamiento). Solo afecta a la generación; el robot no cambia.
        from emotibot.ia import longitud as mod_longitud
        ruta_longitud = Path(argumentos.longitud)
        orquestador.longitudes = mod_longitud.cargar(ruta_longitud)
        if not orquestador.longitudes:
            print(f"No pude leer rutas de longitud en {ruta_longitud}.")
            return 1
        archivo_longitud = str(ruta_longitud)
    hosts = {n: _anfitrion(e.url) for n, e in orquestador.endpoints.items()
             if n in orden and e.configurado}

    registro_ = _leer_registro()
    hoy = time.strftime("%Y-%m-%d")
    medidos_hoy = {h for franja, cuenta in registro_["franjas"].items()
                   if franja.startswith(hoy) and not franja.startswith(hoy + "_b6")
                   for h in cuenta}
    choque = sorted(set(hosts.values()) & medidos_hoy)
    if choque:
        print(f"No genero: hoy ya se midió latencia en {', '.join(choque)} "
              "(§13.5: no el mismo día y proveedor). Vuelve mañana.")
        return 2
    if "openrouter.ai" in hosts.values():
        usadas = registro_["total"].get("openrouter.ai", 0)
        if usadas + llamadas_max > TOPE_OPENROUTER_FASE and not argumentos.autorizacion:
            print(f"No genero: OpenRouter lleva {usadas} solicitudes en la Fase 1B y "
                  f"esto puede sumar hasta {llamadas_max} (tope {TOPE_OPENROUTER_FASE}).")
            print("Pide autorización al responsable y repite con "
                  "--autorizacion \"quién y cuándo\".")
            return 2

    print(f"Configuración «{argumentos.nombre}»: orden {', '.join(orden)}. Hasta "
          f"{llamadas_max} solicitudes reales.")
    if not argumentos.si and input("¿Seguimos? [s/N] ").strip().lower() not in ("s", "si", "sí"):
        return 1

    gestor = Gestor(config, identidad, orquestador, Guardia())
    salida = {"configuracion": argumentos.nombre, "orden": list(orden),
              "fecha": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "version_emotibot": __version__, "version_bateria": version,
              "modelos": {n: orquestador.endpoints[n].modelo for n in hosts},
              "autorizacion": argumentos.autorizacion or "",
              "longitud": archivo_longitud or "config/longitud.json",
              "max_tokens_por_ruta": {n: r.max_tokens
                                      for n, r in orquestador.longitudes.items()},
              "situaciones": {}}
    franja = f"{hoy}_b6"
    for s in situaciones:
        gestor.limpiar_memoria()              # cada situación empieza de cero
        gestor.actividad = None
        dichas, quien = [], []
        for turno in s.turnos:
            resultado = gestor.procesar(turno)
            dichas.append(resultado.texto)
            quien.append(resultado.proveedor)
            host = hosts.get(resultado.proveedor)
            if host:                           # cuenta para los topes de la fase
                registro_["franjas"].setdefault(franja, {})
                registro_["franjas"][franja][host] = registro_["franjas"][franja].get(host, 0) + 1
                registro_["total"][host] = registro_["total"].get(host, 0) + 1
        salida["situaciones"][s.id] = {"tipo": s.tipo, "turnos": list(s.turnos),
                                       "respuestas": dichas, "proveedores": quien}
        print(f"  {s.id} ({s.tipo}): {', '.join(quien)}")
    rutas.asegurar_directorio(REGISTRO_B4.parent)
    REGISTRO_B4.write_text(json.dumps(registro_, indent=2), encoding="utf-8")
    rutas.asegurar_directorio(DIRECTORIO)
    destino = DIRECTORIO / f"respuestas_{argumentos.nombre}.json"
    destino.write_text(json.dumps(salida, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nRespuestas: {destino}")
    print("Revisa que no haya respuestas de «guion» donde esperabas un modelo:")
    print("eso significa que el proveedor no estaba disponible.")
    return 0


def preparar(argumentos) -> int:
    nombres = [n.strip() for n in argumentos.configuraciones.split(",") if n.strip()]
    if len(nombres) < 2:
        print("Hacen falta al menos dos configuraciones para comparar.")
        return 1
    if CLAVE.exists() and not argumentos.sobrescribir:
        print(f"Ya existe una clave en {CLAVE}. Si es una ronda nueva, guarda la "
              "anterior y usa --sobrescribir.")
        return 1
    respuestas = {}
    for nombre in nombres:
        ruta = DIRECTORIO / f"respuestas_{nombre}.json"
        if not ruta.is_file():
            print(f"Falta {ruta}: ejecuta antes «generar --nombre {nombre}».")
            return 1
        respuestas[nombre] = json.loads(ruta.read_text(encoding="utf-8"))
    hojas, clave = evaluacion.preparar(respuestas, argumentos.evaluadores)
    rutas.asegurar_directorio(HOJAS)
    rutas.asegurar_directorio(CLAVE.parent)
    for i, filas in enumerate(hojas, 1):
        evaluacion.escribir_hoja(HOJAS / f"evaluador_{i}.csv", filas)
    CLAVE.write_text(json.dumps({"fecha": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                 "configuraciones": nombres, "clave": clave},
                                indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{len(hojas)} hojas en {HOJAS} ({len(clave)} respuestas cada una).")
    print(f"Clave (NO entregar a los evaluadores): {CLAVE}")
    return 0


def resumir(argumentos) -> int:
    if not CLAVE.is_file():
        print(f"No encuentro la clave en {CLAVE}.")
        return 1
    clave = json.loads(CLAVE.read_text(encoding="utf-8"))["clave"]
    carpeta = Path(argumentos.hojas) if argumentos.hojas else HOJAS
    hojas, invalidas = {}, 0
    for ruta in sorted(carpeta.glob("*.csv")):
        filas = evaluacion.leer_hoja(ruta)
        problemas = evaluacion.validar_hoja(filas)
        if problemas:
            invalidas += 1
            print(f"✗ {ruta.name}: {len(problemas)} problemas; no se usa. Ejemplos:")
            for p in problemas[:5]:
                print(f"    {p}")
            continue
        hojas[ruta.stem] = filas
    if not hojas:
        print("Ninguna hoja válida todavía.")
        return 1
    r = evaluacion.resumir(hojas, clave)
    print(f"Evaluadores con hoja válida: {r['evaluadores']} (inválidas: {invalidas})")
    if not r["valido_segun_D2"]:
        print(f"AVISO: menos de {evaluacion.MINIMO_EVALUADORES} evaluadores. Según "
              "D2, este resultado NO es válido como evaluación.")
    if r["acuerdo_pm1"] is not None:
        print(f"Acuerdo entre evaluadores (diferencia ≤ 1 punto): {r['acuerdo_pm1']:.0%}")
    cabecera = "".join(f"{c[:11]:>12}" for c in evaluacion.CRITERIOS)
    print(f"\n{'configuración':<16}{cabecera}   errores/truncadas/identidad")
    for nombre, datos in sorted(r["configuraciones"].items()):
        medias = "".join(f"{datos['criterios'][c]['media']:>12.2f}"
                         for c in evaluacion.CRITERIOS)
        m = datos["marcas"]
        print(f"{nombre:<16}{medias}   {m['error_factual']}/{m['truncada']}/"
              f"{m['fallo_identidad']}")
    destino = DIRECTORIO / "resultados.json"
    destino.write_text(json.dumps(r, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nResultados: {destino}")
    return 0


def main() -> int:
    analizador = argparse.ArgumentParser(description=__doc__,
                                         formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = analizador.add_subparsers(dest="orden_cmd", required=True)
    g = sub.add_parser("generar")
    g.add_argument("--nombre", required=True)
    g.add_argument("--orden", default="conversacion,razonamiento,remoto,local,guion")
    g.add_argument("--autorizacion", default="")
    g.add_argument("--longitud", default="",
                   help="Archivo de longitud propio de esta configuración.")
    g.add_argument("--si", action="store_true")
    p = sub.add_parser("preparar")
    p.add_argument("--configuraciones", required=True)
    p.add_argument("--evaluadores", type=int, default=3)
    p.add_argument("--sobrescribir", action="store_true")
    r = sub.add_parser("resumir")
    r.add_argument("--hojas", default="")
    argumentos = analizador.parse_args()
    registro.configurar(a_archivo=False)
    logging.getLogger("emotibot").setLevel(logging.WARNING)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    return {"generar": generar, "preparar": preparar,
            "resumir": resumir}[argumentos.orden_cmd](argumentos)


if __name__ == "__main__":
    sys.exit(main())
