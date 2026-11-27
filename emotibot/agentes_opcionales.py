"""Importación de dependencias opcionales sin romper el arranque.

El robot tiene que poder arrancar con lo mínimo instalado. Cada pieza
opcional (Piper, faster-whisper, google-genai) se importa aquí, con el fallo
registrado una sola vez y en lenguaje claro, en lugar de propagar un
ImportError a media conversación.
"""
from __future__ import annotations

import importlib
from types import ModuleType

from . import registro

log = registro.obtener("opcionales")

_fallos_avisados: set[str] = set()


def importar_opcional(nombre: str) -> ModuleType | None:
    try:
        return importlib.import_module(nombre)
    except ImportError as exc:
        if nombre not in _fallos_avisados:
            _fallos_avisados.add(nombre)
            log.info("Dependencia opcional ausente: %s (%s)", nombre, exc)
        return None
    except Exception as exc:  # un paquete puede fallar al inicializarse
        if nombre not in _fallos_avisados:
            _fallos_avisados.add(nombre)
            log.warning("La dependencia %s no se pudo cargar: %s", nombre, exc)
        return None


def disponible(nombre: str) -> bool:
    return importar_opcional(nombre) is not None
