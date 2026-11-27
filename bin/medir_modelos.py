#!/usr/bin/env python3
"""B4 — Medición real de los modelos desde este equipo, con topes de cuota.

Mide, por solicitud y con streaming AISLADO en este script (la aplicación
sigue sin streaming):

- t_conexion: hasta recibir las cabeceras HTTP;
- TTFT: hasta el primer fragmento de texto;
- t_total: hasta el último byte;
- tokens de entrada y salida (del `usage` final del stream) y velocidad
  efectiva = tokens de salida ÷ (t_total − TTFT);
- motivo de fin (truncadas), errores y rechazos por clase.

Topes de §13.5, comprobados ANTES de enviar y guardados entre ejecuciones
en logs/mediciones/b4_registro.json:
- OpenRouter / DeepSeek: 8 solicitudes por franja y 16 en toda la Fase 1B.
- Groq / Qwen: 20 por franja.
Si una ejecución los superara, el script se niega a empezar.

Cada solicitud también pasa por el presupuesto del robot (reservar y
confirmar), así que la medición gasta de la misma cuenta que el uso real, y
el robot lo sabe.

Franjas: mide al menos dos (por ejemplo, la tarde y la noche, o a la hora en
que se presentará el proyecto). La franja por defecto es la fecha y la hora
actuales («2026-11-21_21h»).

El tiempo hasta el primer sonido y el tiempo total de una intervención NO se
pueden medir aquí: dependen de la voz y del altavoz. Se toman del uso real,
en logs/latencia.csv, y este script los resume por modelo al final.

Las preguntas son fijas, inocuas y no personales. No se guarda el texto de
las respuestas: solo cifras.

Uso:
    .venv\\Scripts\\python.exe bin\\medir_modelos.py --conexion "wifi 5 GHz"
    .venv\\Scripts\\python.exe bin\\medir_modelos.py --plan conversacion=10,candidato_gpt_oss_20b=10
    .venv\\Scripts\\python.exe bin\\medir_modelos.py --plan candidato_gpt_oss_20b@razonamiento=4 --max-tokens 400

Por defecto (22-11-2026, ruta de OpenRouter desactivada) compara Qwen
(«conversacion») con GPT-OSS 20B («candidato_gpt_oss_20b»), cada uno con
preguntas de conversación y de razonamiento («nombre@razonamiento»), y toma
4 muestras del respaldo Gemini («remoto»). Con --max-tokens se sube el tope
SOLO en esta medición, para ver cuántos tokens de razonamiento gasta GPT-OSS
sin cortarse (§14.3); el robot no cambia.
    .venv\\Scripts\\python.exe bin\\medir_modelos.py --resumen
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import platform
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))
try:  # consola de Windows en cp1252: que se vean tildes y símbolos
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

from emotibot import __version__, credenciales, metricas, registro, rutas  # noqa: E402
from emotibot import ajustes as mod_ajustes  # noqa: E402
from emotibot import identidad as mod_identidad  # noqa: E402
from emotibot.ia import longitud, tokens  # noqa: E402
from emotibot.ia.base import clasificar_http, normalizar_motivo_fin  # noqa: E402
from emotibot.ia.openai_compat import (Endpoint, cabeceras_peticion,  # noqa: E402
                                       cargar_endpoints, cuerpo_peticion)
from emotibot.ia.presupuesto import Presupuesto  # noqa: E402

# Topes de §13.5 por anfitrión del proveedor.
HOST_GEMINI = "generativelanguage.googleapis.com"
TOPES = {
    "openrouter.ai": {"por_franja": 8, "total": 16},
    "api.groq.com": {"por_franja": 20, "total": None},
    # Muestra pequeña del respaldo Gemini (decisión del 22-11): 4 por franja.
    HOST_GEMINI: {"por_franja": 4, "total": None},
}
PREGUNTAS = {
    "conversacion": (
        "Hola, ¿qué tal?",
        "Cuéntame algo curioso sobre los pulpos.",
        "Hoy hace un día bonito, ¿no crees?",
        "¿Qué me recomiendas para desayunar?",
        "Me gusta mucho la música, ¿y a ti?",
    ),
    "razonamiento": (
        "¿Por qué el cielo se ve azul?",
        "Explícame la diferencia entre el tiempo y el clima.",
        "Tengo que entregar un trabajo el viernes y me falta la mitad. ¿Por dónde empiezo?",
        "¿Cuál es mejor para ir al trabajo, la bici o el autobús? Dame pros y contras.",
    ),
}
DIRECTORIO = rutas.LOGS / "mediciones"
REGISTRO = DIRECTORIO / "b4_registro.json"
COLUMNAS = ("franja", "marca_tiempo", "papel", "proveedor", "modelo", "pregunta",
            "max_tokens", "estado", "http", "t_conexion", "t_primer_fragmento",
            "ttft", "t_total", "tokens_entrada", "tokens_salida",
            "tokens_razonamiento", "tokens_cache", "tokens_s", "motivo_fin")
# Plan por defecto (22-11-2026, opción d: ruta de razonamiento de OpenRouter
# desactivada). Qwen contra GPT-OSS, cada uno con preguntas de conversación
# y de razonamiento, porque ahora el modelo de conversación atiende las dos
# rutas (con 320 tokens la de razonamiento). 7 + 3 + 7 + 3 = 20, el tope de
# Groq por franja. Más 4 del respaldo Gemini («remoto»), que no gasta cuota
# de Groq ni de OpenRouter.
# «nombre@ruta=N» mide el proveedor «nombre» con las preguntas y el tope de
# «ruta».
PLAN_POR_DEFECTO = ("conversacion=7,conversacion@razonamiento=3,"
                    "candidato_gpt_oss_20b=7,candidato_gpt_oss_20b@razonamiento=3,"
                    "remoto=4")
GEMINI = "remoto"


def separar(clave_plan: str) -> tuple[str, str]:
    """«conversacion@razonamiento» → ("conversacion", "razonamiento")."""
    nombre, _, ruta = clave_plan.partition("@")
    return nombre.strip(), ruta.strip()


def endpoint_gemini(config) -> Endpoint:
    """Gemini no es compatible con OpenAI: este Endpoint solo lo describe para
    el plan, los topes y el informe. Se consulta con ProveedorGemini, igual
    que el robot."""
    return Endpoint(nombre=GEMINI, url=f"https://{HOST_GEMINI}",
                    modelo=config.ia.modelo_remoto, clave="gemini",
                    papel="conversacion", max_tokens=config.ia.max_tokens_respuesta)


def medir_gemini(config, presupuesto, instrucciones: str, pregunta: str,
                 max_tokens: int) -> dict:
    """Una consulta al respaldo Gemini por el MISMO camino que el robot.

    Sin streaming, así que no hay TTFT: se mide el tiempo total, incluida la
    primera creación del cliente, que es lo que nota la persona. El
    presupuesto (reserva y conciliación) lo lleva el propio proveedor, y el
    timeout es el de producción: un tiempo agotado es un dato, no un fallo
    del instrumento.
    """
    from emotibot.ia.base import ErrorProveedor, Peticion
    from emotibot.ia.gemini import ProveedorGemini
    proveedor = ProveedorGemini(config.ia, presupuesto, credenciales.cargar)
    r = {"estado": "ok", "http": "", "t_conexion": None, "t_primer_fragmento": None,
         "ttft": None, "t_total": None, "tokens_entrada": None, "tokens_salida": None,
         "tokens_razonamiento": None, "tokens_cache": None, "motivo_fin": ""}
    inicio = time.monotonic()
    try:
        respuesta = proveedor.responder(Peticion(
            texto=pregunta, instrucciones=instrucciones, max_tokens=max_tokens))
        r.update(tokens_entrada=respuesta.tokens_entrada,
                 tokens_salida=respuesta.tokens_salida,
                 motivo_fin=respuesta.motivo_fin)
    except ErrorProveedor as exc:
        r["estado"] = exc.clase.value
    r["t_total"] = time.monotonic() - inicio
    return r


# Por debajo de esta ventana, la velocidad no se puede medir: el servicio
# entrega la salida en pocos fragmentos y dividir por unos milisegundos da
# cifras absurdas (se llegaron a ver 44.557 tok/s).
VENTANA_MINIMA_S = 0.25


def velocidad_generacion(r: dict) -> float | None:
    """Tokens de salida ÷ tiempo de generación, o None si no es medible.

    La generación empieza con el PRIMER fragmento de cualquier tipo, no con
    el primer texto: en un modelo de razonamiento (GPT-OSS), los tokens de
    razonamiento llegan antes del TTFT y forman parte de la salida contada.
    Dividirlos solo por el tramo posterior al TTFT inflaba la cifra.
    """
    def numero(clave):
        try:
            valor = r.get(clave)
            return float(valor) if valor not in (None, "") else None
        except (TypeError, ValueError):
            return None

    salida, total = numero("tokens_salida"), numero("t_total")
    inicio = numero("t_primer_fragmento") or numero("ttft")
    if not salida or total is None or inicio is None:
        return None
    ventana = total - inicio
    if ventana < VENTANA_MINIMA_S:
        return None
    return salida / ventana


def escribir_fila(escritor, salida, franja: str, papel: str, proveedor: str,
                  modelo: str, pregunta: int, max_tokens: int, r: dict) -> dict:
    """Anota una medición (solo cifras) y la muestra en pantalla."""
    velocidad = velocidad_generacion(r)
    fila = {"franja": franja, "marca_tiempo": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "papel": papel, "proveedor": proveedor, "modelo": modelo,
            "pregunta": pregunta, "max_tokens": max_tokens,
            **{k: (round(v, 3) if isinstance(v, float) else ("" if v is None else v))
               for k, v in r.items()},
            "tokens_s": "" if velocidad is None else round(velocidad, 1)}
    escritor.writerow(fila)
    salida.flush()
    print(f"  {papel:<34} {r['estado']:<6} TTFT {fila['ttft'] or '—'} s · "
          f"total {fila['t_total']} s · {fila['tokens_salida'] or '?'} tok · "
          f"{r['motivo_fin'] or '?'}")
    return fila


# Segundos entre dos solicitudes seguidas. Con los modelos ALTERNADOS, cada
# modelo recibe una solicitud cada 10-15 s, por debajo de lo que cabe en el
# tope propio de 7.000 tokens/min. Así B4 mide el servicio y no nuestro
# propio tope (diagnóstico del 22-11). El presupuesto no se toca.
# Se propuso 3,5 s, pero las instrucciones crecieron el 22-11 (+531
# caracteres, unos 150 tokens reales más por turno). Con ese consumo, 3,5 s
# dejan 2 rechazos; 4 s, ninguno; 5 s, ninguno aunque la salida crezca
# otros 100 tokens. Se fija 5 s: la franja tarda unos 2 minutos.
ESPACIO_S = 5.0


def orden_alternado(plan: dict[str, int]) -> list[tuple[str, int]]:
    """Orden de envío: alterna MODELOS y reparte las rutas dentro de cada uno.

    Devuelve [(entrada_del_plan, índice), …]. Ejemplo con el plan por
    defecto: Qwen, GPT-OSS, Gemini, Qwen, GPT-OSS, Gemini… y, dentro de
    Qwen, las 3 de razonamiento repartidas entre las 7 de conversación en
    vez de amontonadas al final.
    """
    por_modelo: dict[str, list[tuple[str, int]]] = {}
    for clave, n in plan.items():
        if n > 0:
            por_modelo.setdefault(separar(clave)[0], []).append((clave, n))
    colas: dict[str, list[tuple[str, int]]] = {}
    for modelo, entradas in por_modelo.items():
        total = sum(n for _, n in entradas)
        # Reparto proporcional: cada entrada ocupa posiciones equiespaciadas.
        puestos = []
        for clave, n in entradas:
            for i in range(n):
                puestos.append(((i + 0.5) / n, clave, i))
        puestos.sort()
        colas[modelo] = [(clave, i) for _, clave, i in puestos][:total]
    orden: list[tuple[str, int]] = []
    while any(colas.values()):
        for modelo in list(colas):
            if colas[modelo]:
                orden.append(colas[modelo].pop(0))
    return orden


def leer_plan(texto: str) -> dict[str, int]:
    """«nombre=N,nombre=N» → {nombre: N}. Los nombres son los de proveedores.json."""
    plan: dict[str, int] = {}
    for parte in texto.split(","):
        if not parte.strip():
            continue
        nombre, _, numero = parte.partition("=")
        plan[nombre.strip()] = max(0, int(numero or 0))
    return plan


def anfitrion(url: str) -> str:
    return url.split("//", 1)[-1].split("/", 1)[0]


def leer_registro() -> dict:
    try:
        return json.loads(REGISTRO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"franjas": {}, "total": {}}


def guardar_registro(datos: dict) -> None:
    rutas.asegurar_directorio(DIRECTORIO)
    REGISTRO.write_text(json.dumps(datos, indent=2), encoding="utf-8")


def comprobar_topes(plan: dict[str, int], hosts: dict[str, str], franja: str,
                    registro_: dict) -> list[str]:
    """Devuelve los motivos por los que el plan superaría algún tope.

    Los topes son por ANFITRIÓN: Qwen y GPT-OSS van los dos a Groq, así que
    sus solicitudes se suman antes de comparar con el tope.
    """
    por_host: dict[str, int] = {}
    for nombre, n in plan.items():
        if n > 0 and nombre in hosts:
            por_host[hosts[nombre]] = por_host.get(hosts[nombre], 0) + n
    problemas = []
    for host, n in por_host.items():
        tope = TOPES.get(host)
        if not tope:
            continue
        hechas = registro_["franjas"].get(franja, {}).get(host, 0)
        if hechas + n > tope["por_franja"]:
            problemas.append(f"{host}: {hechas} ya hechas en la franja {franja} "
                             f"+ {n} > {tope['por_franja']} por franja")
        if tope["total"] is not None:
            total = registro_["total"].get(host, 0)
            if total + n > tope["total"]:
                problemas.append(f"{host}: {total} en la Fase 1B + {n} > "
                                 f"{tope['total']} en total")
    return problemas


def anotar_registro(registro_: dict, franja: str, host: str) -> None:
    registro_["franjas"].setdefault(franja, {})
    registro_["franjas"][franja][host] = registro_["franjas"][franja].get(host, 0) + 1
    registro_["total"][host] = registro_["total"].get(host, 0) + 1
    guardar_registro(registro_)


def leer_uso(fragmento: dict, r: dict) -> None:
    """Consumo del fragmento final del stream.

    Según el servicio llega en `usage` o, en Groq, en `x_groq.usage`. Los
    tokens de razonamiento (§14.3) y los aciertos de caché vienen en los
    detalles, si el servicio los da.
    """
    uso = fragmento.get("usage")
    if not isinstance(uso, dict):
        uso = (fragmento.get("x_groq") or {}).get("usage")
    if not isinstance(uso, dict):
        return
    r["tokens_entrada"] = uso.get("prompt_tokens", r["tokens_entrada"])
    r["tokens_salida"] = uso.get("completion_tokens", r["tokens_salida"])
    detalles_salida = uso.get("completion_tokens_details") or {}
    detalles_entrada = uso.get("prompt_tokens_details") or {}
    if isinstance(detalles_salida, dict) and "reasoning_tokens" in detalles_salida:
        r["tokens_razonamiento"] = detalles_salida["reasoning_tokens"]
    if isinstance(detalles_entrada, dict) and "cached_tokens" in detalles_entrada:
        r["tokens_cache"] = detalles_entrada["cached_tokens"]


def medir_una(endpoint, clave: str, mensajes: list[dict], max_tokens: int,
              timeout_s: float) -> dict:
    # El mismo cuerpo que enviaría el robot (incluidos los parámetros propios
    # del modelo, como el esfuerzo de razonamiento), pero en streaming.
    datos = cuerpo_peticion(endpoint, mensajes, max_tokens, stream=True)
    datos["stream_options"] = {"include_usage": True}
    cuerpo = json.dumps(datos).encode("utf-8")
    # Las mismas cabeceras que el robot, User-Agent propio incluido: sin él,
    # Cloudflare responde 403/1010 a Groq y se mediría un bloqueo.
    cabeceras = cabeceras_peticion(endpoint, clave)
    solicitud = urllib.request.Request(endpoint.url.rstrip("/") + "/chat/completions",
                                       data=cuerpo, headers=cabeceras, method="POST")
    r = {"estado": "ok", "http": 200, "t_conexion": None,
         "t_primer_fragmento": None, "ttft": None, "t_total": None,
         "tokens_entrada": None, "tokens_salida": None,
         "tokens_razonamiento": None, "tokens_cache": None, "motivo_fin": ""}
    inicio = time.monotonic()
    try:
        with urllib.request.urlopen(solicitud, timeout=timeout_s) as respuesta:
            r["t_conexion"] = time.monotonic() - inicio
            for linea in respuesta:
                linea = linea.decode("utf-8", "replace").strip()
                if not linea.startswith("data:"):
                    continue
                dato = linea[5:].strip()
                if dato == "[DONE]":
                    break
                try:
                    fragmento = json.loads(dato)
                except ValueError:
                    continue
                for eleccion in fragmento.get("choices") or []:
                    delta = eleccion.get("delta") or {}
                    # Un modelo de razonamiento emite primero lo que piensa
                    # (campo «reasoning») y luego el texto: se miden los dos.
                    if (delta.get("content") or delta.get("reasoning")
                            or delta.get("reasoning_content")) \
                            and r["t_primer_fragmento"] is None:
                        r["t_primer_fragmento"] = time.monotonic() - inicio
                    if delta.get("content") and r["ttft"] is None:
                        r["ttft"] = time.monotonic() - inicio
                    if eleccion.get("finish_reason"):
                        r["motivo_fin"] = normalizar_motivo_fin(eleccion["finish_reason"])
                leer_uso(fragmento, r)
        r["t_total"] = time.monotonic() - inicio
    except urllib.error.HTTPError as exc:
        try:
            cuerpo_error = exc.read().decode("utf-8", "replace")
        except Exception:
            cuerpo_error = ""
        # Misma clasificación que el robot: un 403 sin JSON de la API es un
        # bloqueo del cliente, no una clave mala.
        r.update(estado=clasificar_http(exc.code, cuerpo_error).value,
                 http=exc.code, t_total=time.monotonic() - inicio)
    except (TimeoutError, urllib.error.URLError, OSError) as exc:
        r.update(estado="tiempo" if "timed out" in str(exc).lower() else "red",
                 http="", t_total=time.monotonic() - inicio)
    return r


def resumen_filas(filas: list[dict]) -> str:
    lineas = []
    grupos: dict[tuple[str, str], list[dict]] = {}
    for f in filas:
        # Un mismo modelo con preguntas de conversación y de razonamiento son
        # dos grupos: los topes (120 / 320) y las latencias difieren.
        ruta = separar(f.get("papel", ""))[1]
        etiqueta = f"{f['modelo']} [{ruta}]" if ruta else f["modelo"]
        grupos.setdefault((f["franja"], etiqueta), []).append(f)

    def med(valores):
        valores = [float(v) for v in valores if str(v).strip() not in ("", "None")]
        if not valores:
            return "—"
        p90 = sorted(valores)[min(len(valores) - 1, round(0.9 * (len(valores) - 1)))]
        return f"{statistics.median(valores):.2f}/{p90:.2f}"

    lineas.append(f"{'franja':<16}{'modelo':<40}{'n':>3}{'ok':>4}"
                  f"{'conexión':>12}{'TTFT':>12}{'total':>12}{'tok/s':>12}"
                  f"{'salida':>12}{'razón.':>12}{'caché':>8}{'trunc':>6}")
    for (franja, modelo), lista in sorted(grupos.items()):
        ok = [f for f in lista if f["estado"] == "ok"]
        lineas.append(
            f"{franja:<16}{modelo[:39]:<40}{len(lista):>3}{len(ok):>4}"
            f"{med(f['t_conexion'] for f in ok):>12}{med(f['ttft'] for f in ok):>12}"
            # tok/s se recalcula desde los datos en bruto: así tampoco se
            # muestran las cifras imposibles guardadas antes del arreglo.
            f"{med(f['t_total'] for f in ok):>12}"
            f"{med(velocidad_generacion(f) for f in ok):>12}"
            f"{med(f.get('tokens_salida', '') for f in ok):>12}"
            f"{med(f.get('tokens_razonamiento', '') for f in ok):>12}"
            f"{sum(int(float(f.get('tokens_cache') or 0)) for f in ok):>8}"
            f"{sum(f['motivo_fin'] == 'truncada' for f in ok):>6}")
        errores = {}
        for f in lista:
            if f["estado"] != "ok":
                errores[f["estado"]] = errores.get(f["estado"], 0) + 1
        if errores:
            lineas.append("    errores: " + ", ".join(f"{k}={v}" for k, v in errores.items()))
    lineas.append("Tiempos en segundos y tokens: mediana/p90. «razón.» = tokens de "
                  "razonamiento (incluidos en salida); «caché» = tokens de entrada "
                  "servidos desde caché, en total.")
    lineas.append(f"«tok/s» solo se calcula si la generación dura ≥ "
                  f"{VENTANA_MINIMA_S} s desde el primer fragmento; si no, «—»: "
                  "es demasiado rápida para medirla así.")
    return "\n".join(lineas)


def resumen_uso_real() -> str:
    filas = [f for f in metricas.leer_csv() if (f.get("t_primer_sonido") or "0") not in ("", "0", "0.0")]
    if not filas:
        return "Uso real (latencia.csv): sin turnos con primer sonido medido."
    grupos: dict[str, list[dict]] = {}
    for f in filas:
        grupos.setdefault(f.get("modelo") or f.get("proveedor") or "?", []).append(f)
    lineas = ["Uso real (logs/latencia.csv), mediana — tiempo desde que dejas de "
              "hablar:"]
    for modelo, lista in sorted(grupos.items()):
        def m(col):
            v = [float(f[col]) for f in lista if (f.get(col) or "").strip()]
            return f"{statistics.median(v):.2f}s" if v else "—"
        lineas.append(f"  {modelo:<40} n={len(lista):<3} IA {m('t_ia')} · "
                      f"primer sonido {m('t_primer_sonido')} · total {m('t_total')}")
    lineas.append("  Ojo: las filas antiguas con t_ia ~0,71 s son de Gemini (n=8), "
                  "no de Qwen ni de DeepSeek.")
    return "\n".join(lineas)


def main() -> int:
    analizador = argparse.ArgumentParser(description=__doc__,
                                         formatter_class=argparse.RawDescriptionHelpFormatter)
    analizador.add_argument("--franja", default=time.strftime("%Y-%m-%d_%Hh"))
    analizador.add_argument("--conexion", default="",
                            help="Tipo de conexión (wifi, ethernet, 4G…).")
    analizador.add_argument("--plan", default=PLAN_POR_DEFECTO,
                            help="nombre=N separados por comas (nombres de "
                                 "config/proveedores.json).")
    analizador.add_argument("--max-tokens", type=int, default=0,
                            help="Tope de salida SOLO para esta medición.")
    analizador.add_argument("--espacio", type=float, default=ESPACIO_S,
                            help="Segundos entre dos solicitudes seguidas.")
    analizador.add_argument("--si", action="store_true",
                            help="No pedir confirmación antes de enviar.")
    analizador.add_argument("--resumen", action="store_true",
                            help="Solo resume lo ya medido.")
    argumentos = analizador.parse_args()
    registro.configurar(a_archivo=False)
    logging.getLogger("emotibot").setLevel(logging.WARNING)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    destino = DIRECTORIO / "b4_modelos.csv"
    if argumentos.resumen:
        filas = metricas.leer_csv(destino)
        print(resumen_filas(filas) if filas else "Sin mediciones B4.")
        print()
        print(resumen_uso_real())
        return 0

    config = mod_ajustes.cargar()
    identidad = mod_identidad.cargar()
    endpoints = cargar_endpoints(rutas.ARCHIVO_PROVEEDORES)
    longitudes = longitud.cargar()
    plan = leer_plan(argumentos.plan)
    endpoints[GEMINI] = endpoint_gemini(config)
    hosts, claves = {}, {}
    for papel in list(plan):
        endpoint = endpoints.get(separar(papel)[0])
        if endpoint is None or not endpoint.configurado:
            print(f"{papel}: sin configurar o desactivado; no se mide.")
            plan[papel] = 0
            continue
        clave = credenciales.cargar(endpoint.clave)
        if not clave:
            print(f"{papel}: sin clave de «{endpoint.clave}»; no se mide.")
            plan[papel] = 0
            continue
        registro.proteger(clave)
        hosts[papel], claves[papel] = anfitrion(endpoint.url), clave

    registro_ = leer_registro()
    problemas = comprobar_topes(plan, hosts, argumentos.franja, registro_)
    if problemas:
        print("No empiezo: el plan supera los topes de §13.5.")
        for p in problemas:
            print("  · " + p)
        print("Si de verdad hace falta más, pide autorización al responsable.")
        return 2
    if not any(plan.values()):
        print("Nada que medir.")
        return 1

    print(f"Franja {argumentos.franja}. Se enviarán:")
    for papel, n in plan.items():
        if n:
            print(f"  {n} × {papel} ({endpoints[separar(papel)[0]].modelo}, {hosts[papel]})")
    if not argumentos.si and input("¿Seguimos? [s/N] ").strip().lower() not in ("s", "si", "sí"):
        return 1

    presupuesto = Presupuesto(config.ia.presupuesto_diario,
                              config.ia.presupuesto_por_minuto)
    for papel in plan:
        e = endpoints.get(separar(papel)[0])
        if e and separar(papel)[0] != GEMINI:
            presupuesto.fijar_limites(e.modelo, e.max_dia, e.max_minuto,
                                      e.max_tokens_dia, e.max_tokens_minuto)
    meta = {"franja": argumentos.franja, "fecha": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "version_emotibot": __version__, "python": sys.executable,
            "sistema": f"{platform.system()} {platform.release()} {platform.machine()}",
            "conexion": argumentos.conexion, "plan": plan,
            "max_tokens_forzado": argumentos.max_tokens or None}
    rutas.asegurar_directorio(DIRECTORIO)
    nuevo = not destino.exists()
    with destino.open("a", newline="", encoding="utf-8") as salida:
        escritor = csv.DictWriter(salida, fieldnames=list(COLUMNAS))
        if nuevo:
            escritor.writeheader()
        # Configuración de cada entrada del plan: misma ruta, mismas
        # preguntas y mismo tope que tendría en producción.
        tareas_por_entrada = {}
        for papel, n in plan.items():
            if not n:
                continue
            nombre, ruta_pedida = separar(papel)
            endpoint = endpoints[nombre]
            ruta_nombre = ruta_pedida or endpoint.papel or nombre
            ruta = longitudes.get(ruta_nombre)
            tareas_por_entrada[papel] = {
                "nombre": nombre, "endpoint": endpoint,
                "preguntas": PREGUNTAS.get(ruta_nombre, PREGUNTAS["conversacion"]),
                "max_tokens": (argumentos.max_tokens
                               or (ruta.max_tokens if ruta else endpoint.max_tokens)),
            }
        parados: set[str] = set()      # modelos detenidos por 429 o presupuesto
        orden = orden_alternado(plan)
        for posicion, (papel, i) in enumerate(orden):
            t = tareas_por_entrada[papel]
            nombre, endpoint, max_tokens = t["nombre"], t["endpoint"], t["max_tokens"]
            if nombre in parados:
                continue
            if posicion:
                time.sleep(argumentos.espacio)   # ritmo sostenido, sin ráfagas
            pregunta = t["preguntas"][i % len(t["preguntas"])]
            numero = i % len(t["preguntas"]) + 1
            if nombre == GEMINI:
                anotar_registro(registro_, argumentos.franja, hosts[papel])
                r = medir_gemini(config, presupuesto, identidad.instrucciones(),
                                 pregunta, max_tokens)
                escribir_fila(escritor, salida, argumentos.franja, papel, hosts[papel],
                              endpoint.modelo, numero, max_tokens, r)
                if r["estado"] == "cuota":
                    print("  429: paro este modelo. No se reintenta.")
                    parados.add(nombre)
                continue
            mensajes = [{"role": "system", "content": identidad.instrucciones()},
                        {"role": "user", "content": pregunta}]
            entrada = tokens.estimar_entrada(m["content"] for m in mensajes)
            reserva, motivo = presupuesto.reservar(endpoint.modelo,
                                                   entrada + max_tokens, entrada)
            if reserva is None:
                print(f"  {papel}: el presupuesto del robot dice que no ({motivo}). "
                      "Paro este modelo.")
                parados.add(nombre)
                continue
            anotar_registro(registro_, argumentos.franja, hosts[papel])
            r = medir_una(endpoint, claves[papel], mensajes, max_tokens,
                          config.ia.timeout_remoto_ms / 1000.0 + 20)
            if r["estado"] == "ok":
                presupuesto.confirmar(reserva, r["tokens_entrada"], r["tokens_salida"])
            else:
                if r["estado"] == "cuota":
                    presupuesto.registrar_rechazo_cuota(endpoint.modelo)
                presupuesto.anular(reserva, 0 if r["estado"] in
                                   ("cuota", "autenticacion", "peticion", "modelo",
                                    "red", "bloqueo_cliente")
                                   else reserva.tokens)
            escribir_fila(escritor, salida, argumentos.franja, papel, hosts[papel],
                          endpoint.modelo, numero, max_tokens, r)
            if r["estado"] == "cuota":
                print("  429: paro este modelo. No se reintenta.")
                parados.add(nombre)
    (DIRECTORIO / f"b4_meta_{argumentos.franja}.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print()
    print(resumen_filas(metricas.leer_csv(destino)))
    print()
    print(resumen_uso_real())
    print(f"\nRegistro de solicitudes de la Fase 1B: {REGISTRO}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
