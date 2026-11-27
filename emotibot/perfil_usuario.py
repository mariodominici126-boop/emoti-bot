"""Perfil de usuario (D10): una opción en cada eje, elegida por separado.

    rostro · voz · personalidad · estilo comunicativo · modelo

Cada eje es un archivo de datos con nombre (ver el README, «Perfil de
usuario»), y el perfil (`config/perfil.json`) solo nombra cuál usar en cada
uno. Añadir una opción es escribir un archivo; no hace falta código.

INDEPENDENCIA. Cada eje toca una sola cosa y nada más:
- rostro → `rostro.perfil` (config/rostro/<nombre>.json);
- voz → `voz.motor`, `voz.modelo_piper`, `voz.velocidad` y `voz.velocidad_espeak`
  (config/voces/<nombre>.json);
- modelo → qué entrada de config/proveedores.json hace de «conversacion»;
- personalidad → la sección de tono de las instrucciones
  (config/personalidades/<nombre>.json);
- estilo → la sección de estilo comunicativo (config/estilos/<nombre>.json).

LO QUE NINGÚN PERFIL PUEDE TOCAR (§14.5). No es una comprobación al
guardar, es la forma del código:
- la ruta de seguridad y el directorio de ayuda no importan este módulo ni
  reciben nada de él (hay una prueba de ello);
- `aplicar()` solo puede escribir los campos de arriba: los topes de
  longitud, de caracteres y de consumo no están a su alcance;
- la personalidad y el estilo solo son texto que va en SUS secciones de las
  instrucciones, siempre seguidas de «Esto prevalece…», normas fijas
  y están en el código (identidad.py), no en ningún archivo de preferencias;
- un perfil con cualquier otra clave (p. ej. «seguridad» o «max_tokens») se
  rechaza entero y se usa el perfil por defecto.
"""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path

from . import registro, rutas

log = registro.obtener("perfil_usuario")

EJES = ("rostro", "voz", "personalidad", "estilo", "modelo")
ARCHIVO = rutas.CONFIG_REPO / "perfil.json"
ARCHIVO_USUARIO = rutas.CONFIG_USUARIO / "perfil.json"
DIRECTORIOS = {
    "rostro": rutas.CONFIG_REPO / "rostro",
    "voz": rutas.CONFIG_REPO / "voces",
    "personalidad": rutas.CONFIG_REPO / "personalidades",
    "estilo": rutas.CONFIG_REPO / "estilos",
}
CAMPOS_VOZ = ("motor", "modelo_piper", "velocidad", "velocidad_espeak")
CLAVE_TEXTO = {"personalidad": "tono", "estilo": "reglas"}
# UN SOLO TECHO para personalidad y estilo JUNTOS (D10, tanda 2): si cada
# eje tuviera el suyo, elegir los dos duplicaría el coste. Derivado de las
# 16 combinaciones publicadas (4 personalidades × 4 estilos): todas llevan 4
# frases, la más larga mide 80 caracteres y la peor (analitica × casual)
# suma 278. El techo queda un poco por encima: cada carácter se paga en cada
# turno y resta turnos por minuto (ver bitácora). Lo impone el código:
# `validar()` rechaza el perfil y `aplicar_identidad()` no añade nada.
MAX_LINEAS_JUNTAS = 5
MAX_CARACTERES_JUNTOS = 320
MAX_CARACTERES_LINEA = 100
MODELO_BASE = "conversacion"


class ErrorPerfilUsuario(ValueError):
    pass


@dataclass(frozen=True)
class PerfilUsuario:
    rostro: str = "hybrid_balanced"
    voz: str = "daniela"
    personalidad: str = "estandar"
    estilo: str = "estandar"
    modelo: str = MODELO_BASE


POR_DEFECTO = PerfilUsuario()


# ----------------------------------------------------------------- opciones
def opciones(eje: str) -> list[str]:
    """Las opciones disponibles en un eje (los archivos que existen)."""
    if eje == "modelo":
        from .ia.openai_compat import cargar_endpoints
        endpoints = cargar_endpoints(rutas.ARCHIVO_PROVEEDORES)
        return [MODELO_BASE] + sorted(n for n, e in endpoints.items()
                                      if e.papel == MODELO_BASE and n != MODELO_BASE)
    if eje not in DIRECTORIOS:
        raise ErrorPerfilUsuario(f"Eje desconocido: {eje!r}")
    return sorted(p.stem for p in DIRECTORIOS[eje].glob("*.json"))


