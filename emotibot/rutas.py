"""Rutas del proyecto y de los datos del usuario.

Separa tres cosas que antes estaban mezcladas en ~/Downloads:

- RAIZ      : el repositorio (código y configuración versionada).
- CONFIG_USUARIO : ajustes y credenciales de esta máquina (nunca al repositorio).
- ESTADO    : contadores y registros locales (nunca al repositorio).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
# Ejecutable de PyInstaller: RAIZ es su carpeta interna (`_internal`), que
# puede estar en Program Files y no admitir escritura.
CONGELADO = bool(getattr(sys, "frozen", False))
# Lo que viaja DENTRO del paquete (voz «claude», Whisper «small»): en el
# código fuente, `voces/` y `modelos/` del proyecto (ignoradas por git).
RECURSOS = RAIZ
CONFIG_REPO = RAIZ / "config"


def _base_config_usuario() -> Path:
    env = os.environ.get("EMOTI_CONFIG_DIR")
    if env:
        return Path(env).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg).expanduser() / "emotibot"
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "emotibot"
    return Path.home() / ".config" / "emotibot"


def _base_estado() -> Path:
    env = os.environ.get("EMOTI_STATE_DIR")
    if env:
        return Path(env).expanduser()
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return Path(xdg).expanduser() / "emotibot"
    if os.name == "nt":
        appdata = os.environ.get("LOCALAPPDATA")
        if appdata:
            return Path(appdata) / "emotibot"
    return Path.home() / ".local" / "state" / "emotibot"


CONFIG_USUARIO = _base_config_usuario()
ESTADO = _base_estado()
# Registros y mediciones. Desde el código fuente, logs/ del proyecto (los
# scripts de bin/ escriben ahí). En el ejecutable, la carpeta de estado de la
# máquina (%LOCALAPPDATA%\emotibot\logs en Windows): la del programa puede
# no ser escribible.
LOGS = ESTADO / "logs" if CONGELADO else RAIZ / "logs"
VOCES_USUARIO = CONFIG_USUARIO / "voces"     # voces bajadas a petición

ARCHIVO_CREDENCIALES = CONFIG_USUARIO / "credenciales.json"
ARCHIVO_PRESUPUESTO = ESTADO / "presupuesto.json"
ARCHIVO_LATENCIA = LOGS / "latencia.csv"
ARCHIVO_PROVEEDORES = CONFIG_REPO / "proveedores.json"


def asegurar_directorio(ruta: Path, privado: bool = False) -> Path:
    """Crea el directorio si falta. Con privado=True aplica permisos 0700 (POSIX)."""
    ruta.mkdir(parents=True, exist_ok=True)
    if privado and os.name != "nt":
        try:
            ruta.chmod(0o700)
        except OSError:
            pass
    return ruta
