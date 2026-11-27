"""Carga de ajustes: JSON del repositorio + sobrescritura por entorno.

Prioridad (de menor a mayor):
  1. valores por defecto del código
  2. config/ajustes.json del repositorio
  3. ~/.config/emotibot/ajustes.json de esta máquina
  4. variables de entorno EMOTI_*

Así el repositorio puede ir a GitHub con valores genéricos y cada Raspberry Pi
mantiene los suyos sin tocar el código ni generar conflictos de merge.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from . import registro, rutas

log = registro.obtener("ajustes")

# Patrón permitido para nombres de dispositivo ALSA. Lo aplica el motor ALSA
# justo antes de construir los argumentos del subproceso, que es donde
# importa. PortAudio no pasa por aquí: su dispositivo va a una llamada de
# biblioteca y en Windows los nombres llevan espacios y paréntesis.
import re

_RE_DISPOSITIVO = re.compile(r"^[A-Za-z0-9_:,.=+\-]{1,64}$")


def dispositivo_valido(valor: object) -> str | None:
    if not valor:
        return None
    texto = str(valor).strip()
    if _RE_DISPOSITIVO.match(texto):
        return texto
    log.warning("Dispositivo ALSA con formato no permitido; se ignora.")
    return None


@dataclass(frozen=True)
class AjustesAudio:
    motor: str = "auto"              # auto | alsa | portaudio
    frecuencia_captura: int = 16000
    frecuencia_salida: int = 22050
    dispositivo_captura: str | None = None
    dispositivo_salida: str | None = None
    ms_asentamiento: int = 400
    ms_calibracion: int = 450
    factor_umbral: float = 2.2
    piso_umbral_rms: int = 120
    histeresis: float = 0.65
    bloques_confirmacion: int = 3
    silencio_final_s: float = 0.60
    max_audio_s: float = 12.0
    # Volumen de salida, 0-1: solo BAJA (nunca amplifica ni satura).
    volumen: float = 1.0
    margen_cola_s: float = 0.25
    segundos_grabacion_fija: int = 5


@dataclass(frozen=True)
class AjustesVoz:
    motor: str = "auto"              # auto | piper | espeak | ninguno
    modelo_piper: str = "~/emoti-voices/es_MX-claude-high.onnx"
    velocidad: float = 0.88          # <1 habla más rápido; 1.0 es lo normal
    velocidad_espeak: int = 165
    max_caracteres: int = 500
    # Ritmo elegido en la configuración, encima de la velocidad de la voz
    # del perfil: >1 más lento, <1 más rápido.
    ajuste_velocidad: float = 1.0


@dataclass(frozen=True)
class AjustesStt:
    motor: str = "auto"              # auto | whisper | remoto | ninguno
    # Dos trabajos, dos modelos (corpus de voz real, 27-11-2026):
    # - conversación: small SIN pista: 9/9 en las frases que base rompía
    #   («no sé qué hacer», «¿me propones otra cosa?»);
    # - despertar («Hola Emoti»): base CON la pista del nombre: más rápido
    #   y acierta el nombre que small transcribía «ole moti».
    modelo_whisper: str = "small"
    modelo_activacion: str = "base"
    computo_whisper: str = "int8"
    idioma: str = "es"


@dataclass(frozen=True)
class AjustesIa:
    # gpt-oss-20b justo detrás de Qwen: misma cuenta de Groq (no salva una
    # cuota agotada), pero sí un fallo o un cuelgue de Qwen.
    orden_proveedores: tuple[str, ...] = (
        "conversacion", "candidato_gpt_oss_20b", "razonamiento", "remoto", "local",
        "guion",
    )
    modelo_remoto: str = "gemini-3.5-flash-lite"
    modelo_remoto_alterno: str | None = None
    timeout_remoto_ms: int = 12000      # Groq (y OpenRouter)
    # Gemini, el suyo: con 12 s fallaba 1 de cada 8 con 504 a los 11,6 s. El
    # SDK manda el timeout al servidor (X-Server-Timeout) y es el propio
    # servidor el que corta: ese 504 era nuestro plazo, no un fallo suyo.
    timeout_gemini_ms: int = 20000
    # Techo del TURNO entero (todos los proveedores juntos). Agotado, se deja
    # de probar y contesta lo local. Cada proveedor conserva su timeout.
    # 15 s (decisión del responsable, 23-11): un cuelgue de Qwen (12 s) más
    # gpt-oss (máx. visto 1,35 s) caben; 20 s solo añadían silencio.
    plazo_turno_ms: int = 15000
    # «breve» pide respuestas más cortas: baja el tope de la ruta, nunca lo
    # sube (ver Orquestador.preparar).
    longitud_respuesta: str = "normal"
    max_tokens_respuesta: int = 120
    temperatura: float = 0.6
    pensamiento: str = "off"         # off | bajo
    timeout_local_ms: int = 45000
    presupuesto_diario: int = 180
    presupuesto_por_minuto: int = 10
    # Fase 1, A2. PROVISIONAL hasta la decisión §13.8a del responsable.
    # "recortar": a la última frase completa; si no hay, respaldo local.
    # "ninguna": comportamiento de la v1.7 (se pronuncia tal cual).
    politica_truncado: str = "recortar"


@dataclass(frozen=True)
class AjustesDialogo:
    # 12 (23-11-2026; antes 4). Coste medido con el prompt actual: ~+313
    # tokens reales por turno (1.034 → 1.347); con los topes de Groq, de 6 a
    # 4 turnos por minuto y de 173 a 133 al día (ver bitácora).
    max_turnos_memoria: int = 12
    guardar_transcripciones: bool = False
    # «Hola Emoti» (emotibot/activacion.py). Apagado: solo ESPACIO, como antes.
    activacion_por_voz: bool = False
    saludo_inicial: bool = False        # decir hola al arrancar
    # Conversación seguida: tras contestar, el micrófono se reabre solo
    # (con las barras a la vista). Apagada por defecto: ver bitácora.
    conversacion_continua: bool = False
    turnos_seguidos_max: int = 6        # y como mucho 3 minutos por conversación
    actividades: bool = True            # respiración y ordenar ideas
    respiracion_ritmo: str = "4-4-6"    # inhalar-sostener-exhalar, en segundos


@dataclass(frozen=True)
class AjustesRostro:
    pantalla_completa: bool = True
    fps: int = 30
    mostrar_boton_menu: bool = True     # ☰ arriba a la derecha
    tamano_rostro: float = 1.0          # 1 = el de siempre; solo más pequeño
    animaciones: bool = True            # respiración y deriva de la mirada
    parpadeo: bool = True
    mostrar_metricas: bool = True
    mostrar_controles: bool = True
    # False: solo los rasgos sobre el fondo, sin cabeza ni orejas (la
    # pantalla del robot físico va dentro del cuerpo). Los rasgos crecen
    # para ocupar el área que deja la cabeza. Ver rostro/cara.py.
    carcasa: bool = True
    # Perfil de rostro: proporciones y colores, como datos, en
    # config/rostro/<perfil>.json. Una variante (D10) es otro archivo.
    perfil: str = "hybrid_balanced"


@dataclass(frozen=True)
class AjustesRegion:
    # País donde se usa el robot. Los números de config/crisis.json solo se
    # ofrecen si son de este país: fuera de él no valen.
    pais: str = "República Dominicana"


@dataclass(frozen=True)
class Ajustes:
    audio: AjustesAudio = field(default_factory=AjustesAudio)
    voz: AjustesVoz = field(default_factory=AjustesVoz)
    stt: AjustesStt = field(default_factory=AjustesStt)
    ia: AjustesIa = field(default_factory=AjustesIa)
    dialogo: AjustesDialogo = field(default_factory=AjustesDialogo)
    rostro: AjustesRostro = field(default_factory=AjustesRostro)
    region: AjustesRegion = field(default_factory=AjustesRegion)


_SECCIONES = {
    "audio": AjustesAudio,
    "voz": AjustesVoz,
    "stt": AjustesStt,
    "ia": AjustesIa,
    "dialogo": AjustesDialogo,
    "rostro": AjustesRostro,
    "region": AjustesRegion,
}

# Sobrescrituras por entorno: EMOTI_<SECCION>_<CAMPO>, y algunos atajos
# heredados de las versiones anteriores para no romper costumbres.
_ATAJOS = {
    "EMOTI_MOTOR_AUDIO": ("audio", "motor"),
    "EMOTI_GEMINI_MODEL": ("ia", "modelo_remoto"),
    "EMOTI_FALLBACK_MODEL": ("ia", "modelo_remoto_alterno"),
    "EMOTI_PIPER_MODEL": ("voz", "modelo_piper"),
    "EMOTI_SILENCIO": ("audio", "silencio_final_s"),
    "EMOTI_MAX_AUDIO": ("audio", "max_audio_s"),
    "EMOTI_VAD_RMS": ("audio", "piso_umbral_rms"),
    "EMOTI_FPS": ("rostro", "fps"),
}


def _leer_json(ruta: Path) -> dict[str, Any]:
    if not ruta.is_file():
        return {}
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("No pude leer %s (%s); uso los valores anteriores.", ruta.name, exc)
        return {}
    return datos if isinstance(datos, dict) else {}


def _convertir(destino_tipo: Any, valor: Any) -> Any:
    """Convierte un valor crudo al tipo declarado en la dataclass."""
    if valor is None:
        return None
    texto = str(valor)
    origen = str(destino_tipo)
    if "bool" in origen:
        if isinstance(valor, bool):
            return valor
        return texto.strip().lower() in {"1", "true", "si", "sí", "yes", "on"}
    if "int" in origen and "float" not in origen:
        return int(float(texto))
    if "float" in origen:
        return float(texto)
    if "tuple" in origen:
        if isinstance(valor, (list, tuple)):
            return tuple(str(v) for v in valor)
        return tuple(p.strip() for p in texto.split(",") if p.strip())
    return texto


def _construir_seccion(clase: Any, crudo: dict[str, Any]) -> Any:
    kwargs: dict[str, Any] = {}
    validos = {f.name: f for f in fields(clase)}
    for nombre, valor in crudo.items():
        if nombre.startswith("_"):
            continue
        campo = validos.get(nombre)
        if campo is None:
            log.debug("Ajuste desconocido ignorado: %s.%s", clase.__name__, nombre)
            continue
        try:
            kwargs[nombre] = _convertir(campo.type, valor)
        except (TypeError, ValueError):
            log.warning("Valor inválido para %s; uso el predeterminado.", nombre)
    return clase(**kwargs)


def _aplicar_entorno(crudo: dict[str, dict[str, Any]]) -> None:
    for clave, valor in os.environ.items():
        if clave in _ATAJOS:
            seccion, campo = _ATAJOS[clave]
            crudo.setdefault(seccion, {})[campo] = valor
            continue
        if not clave.startswith("EMOTI_"):
            continue
        resto = clave[len("EMOTI_"):].lower()
        for seccion in _SECCIONES:
            prefijo = seccion + "_"
            if resto.startswith(prefijo):
                crudo.setdefault(seccion, {})[resto[len(prefijo):]] = valor
                break


def cargar() -> Ajustes:
    crudo: dict[str, dict[str, Any]] = {}
    for origen in (rutas.CONFIG_REPO / "ajustes.json",
                   rutas.CONFIG_USUARIO / "ajustes.json"):
        for seccion, valores in _leer_json(origen).items():
            if seccion in _SECCIONES and isinstance(valores, dict):
                crudo.setdefault(seccion, {}).update(valores)
    # Perfil de usuario (D10): rostro, voz y modelo, sobre los archivos. Los
    # ajustes de entorno (EMOTI_*) siguen mandando, para depurar.
    from . import perfil_usuario
    orden = crudo.get("ia", {}).get("orden_proveedores", AjustesIa().orden_proveedores)
    for seccion, valores in perfil_usuario.sobrescrituras(
            perfil_usuario.cargar(), orden).items():
        crudo.setdefault(seccion, {}).update(valores)
    _aplicar_entorno(crudo)

    secciones = {
        nombre: _construir_seccion(clase, crudo.get(nombre, {}))
        for nombre, clase in _SECCIONES.items()
    }
    ajustes = Ajustes(**secciones)

    return ajustes


def ruta_piper(ajustes: Ajustes) -> Path:
    return Path(ajustes.voz.modelo_piper).expanduser()


def guardar_carcasa(carcasa: bool) -> Path:
    """Guarda `rostro.carcasa` en los ajustes de ESTA máquina.

    Es una decisión de instalación (¿la pantalla va dentro del robot?), no
    de gusto: va en `ajustes.json` de la carpeta de configuración del
    usuario, no en el perfil. Solo escribe ese campo y conserva todo lo
    demás del archivo. Si el archivo existe y no se puede leer, NO se
    sobrescribe (se perdería lo que tenga): se lanza el error.
    """
    ruta = _guardar_usuario({"rostro": {"carcasa": bool(carcasa)}})
    if os.environ.get("EMOTI_ROSTRO_CARCASA"):
        log.warning("Guardado, pero EMOTI_ROSTRO_CARCASA manda al arrancar.")
    return ruta


def _guardar_usuario(cambios: dict[str, dict[str, Any]]) -> Path:
    """Escribe esos campos en el `ajustes.json` de la máquina y conserva el
    resto. Interno: lo usan `guardar_carcasa` y la configuración
    (emotibot/configuracion.py), que es quien decide QUÉ se puede escribir.
    Un archivo ilegible no se sobrescribe."""
    ruta = rutas.CONFIG_USUARIO / "ajustes.json"
    datos: dict[str, Any] = {}
    if ruta.is_file():
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        if not isinstance(datos, dict):
            raise ValueError(f"{ruta} no es un objeto JSON; no lo sobrescribo.")
    for nombre_seccion, campos in cambios.items():
        seccion = datos.setdefault(nombre_seccion, {})
        if not isinstance(seccion, dict):
            raise ValueError(f"{ruta}: «{nombre_seccion}» no es una sección; "
                             "no lo sobrescribo.")
        seccion.update(campos)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_name(ruta.name + ".tmp")
    temporal.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    temporal.replace(ruta)
    return ruta
