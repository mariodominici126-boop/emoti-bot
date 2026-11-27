#!/usr/bin/env python3
"""Diagnóstico del proveedor remoto, aislado del micrófono y de la interfaz.

Sirve para lo que ahora mismo bloquea el proyecto: saber EXACTAMENTE qué
límite se agotó. Imprime el cuerpo completo del error, que es donde el
proveedor nombra la métrica y su valor, y el dato que nunca se capturó.

Hace una sola consulta de texto por modelo. No reintenta nunca ante un 429.
No envía audio: una consulta de texto cuesta una fracción de lo que cuesta
una de audio, y para diagnosticar basta.

Uso:
    python3 bin/diagnostico_ia.py
    python3 bin/diagnostico_ia.py --modelos gemini-3.5-flash-lite,gemini-3.8-flash
    python3 bin/diagnostico_ia.py --sin-consulta     # solo revisa el entorno
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))
try:  # consola o tubería de Windows en cp1252: que no se caiga con «→»
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

from emotibot import ajustes as mod_ajustes  # noqa: E402
from emotibot import credenciales, identidad as mod_identidad, registro, rutas  # noqa: E402
from emotibot.agentes_opcionales import importar_opcional  # noqa: E402
from emotibot.ia import presupuesto as mod_presupuesto  # noqa: E402
from emotibot.ia.base import Clase, ErrorProveedor, Peticion  # noqa: E402
from emotibot.ia.gemini import ProveedorGemini  # noqa: E402
from emotibot.ia.openai_compat import (  # noqa: E402
    ProveedorOpenAI, cargar_endpoints)

PREGUNTA = "Responde solo con la palabra: listo"


def titulo(texto: str) -> None:
    print()
    print(texto)
    print("-" * len(texto))


def explicar(exc: ErrorProveedor) -> None:
    """Qué significa la clase del fallo, para no confundir unas con otras."""
    if exc.clase is Clase.BLOQUEO_CLIENTE:
        print("     → Bloqueo del CLIENTE en el borde del servicio (p. ej.")
        print("       Cloudflare, código 1010): la petición no llegó a la API y")
        print("       la clave NO se comprobó. No regeneres la clave.")
    elif exc.clase is Clase.AUTENTICACION:
        print("     → La API del proveedor rechazó la clave (respuesta JSON).")
    elif exc.clase is Clase.MODELO:
        print("     → La API dice que el modelo no existe o no está disponible")
        print("       para esta cuenta. Lee el mensaje: suele proponer otro.")


def revisar_entorno(config) -> bool:
    titulo("Entorno")
    sdk = importar_opcional("google.genai") or importar_opcional("google_genai")
    print(f"  google-genai instalado:  {'sí' if sdk else 'NO'}")
    if not sdk:
        print("    instala con: python -m pip install -U google-genai")
    claves = {n: credenciales.cargar(n)
              for n in ("groq", "openrouter", "gemini")}
    for nombre, valor in claves.items():
        print(f"  clave {nombre:<18} {credenciales.huella(valor)}")
    print(f"  archivo de credenciales: {rutas.ARCHIVO_CREDENCIALES}")
    print(f"  modelo configurado:      {config.ia.modelo_remoto}")
    print(f"  timeout:                 {config.ia.timeout_remoto_ms} ms")
    print(f"  presupuesto propio:      {config.ia.presupuesto_diario}/día, "
          f"{config.ia.presupuesto_por_minuto}/min")
    return bool(sdk and any(claves.values()))


def probar_modelo(config, identidad, clave: str, modelo: str) -> None:
    print(f"\n  → {modelo}")
    ajuste_ia = mod_ajustes.AjustesIa(
        **{**{campo: getattr(config.ia, campo)
              for campo in config.ia.__dataclass_fields__},
           "modelo_remoto": modelo}
    )
    # Presupuesto en archivo aparte: el diagnóstico no consume el del robot.
    presupuesto = mod_presupuesto.Presupuesto(
        maximo_diario=50, maximo_por_minuto=5,
        ruta=rutas.ESTADO / "presupuesto_diagnostico.json",
    )
    # El contrato es obtener_clave(nombre_del_proveedor) -> clave, el mismo
    # que usa la aplicación. Antes se pasaba una función sin argumentos y el
    # diagnóstico de Gemini acababa en TypeError.
    proveedor = ProveedorGemini(ajuste_ia, presupuesto, lambda _nombre: clave)
    peticion = Peticion(texto=PREGUNTA,
                        instrucciones=identidad.instrucciones())
    try:
        respuesta = proveedor.responder(peticion)
    except ErrorProveedor as exc:
        print(f"     resultado: FALLO ({exc.clase.value})")
        print(f"     mensaje al usuario: {exc.mensaje_usuario()}")
        print("     cuerpo completo del error:")
        for linea in (exc.detalle or "sin detalle").split(" | "):
            print(f"       {linea}")
        explicar(exc)
        if exc.clase is Clase.CUOTA:
            print()
            print("     ESTE es el texto que hacía falta. Guárdalo.")
            print("     Mira también la cuota viva de tu proyecto en:")
            print("       https://aistudio.google.com/rate-limit")
            print("     No se reintenta: un 429 es un techo, no un fallo")
            print("     pasajero.")
        return
    print(f"     resultado: OK en {respuesta.segundos:.2f} s")
    print(f"     texto: {respuesta.texto[:120]!r}")


def probar_endpoints(config, identidad) -> None:
    """Prueba los proveedores compatibles con OpenAI de proveedores.json."""
    titulo("Proveedores compatibles con OpenAI")
    endpoints = cargar_endpoints(rutas.ARCHIVO_PROVEEDORES)
    if not endpoints:
        print("  Ninguno definido en config/proveedores.json.")
        return

    presupuesto = mod_presupuesto.Presupuesto(
        maximo_diario=50, maximo_por_minuto=5,
        ruta=rutas.ESTADO / "presupuesto_diagnostico.json",
    )
    peticion = Peticion(texto=PREGUNTA,
                        instrucciones=identidad.instrucciones())

    for nombre, endpoint in endpoints.items():
        print(f"\n  → {nombre}: {endpoint.descripcion}")
        if not endpoint.configurado:
            print("     SIN CONFIGURAR: falta url o modelo.")
            print("     Edita config/proveedores.json.")
            continue
        print(f"     url    {endpoint.url}")
        print(f"     modelo {endpoint.modelo}")
        clave = credenciales.cargar(endpoint.clave) if endpoint.clave else ""
        if endpoint.necesita_clave:
            print(f"     clave  {endpoint.clave}: "
                  f"{credenciales.huella(clave)}")
            if not clave:
                print("     Sin clave: pulsa K en EMOTI-BOT o exporta "
                      f"EMOTI_CLAVE_{endpoint.clave.upper()}")
                continue

        proveedor = ProveedorOpenAI(
            endpoint, presupuesto, lambda n: credenciales.cargar(n),
            config.ia.timeout_remoto_ms,
        )
        try:
            respuesta = proveedor.responder(peticion)
        except ErrorProveedor as exc:
            print(f"     resultado: FALLO ({exc.clase.value})")
            print(f"     {exc.detalle[:400]}")
            explicar(exc)
            continue
        print(f"     resultado: OK en {respuesta.segundos:.2f} s")
        print(f"     texto: {respuesta.texto[:120]!r}")


def main() -> int:
    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument("--modelos", default="",
                            help="Lista separada por comas. Por defecto, el "
                                 "configurado y su alterno.")
    analizador.add_argument("--sin-consulta", action="store_true",
                            help="Solo revisa el entorno; no gasta cuota.")
    argumentos = analizador.parse_args()

    registro.configurar(a_archivo=False)
    config = mod_ajustes.cargar()
    identidad = mod_identidad.cargar()

    print("EMOTI-BOT · diagnóstico de inteligencia")
    listo = revisar_entorno(config)
    if not argumentos.sin_consulta:
        probar_endpoints(config, identidad)

    if argumentos.sin_consulta:
        return 0
    if not listo:
        print("\nFalta el SDK o la clave: no hago consultas remotas.")
        return 1

    if argumentos.modelos:
        modelos = [m.strip() for m in argumentos.modelos.split(",") if m.strip()]
    else:
        modelos = [config.ia.modelo_remoto]
        if config.ia.modelo_remoto_alterno:
            modelos.append(config.ia.modelo_remoto_alterno)

    titulo("Consultas remotas (una por modelo, sin reintentos)")
    clave = credenciales.cargar("gemini")
    for modelo in modelos:
        probar_modelo(config, identidad, clave, modelo)

    print()
    print("Recordatorio: los límites del nivel gratuito son por PROYECTO y por")
    print("modelo, y no se publican en una tabla fija. La cifra que vale es la")
    print("que muestra tu propia consola.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
