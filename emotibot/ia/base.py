"""Contrato común de los proveedores de inteligencia.

La identidad y el diálogo no saben qué proveedor contesta. Cambiar de un
modelo remoto a uno local, o al guion sin IA, no toca ni una línea del resto
del programa: es el punto que faltaba en el prototipo, donde la disponibilidad
del robot estaba igualada a la disponibilidad de una única API.
"""
from __future__ import annotations

import enum
import json
from dataclasses import dataclass, field
from typing import Protocol


class Clase(enum.Enum):
    """Clasificación de fallos, para decidir si degradar o reintentar."""

    PETICION = "peticion"            # 400: la petición no vale para el modelo
    CUOTA = "cuota"                  # 429: NUNCA se reintenta
    AUTENTICACION = "autenticacion"  # 401/403 CON respuesta JSON de la API
    # 401/403 SIN respuesta JSON de la API: un cortafuegos de borde (p. ej.
    # Cloudflare, código 1010) rechazó al cliente HTTP antes de mirar la
    # clave. La clave puede estar perfectamente bien.
    BLOQUEO_CLIENTE = "bloqueo_cliente"
    MODELO = "modelo"                # 404 con respuesta JSON de la API
    INTERNO = "error_interno"        # 500 y otros 5xx no clasificados
    SOBRECARGA = "sobrecarga"        # 503
    TIEMPO = "tiempo"                # 504 o timeout local
    RED = "red"
    VACIA = "respuesta_vacia"
    SIN_PRESUPUESTO = "sin_presupuesto"
    NO_DISPONIBLE = "no_disponible"
    TRUNCADA = "truncada"            # Fase 1, A2: cortada por el tope de tokens
    OTRO = "otro"


MENSAJES = {
    Clase.PETICION: "El modelo rechazó la forma de la petición. Mira el "
                    "registro: dice qué argumento no acepta.",
    Clase.CUOTA: "Me quedé sin cuota de inteligencia por hoy. Sigo aquí para "
                 "las actividades que funcionan sin conexión.",
    Clase.AUTENTICACION: "La clave de acceso fue rechazada. Pulsa K para "
                         "revisarla.",
    Clase.BLOQUEO_CLIENTE: "El servicio bloqueó la conexión de este programa "
                           "antes de comprobar la clave. No es la clave: mira "
                           "el registro.",
    Clase.INTERNO: "El servicio tuvo un error interno.",
    Clase.MODELO: "El modelo configurado no está disponible para esta clave.",
    Clase.SOBRECARGA: "El servicio está sobrecargado ahora mismo.",
    Clase.TIEMPO: "La respuesta tardó demasiado.",
    Clase.RED: "No tengo conexión en este momento.",
    Clase.VACIA: "No recibí ninguna respuesta.",
    Clase.SIN_PRESUPUESTO: "Alcancé el límite de consultas que me puse para hoy.",
    Clase.NO_DISPONIBLE: "Ese proveedor no está configurado.",
    Clase.TRUNCADA: "La respuesta llegó cortada.",
    Clase.OTRO: "Hubo un problema al consultar la inteligencia.",
}


def _es_json_de_api(cuerpo: str) -> bool:
    """¿El cuerpo es un objeto JSON, como los que devuelve la API?

    Un cortafuegos de borde contesta con texto plano («error code: 1010») o
    HTML; la API del proveedor, con un objeto JSON. Esa diferencia es la que
    separa «el servicio rechazó tu clave» de «algo bloqueó la conexión antes».
    """
    try:
        return isinstance(json.loads(cuerpo), dict)
    except (TypeError, ValueError):
        return False


def clasificar_http(codigo: int, cuerpo: str = "") -> Clase:
    """Clase de un error HTTP según el código Y según quién contestó.

    - 401/403 con JSON de la API: autenticación real.
    - 401/403 sin JSON: bloqueo del cliente en el borde. Nunca autenticación.
    - 404 con JSON: modelo inexistente o no disponible para esta cuenta.
      Sin JSON: otra cosa (ruta mal escrita, proxy…).
    - 429: cuota. 400: petición. 502/503: sobrecarga. 504: tiempo.
    - 500 y demás 5xx: error interno del servicio.
    """
    de_api = _es_json_de_api(cuerpo)
    if codigo in (401, 403):
        return Clase.AUTENTICACION if de_api else Clase.BLOQUEO_CLIENTE
    if codigo == 404:
        return Clase.MODELO if de_api else Clase.OTRO
    if codigo == 429:
        return Clase.CUOTA
    if codigo == 400:
        return Clase.PETICION
    if codigo in (502, 503):
        return Clase.SOBRECARGA
    if codigo == 504:
        return Clase.TIEMPO
    if 500 <= codigo < 600:
        return Clase.INTERNO
    return Clase.OTRO


