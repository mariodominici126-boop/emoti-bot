"""Registro con redacción obligatoria de secretos.

Regla del proyecto: ninguna clave API puede aparecer en consola, en un archivo
de log ni en un mensaje de error mostrado al usuario.

Dos capas de defensa:

1. `proteger(secreto)` registra una cadena concreta para redactarla siempre.
2. Un patrón genérico tapa cualquier cosa con forma de clave de Google, por si
   un secreto llega sin haber sido registrado antes.

Además (v1.8) se ocultan los identificadores de cuenta y de usuario que
algunos proveedores devuelven en sus cuerpos de error.
"""
from __future__ import annotations

import logging
import re
import sys
from typing import Iterable

from . import rutas

MARCA = "[CLAVE OCULTA]"

# Claves de Google AI Studio empiezan por AIza; cubrimos también tokens largos.
_PATRONES_GENERICOS = (
    re.compile(r"AIza[0-9A-Za-z_\-]{10,}"),
    re.compile(r"\bsk-[0-9A-Za-z_\-]{16,}\b"),
)

MARCA_ID = "[ID OCULTO]"

# Identificadores de cuenta, usuario u organización que los proveedores meten
# en sus cuerpos de error (p. ej. «"user_id":"user_…"» de OpenRouter). No son
# secretos, pero identifican la cuenta del responsable y no deben aparecer en
# consola ni en el registro. Se oculta solo el VALOR: el resto del mensaje de
# error, que es lo útil para diagnosticar, se conserva.
_CAMPO_ID = re.compile(
    r"""(?P<campo>["']?\b(?:user|account|org|organization|project|customer|owner|team|workspace)[_\-]?id["']?\s*[:=]\s*["']?)"""
    r"""(?P<valor>[A-Za-z0-9_\-\.:@]{4,})""",
    re.IGNORECASE,
)
# Identificadores con prefijo de tipo sueltos en el texto (user_…, org_…).
_ID_SUELTO = re.compile(r"\b(?:user|org|acct|account|team)_[A-Za-z0-9]{12,}\b")

_secretos: set[str] = set()


def proteger(*secretos: str) -> None:
    """Registra secretos para que nunca se impriman en claro."""
    for secreto in secretos:
        if secreto and len(secreto) >= 8:
            _secretos.add(secreto)


def olvidar_secretos() -> None:
    _secretos.clear()


def redactar(texto: object) -> str:
    """Devuelve el texto con todos los secretos conocidos sustituidos."""
    salida = str(texto)
    for secreto in _secretos:
        if secreto in salida:
            salida = salida.replace(secreto, MARCA)
    for patron in _PATRONES_GENERICOS:
        salida = patron.sub(MARCA, salida)
    salida = _CAMPO_ID.sub(lambda m: m.group("campo") + MARCA_ID, salida)
    salida = _ID_SUELTO.sub(MARCA_ID, salida)
    return salida


class _FiltroRedaccion(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            mensaje = record.getMessage()
        except Exception:
            return True
        limpio = redactar(mensaje)
        if limpio != mensaje:
            record.msg = limpio
            record.args = ()
        return True


_configurado = False


def configurar(nivel: int = logging.INFO, a_archivo: bool = True) -> None:
    global _configurado
    if _configurado:
        return
    _configurado = True

    formato = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)-22s %(message)s", "%H:%M:%S"
    )
    filtro = _FiltroRedaccion()

    raiz = logging.getLogger("emotibot")
    raiz.setLevel(nivel)
    raiz.propagate = False

    consola = logging.StreamHandler(sys.stderr)
    consola.setFormatter(formato)
    consola.addFilter(filtro)
    raiz.addHandler(consola)

    if a_archivo:
        try:
            rutas.asegurar_directorio(rutas.LOGS)
            archivo = logging.FileHandler(
                rutas.LOGS / "emotibot.log", encoding="utf-8"
            )
            archivo.setFormatter(formato)
            archivo.addFilter(filtro)
            raiz.addHandler(archivo)
        except OSError:
            raiz.warning("No se pudo abrir el archivo de registro; sigo solo en consola.")


def obtener(nombre: str) -> logging.Logger:
    configurar()
    return logging.getLogger(f"emotibot.{nombre}")


def resumen_excepcion(exc: BaseException, limite: int = 220) -> str:
    """Texto corto y redactado de una excepción, apto para la interfaz."""
    return f"{type(exc).__name__}: {redactar(exc)[:limite]}"


def unir(partes: Iterable[str]) -> str:
    return " ".join(p for p in partes if p)
