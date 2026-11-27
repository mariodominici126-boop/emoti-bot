"""Almacenamiento de la clave API fuera del repositorio.

Problema que resuelve: en las versiones 0.5–0.6.2 la clave vivía en una
variable de terminal (se perdía al reiniciar) o solo en memoria (había que
reescribirla en cada arranque).

Decisiones de seguridad:

- Hay una clave por proveedor (gemini, qwen, deepseek…), guardadas juntas en
  ~/.config/emotibot/credenciales.json, NUNCA en el repositorio. El directorio queda en 0700 y el archivo en 0600 (POSIX).
- Se escribe con archivo temporal + reemplazo atómico, con los permisos
  aplicados ANTES de escribir el contenido.
- En Windows no existe chmod equivalente: se avisa una vez, porque el archivo
  queda protegido solo por los permisos de la cuenta de usuario.
- Nada de esto se registra en los logs: la clave pasa por registro.proteger()
  en cuanto se carga, de modo que cualquier traza posterior la enmascara.
- `guardar=False` permite usarla solo en memoria para esta ejecución.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from . import registro, rutas

log = registro.obtener("credenciales")

PROVEEDOR_POR_DEFECTO = "gemini"

# Variables de entorno reconocidas para cada proveedor, además de la genérica
# EMOTI_CLAVE_<NOMBRE> que vale para cualquiera.
_VARIABLES_ENTORNO = {
    "gemini": ("EMOTI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "groq": ("GROQ_API_KEY",),
    "openrouter": ("OPENROUTER_API_KEY", "OPENROUTER_KEY"),
    "qwen": ("QWEN_API_KEY", "DASHSCOPE_API_KEY"),
    "deepseek": ("DEEPSEEK_API_KEY",),
}
_aviso_windows_dado = False


def _avisar_windows() -> None:
    global _aviso_windows_dado
    if os.name == "nt" and not _aviso_windows_dado:
        _aviso_windows_dado = True
        log.warning(
            "En Windows el archivo de credenciales queda protegido solo por los "
            "permisos de tu cuenta de usuario."
        )


def desde_entorno(proveedor: str = PROVEEDOR_POR_DEFECTO) -> str:
    candidatas = (f"EMOTI_CLAVE_{proveedor.upper()}",) + \
        _VARIABLES_ENTORNO.get(proveedor, ())
    for nombre in candidatas:
        valor = os.environ.get(nombre, "").strip()
        if valor:
            registro.proteger(valor)
            log.info("Clave de %s tomada de la variable %s.", proveedor, nombre)
            return valor
    return ""


def _leer_archivo() -> dict:
    ruta = rutas.ARCHIVO_CREDENCIALES
    if not ruta.is_file():
        return {}
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("No pude leer las credenciales guardadas: %s", exc)
        return {}
    return datos if isinstance(datos, dict) else {}


def leer(proveedor: str = PROVEEDOR_POR_DEFECTO) -> str:
    """Clave guardada en esta máquina para ese proveedor."""
    datos = _leer_archivo()
    claves = datos.get("claves")
    if isinstance(claves, dict):
        clave = str(claves.get(proveedor, "")).strip()
    else:
        # Formato antiguo: una sola clave suelta, que era la de Gemini.
        clave = (str(datos.get("api_key", "")).strip()
                 if proveedor == PROVEEDOR_POR_DEFECTO else "")
    if clave:
        registro.proteger(clave)
        _avisar_windows()
    return clave


def cargar(proveedor: str = PROVEEDOR_POR_DEFECTO) -> str:
    """Entorno primero (útil en pruebas), luego el archivo del usuario."""
    return desde_entorno(proveedor) or leer(proveedor)


def configurados() -> list[str]:
    """Proveedores que ya tienen clave guardada en esta máquina."""
    claves = _leer_archivo().get("claves")
    if isinstance(claves, dict):
        return sorted(n for n, v in claves.items() if str(v).strip())
    return [PROVEEDOR_POR_DEFECTO] if _leer_archivo().get("api_key") else []


def guardar(clave: str, proveedor: str = PROVEEDOR_POR_DEFECTO) -> bool:
    clave = (clave or "").strip()
    if not clave:
        return False
    registro.proteger(clave)
    # Se conservan las claves de los demás proveedores.
    datos = _leer_archivo()
    claves = datos.get("claves")
    if not isinstance(claves, dict):
        claves = {}
        antigua = str(datos.get("api_key", "")).strip()
        if antigua:
            claves[PROVEEDOR_POR_DEFECTO] = antigua
    claves[proveedor] = clave
    directorio = rutas.asegurar_directorio(rutas.CONFIG_USUARIO, privado=True)
    ruta = rutas.ARCHIVO_CREDENCIALES
    temporal: str | None = None
    try:
        descriptor, temporal = tempfile.mkstemp(
            prefix=".credenciales-", suffix=".tmp", dir=str(directorio)
        )
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as destino:
            json.dump({"claves": claves}, destino)
        os.replace(temporal, ruta)
        temporal = None
        if os.name != "nt":
            try:
                Path(ruta).chmod(0o600)
            except OSError:
                pass
        _avisar_windows()
        log.info("Clave de %s guardada en %s (permisos restringidos).",
                 proveedor, ruta)
        return True
    except OSError as exc:
        log.error("No pude guardar la clave: %s", exc)
        return False
    finally:
        if temporal and os.path.exists(temporal):
            try:
                os.unlink(temporal)
            except OSError:
                pass


def borrar() -> bool:
    try:
        rutas.ARCHIVO_CREDENCIALES.unlink(missing_ok=True)
        registro.olvidar_secretos()
        log.info("Credenciales eliminadas de esta máquina.")
        return True
    except OSError as exc:
        log.error("No pude borrar las credenciales: %s", exc)
        return False


def huella(clave: str) -> str:
    """Identificador no reversible para mostrar en pantalla sin revelar la clave."""
    if not clave:
        return "sin clave"
    return f"clave …{clave[-4:]}" if len(clave) > 8 else "clave cargada"