class ErrorProveedor(RuntimeError):
    def __init__(self, clase: Clase, detalle: str = "") -> None:
        super().__init__(detalle or clase.value)
        self.clase = clase
        self.detalle = detalle

    def mensaje_usuario(self) -> str:
        return MENSAJES.get(self.clase, MENSAJES[Clase.OTRO])

    @property
    def es_transitorio(self) -> bool:
        """Un fallo pasajero justifica probar OTRO proveedor, nunca repetir
        la misma llamada con el mismo modelo: eso consumiría cuota dos veces."""
        return self.clase in (Clase.SOBRECARGA, Clase.TIEMPO, Clase.RED,
                              Clase.VACIA)


@dataclass
class Turno:
    usuario: str
    robot: str


@dataclass
class Peticion:
    texto: str
    instrucciones: str
    historial: tuple[Turno, ...] = field(default_factory=tuple)
    # Fase 1, B5: tope de salida de la RUTA. None = el del proveedor (v1.7).
    max_tokens: int | None = None
    papel: str = ""


# Motivo normalizado por el que terminó la generación (Fase 1, A2). Cada
# proveedor lo nombra a su manera —`stop`/`length` en la API de OpenAI,
# `STOP`/`MAX_TOKENS` en Gemini—; el resto del programa solo ve estos.
FIN_COMPLETA = "completa"
FIN_TRUNCADA = "truncada"      # alcanzó el tope de tokens: frase a medias
FIN_FILTRADA = "filtrada"      # el proveedor cortó por su filtro de contenido
FIN_OTRO = "otro"
FIN_DESCONOCIDO = ""           # el proveedor no lo dijo

_MOTIVOS = {
    "stop": FIN_COMPLETA, "end_turn": FIN_COMPLETA, "eos": FIN_COMPLETA,
    "length": FIN_TRUNCADA, "max_tokens": FIN_TRUNCADA,
    "content_filter": FIN_FILTRADA, "safety": FIN_FILTRADA,
    "recitation": FIN_FILTRADA, "prohibited_content": FIN_FILTRADA,
}


def normalizar_motivo_fin(crudo: object) -> str:
    """Traduce el motivo de fin de cualquier proveedor a los valores FIN_*."""
    if crudo is None:
        return FIN_DESCONOCIDO
    nombre = getattr(crudo, "name", None) or str(crudo)
    nombre = nombre.strip().lower().rsplit(".", 1)[-1]
    if not nombre or nombre in ("none", "finish_reason_unspecified"):
        return FIN_DESCONOCIDO
    return _MOTIVOS.get(nombre, FIN_OTRO)


@dataclass
class Respuesta:
    """Lo que devuelve un proveedor.

    Todo campo añadido después de `segundos` DEBE llevar valor por defecto:
    lo construyen tres proveedores (`openai_compat`, `gemini`, `guion`) y un
    campo obligatorio rompería en silencio a los que no lo rellenan.
    """

    texto: str
    proveedor: str
    modelo: str = ""
    segundos: float = 0.0
    # Fase 1, A2: por qué terminó la generación (valores FIN_*).
    motivo_fin: str = FIN_DESCONOCIDO
    # Fase 1, A2: el texto se recortó a la última frase completa.
    recortada: bool = False
    # Fase 1, A3: consumo informado por el proveedor; None si no lo informó.
    tokens_entrada: int | None = None
    tokens_salida: int | None = None

    @property
    def truncada(self) -> bool:
        return self.motivo_fin == FIN_TRUNCADA


class Proveedor(Protocol):
    nombre: str

    def disponible(self) -> bool: ...

    def responder(self, peticion: Peticion) -> Respuesta: ...