def validar(datos: dict) -> PerfilUsuario:
    """Perfil estricto: exactamente los cinco ejes, cada uno con una opción
    que exista. Las claves que empiezan por «_» son notas."""
    if not isinstance(datos, dict):
        raise ErrorPerfilUsuario("El perfil debe ser un objeto JSON.")
    claves = {k for k in datos if not str(k).startswith("_")}
    sobran, faltan = claves - set(EJES), set(EJES) - claves
    if sobran or faltan:
        raise ErrorPerfilUsuario(
            f"Ejes: sobran {sorted(sobran) or 'ninguno'}; faltan {sorted(faltan) or 'ninguno'}. "
            "Un perfil solo elige rostro, voz, personalidad, estilo y modelo.")
    valores = {}
    for eje in EJES:
        valor = datos[eje]
        if not isinstance(valor, str) or valor not in opciones(eje):
            raise ErrorPerfilUsuario(
                f"{eje}: {valor!r} no es una opción. Opciones: {', '.join(opciones(eje))}")
        valores[eje] = valor
    perfil = PerfilUsuario(**valores)
    comprobar_techo(leer_lineas("personalidad", perfil.personalidad),
                    leer_lineas("estilo", perfil.estilo))
    return perfil


def cargar(ruta: Path | None = None) -> PerfilUsuario:
    """El perfil configurado. Si no es válido, el perfil por defecto (avisando)."""
    return cargar_con_aviso(ruta)[0]


def cargar_con_aviso(ruta: Path | None = None) -> tuple[PerfilUsuario, str]:
    """(perfil, aviso). Un perfil corrupto o incompleto no rompe el arranque:
    se usa el de por defecto y el aviso dice por qué, para enseñarlo."""
    archivo = ruta or (ARCHIVO_USUARIO if ARCHIVO_USUARIO.is_file() else ARCHIVO)
    if not archivo.is_file():
        return POR_DEFECTO, ""
    try:
        return validar(json.loads(archivo.read_text(encoding="utf-8"))), ""
    except (OSError, ValueError) as exc:
        log.error("Perfil de usuario %s no válido (%s). Uso el perfil por defecto.",
                  archivo, exc)
        return POR_DEFECTO, "Tu perfil no es válido: uso el estándar."


def primer_arranque() -> bool:
    """Nadie ha elegido todavía en esta máquina: no hay perfil propio.

    El perfil elegido vive con los ajustes y las credenciales de la máquina
    (`ARCHIVO_USUARIO`), nunca en el repositorio; `config/perfil.json` es el
    perfil por defecto que se distribuye."""
    return not ARCHIVO_USUARIO.is_file()


def guardar(perfil: PerfilUsuario, ruta: Path | None = None) -> Path:
    """Escribe el perfil: los cinco ejes y NADA más.

    Lo escrito se valida con las mismas reglas que al cargar ANTES de tocar
    el disco (un perfil que no se podría cargar no se escribe), y se escribe
    entero o nada (archivo temporal y reemplazo)."""
    if not isinstance(perfil, PerfilUsuario):
        raise ErrorPerfilUsuario("Solo se guarda un PerfilUsuario.")
    datos = {eje: getattr(perfil, eje) for eje in EJES}
    validar(datos)
    destino = Path(ruta or ARCHIVO_USUARIO)
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_name(destino.name + ".tmp")
    temporal.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    temporal.replace(destino)
    log.info("Perfil guardado en %s: %s.", destino, resumen(perfil))
    return destino


# --------------------------------------------------------------- archivos de eje
def _leer(eje: str, nombre: str) -> dict:
    archivo = DIRECTORIOS[eje] / f"{nombre}.json"
    datos = json.loads(archivo.read_text(encoding="utf-8"))
    if not isinstance(datos, dict):
        raise ErrorPerfilUsuario(f"{archivo.name}: debe ser un objeto JSON.")
    return {k: v for k, v in datos.items() if not str(k).startswith("_")}


def leer_voz(nombre: str) -> dict:
    """Los campos de voz de una opción. Cualquier otro campo se rechaza."""
    datos = _leer("voz", nombre)
    datos.pop("descripcion", None)
    sobran = set(datos) - set(CAMPOS_VOZ)
    if sobran:
        raise ErrorPerfilUsuario(
            f"voz {nombre}: campos no admitidos {sorted(sobran)}; solo {list(CAMPOS_VOZ)}.")
    return datos


def leer_lineas(eje: str, nombre: str) -> tuple[str, ...]:
    """Las líneas de tono (personalidad) o de estilo, validadas.

    Cada línea es una frase suelta: sin saltos de línea, sin hacerse pasar
    por una sección de las instrucciones y sin números de teléfono. Lo que
    digan, en cambio, no se juzga aquí: aunque una línea pida saltarse las
    normas, va en su sección y detrás van las normas fijas que prevalecen.
    """
    from .dialogo import directorio
    from .identidad import ENCABEZADOS_RESERVADOS
    datos = _leer(eje, nombre)
    clave = CLAVE_TEXTO[eje]
    sobran = set(datos) - {clave, "descripcion"}
    if sobran:
        raise ErrorPerfilUsuario(f"{eje} {nombre}: campos no admitidos {sorted(sobran)}.")
    lineas = datos.get(clave, [])
    if not isinstance(lineas, list) or len(lineas) > MAX_LINEAS_JUNTAS:
        raise ErrorPerfilUsuario(f"{eje} {nombre}: «{clave}» es una lista de "
                                 f"como mucho {MAX_LINEAS_JUNTAS} frases.")
    salida = []
    for linea in lineas:
        if not isinstance(linea, str) or not linea.strip():
            raise ErrorPerfilUsuario(f"{eje} {nombre}: cada línea es un texto.")
        linea = linea.strip()
        if "\n" in linea or "\r" in linea or len(linea) > MAX_CARACTERES_LINEA:
            raise ErrorPerfilUsuario(f"{eje} {nombre}: una línea por frase, de hasta "
                                     f"{MAX_CARACTERES_LINEA} caracteres.")
        if any(e.lower() in linea.lower() for e in ENCABEZADOS_RESERVADOS):
            raise ErrorPerfilUsuario(f"{eje} {nombre}: una línea no puede imitar una "
                                     "sección de las instrucciones.")
        if directorio.contiene_telefono(linea):
            raise ErrorPerfilUsuario(f"{eje} {nombre}: los números de ayuda no van aquí; "
                                     "viven en config/crisis.json.")
        salida.append(linea)
    comprobar_techo(tuple(salida), ())
    return tuple(salida)


def comprobar_techo(tono: tuple[str, ...], reglas: tuple[str, ...]) -> None:
    """El techo ÚNICO de personalidad y estilo juntos."""
    juntas = tuple(tono) + tuple(reglas)
    if len(juntas) > MAX_LINEAS_JUNTAS or sum(map(len, juntas)) > MAX_CARACTERES_JUNTOS:
        raise ErrorPerfilUsuario(
            f"Personalidad y estilo juntos: {len(juntas)} frases y "
            f"{sum(map(len, juntas))} caracteres; el techo es {MAX_LINEAS_JUNTAS} frases "
            f"y {MAX_CARACTERES_JUNTOS} caracteres entre los dos.")


# ------------------------------------------------------------------- aplicar
def sobrescrituras(perfil: PerfilUsuario, orden_proveedores) -> dict[str, dict]:
    """Lo único que un perfil escribe en los ajustes, por sección y campo.

    Es la lista cerrada: rostro.perfil, los cuatro campos de voz y
    ia.orden_proveedores. Ningún tope (longitud, caracteres, consumo) aparece.
    """
    try:
        voz = leer_voz(perfil.voz)
    except (OSError, ValueError) as exc:
        log.error("Voz %s no válida (%s): uso la de config/ajustes.json.", perfil.voz, exc)
        voz = {}
    orden = tuple(orden_proveedores)
    if perfil.modelo != MODELO_BASE:
        # El elegido ocupa el sitio de «conversacion». Si ya estaba en la
        # cadena (gpt-oss va de respaldo detrás de Qwen), se intercambian:
        # Qwen pasa a ser su respaldo y nadie aparece dos veces.
        orden = tuple(perfil.modelo if n == MODELO_BASE
                      else MODELO_BASE if n == perfil.modelo else n for n in orden)
    return {"rostro": {"perfil": perfil.rostro}, "voz": voz,
            "ia": {"orden_proveedores": orden}}


def aplicar(ajustes, perfil: PerfilUsuario):
    """Ajustes con el rostro, la voz y el modelo del perfil. Nada más cambia."""
    cambios = sobrescrituras(perfil, ajustes.ia.orden_proveedores)
    return dataclasses.replace(ajustes, **{
        seccion: dataclasses.replace(getattr(ajustes, seccion), **valores)
        for seccion, valores in cambios.items()})


def aplicar_identidad(identidad, perfil: PerfilUsuario):
    """Identidad con el tono y el estilo del perfil, en sus secciones.

    Solo escribe `estilo_elegido` y `tono`: nombre, creador, límites y
    normas de config/identidad.json no están a su alcance.
    """
    def lineas(eje: str, nombre: str) -> tuple[str, ...]:
        # Cada eje por separado: un archivo roto no arrastra al otro.
        try:
            return leer_lineas(eje, nombre)
        except (OSError, ValueError) as exc:
            log.error("%s %s no válido (%s): no se añade nada.", eje, nombre, exc)
            return ()

    estilo, tono = lineas("estilo", perfil.estilo), lineas("personalidad", perfil.personalidad)
    try:
        comprobar_techo(tono, estilo)
    except ErrorPerfilUsuario as exc:
        log.error("%s No se añade ni el tono ni el estilo.", exc)
        estilo, tono = (), ()
    return dataclasses.replace(identidad, estilo_elegido=estilo, tono=tono)


def resumen(perfil: PerfilUsuario) -> str:
    return " · ".join(f"{eje} {getattr(perfil, eje)}" for eje in EJES)
