"""Proveedor para cualquier API compatible con OpenAI.

Qwen, DeepSeek y un `llama-server` en el propio equipo hablan todos el mismo
dialecto —`POST /chat/completions`—, así que son el mismo código con distinta
URL, modelo y clave. Cambiar de modelo pasa a ser editar
`config/proveedores.json`, no tocar Python.

Se usa `urllib` de la biblioteca estándar: una dependencia menos que instalar
en la Raspberry.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from .. import registro
from . import tokens
from .base import (FIN_DESCONOCIDO, FIN_TRUNCADA, Clase, ErrorProveedor,
                   Peticion, Respuesta, clasificar_http, normalizar_motivo_fin)
from .presupuesto import Presupuesto

log = registro.obtener("ia.openai")

_TIEMPO_SONDEO = 2.0
_SEGUNDOS_ENTRE_SONDEOS = 20.0


@dataclass
class Endpoint:
    """Lo que define a un proveedor en `config/proveedores.json`."""

    nombre: str
    url: str = ""
    modelo: str = ""
    clave: str = ""          # nombre con el que se guarda la clave, no la clave
    descripcion: str = ""
    max_tokens: int = 120
    temperatura: float = 0.6
    # Límites propios, por debajo de los del proveedor: frenar nosotros antes
    # de que nos frene él, porque en varios servicios las peticiones
    # rechazadas también cuentan para la cuota diaria.
    max_dia: int = 200
    max_minuto: int = 10
    # Fase 1, A3: topes propios de tokens. 0 = sin tope (se cuentan igual).
    max_tokens_dia: int = 0
    max_tokens_minuto: int = 0
    cabeceras: dict = field(default_factory=dict)
    # Parámetros extra del cuerpo propios de un modelo (p. ej. el esfuerzo de
    # razonamiento de GPT-OSS). No pueden pisar los que controla el robot.
    parametros: dict = field(default_factory=dict)
    # Ruta a la que se asimila en las mediciones (conversacion/razonamiento).
    # Vacío = su propio nombre. No afecta a qué contesta en producción.
    papel: str = ""

    @property
    def configurado(self) -> bool:
        return bool(self.url and self.modelo)

    @property
    def necesita_clave(self) -> bool:
        return bool(self.clave)

    @property
    def es_local(self) -> bool:
        return any(h in self.url for h in ("127.0.0.1", "localhost", "::1"))


# Campos que decide el robot y que un archivo de configuración no puede
# cambiar: el tope de tokens es parte de la contabilidad (A3) y de §14.5.
CAMPOS_PROTEGIDOS = frozenset({
    "model", "messages", "max_tokens", "max_completion_tokens", "stream",
    "stream_options", "n",
})


# Identificación del cliente en cada petición HTTP.
#
# Sin ella, urllib se presenta como «Python-urllib/3.x». Groq está detrás de
# Cloudflare, que bloquea esa firma con un 403 código 1010 («firma del
# navegador prohibida»): un bloqueo del CLIENTE, no de la clave. Esto es
# identificarse con un nombre propio y honesto, no imitar a un navegador.
# Si config/proveedores.json trae su propio «User-Agent», manda ese.
AGENTE_USUARIO = "EMOTI-BOT/1.8"


def cabeceras_peticion(endpoint: Endpoint, clave: str = "") -> dict[str, str]:
    """Cabeceras de /chat/completions. Las usan el robot y los instrumentos."""
    cabeceras = {"Content-Type": "application/json", "User-Agent": AGENTE_USUARIO}
    # Algunos servicios piden cabeceras propias para identificar la
    # aplicación; se declaran por proveedor en el archivo y prevalecen. Las
    # cabeceras HTTP no distinguen mayúsculas: «user-agent» sustituye a la
    # nuestra en vez de duplicarla.
    for nombre, valor in (endpoint.cabeceras or {}).items():
        nombre = str(nombre)
        for existente in [k for k in cabeceras if k.lower() == nombre.lower()]:
            del cabeceras[existente]
        cabeceras[nombre] = str(valor)
    if clave:
        cabeceras["Authorization"] = f"Bearer {clave}"
    return cabeceras


def cuerpo_peticion(endpoint: Endpoint, mensajes: list[dict], max_tokens: int,
                    stream: bool = False) -> dict:
    """Cuerpo de /chat/completions. Lo usan el robot y los instrumentos (B4)."""
    cuerpo = {str(k): v for k, v in (endpoint.parametros or {}).items()
              if str(k) not in CAMPOS_PROTEGIDOS}
    cuerpo.update({
        "model": endpoint.modelo,
        "messages": mensajes,
        "temperature": cuerpo.get("temperature", endpoint.temperatura),
        "max_tokens": max_tokens,
        "stream": stream,
    })
    return cuerpo


class ProveedorOpenAI:
    def __init__(
        self,
        endpoint: Endpoint,
        presupuesto: Presupuesto,
        obtener_clave,
        timeout_ms: int = 20000,
    ) -> None:
        self.endpoint = endpoint
        self.nombre = endpoint.nombre
        self.modelo = endpoint.modelo
        self.presupuesto = presupuesto
        self._obtener_clave = obtener_clave
        self.timeout_s = max(2.0, timeout_ms / 1000.0)
        self.ultimo_motivo = ""
        presupuesto.fijar_limites(endpoint.modelo, endpoint.max_dia,
                                  endpoint.max_minuto,
                                  endpoint.max_tokens_dia,
                                  endpoint.max_tokens_minuto)
        self._ultimo_sondeo = 0.0
        self._estaba_vivo = False

    # ------------------------------------------------------------ disponibilidad
    def _clave(self) -> str:
        if not self.endpoint.necesita_clave:
            return ""
        return self._obtener_clave(self.endpoint.clave) or ""

    def disponible(self) -> bool:
        if not self.endpoint.configurado:
            self.ultimo_motivo = (
                f"{self.nombre}: falta la URL o el modelo en "
                "config/proveedores.json."
            )
            return False
        if self.endpoint.necesita_clave and not self._clave():
            self.ultimo_motivo = (
                f"Sin clave de {self.endpoint.clave}. Púlsala con la tecla K."
            )
            return False
        # Si ni siquiera cabe la salida máxima, no tiene sentido intentarlo.
        permitido, motivo = self.presupuesto.puede_consultar(
            self.modelo, self.endpoint.max_tokens)
        if not permitido:
            self.ultimo_motivo = motivo
            return False
        if self.endpoint.es_local and not self._sondear():
            self.ultimo_motivo = "El servidor local no responde."
            return False
        self.ultimo_motivo = ""
        return True

    def _sondear(self) -> bool:
        """Solo para servidores locales: comprobar que están levantados.

        A un servicio remoto no se le hace ping en cada turno; si está caído,
        se verá al consultar y el error lo dirá.
        """
        ahora = time.monotonic()
        if ahora - self._ultimo_sondeo < _SEGUNDOS_ENTRE_SONDEOS:
            return self._estaba_vivo
        self._ultimo_sondeo = ahora
        base = self.endpoint.url.rstrip("/")
        for sufijo in ("/models", "/health"):
            try:
                peticion = urllib.request.Request(
                    base + sufijo, method="GET",
                    headers={"User-Agent": AGENTE_USUARIO})
                with urllib.request.urlopen(peticion, timeout=_TIEMPO_SONDEO) as r:
                    if 200 <= r.status < 300:
                        self._estaba_vivo = True
                        return True
            except (urllib.error.URLError, OSError, ValueError):
                continue
        self._estaba_vivo = False
        return False

    # ------------------------------------------------------------------ consulta
    def _mensajes(self, peticion: Peticion) -> list[dict]:
        mensajes = [{"role": "system", "content": peticion.instrucciones}]
        for turno in peticion.historial:
            mensajes.append({"role": "user", "content": turno.usuario})
            mensajes.append({"role": "assistant", "content": turno.robot})
        mensajes.append({"role": "user", "content": peticion.texto})
        return mensajes

    def responder(self, peticion: Peticion) -> Respuesta:
        if not self.endpoint.configurado:
            raise ErrorProveedor(Clase.NO_DISPONIBLE, self.ultimo_motivo)

        # A3, etapa previa: la entrada se conoce ya (el prompt está hecho) y
        # se estima al alza; la salida se acota con max_tokens.
        mensajes = self._mensajes(peticion)
        # B5: el tope lo pone la ruta de la pregunta; si no hay, el propio.
        max_tokens = peticion.max_tokens or self.endpoint.max_tokens
        entrada = tokens.estimar_entrada(m["content"] for m in mensajes)
        reserva, motivo = self.presupuesto.reservar(
            self.modelo, entrada + max_tokens,
            entrada_estimada=entrada,
        )
        if reserva is None:
            raise ErrorProveedor(Clase.SIN_PRESUPUESTO, motivo)

        try:
            respuesta = self._consultar(mensajes, max_tokens)
        except ErrorProveedor as exc:
            # A3, etapa posterior de un fallo: cuánto pudo contar el proveedor.
            self.presupuesto.anular(reserva, self._contabilizados(exc, reserva))
            raise
        except Exception:
            self.presupuesto.anular(reserva, reserva.tokens)
            raise
        self.presupuesto.confirmar(reserva, respuesta.tokens_entrada,
                                   respuesta.tokens_salida)
        return respuesta

    @staticmethod
    def _contabilizados(exc: ErrorProveedor, reserva) -> int:
        """Tokens que un fallo pudo haber consumido, hacia arriba si hay duda.

        - Rechazos que el proveedor emite sin procesar la petición (400, 401,
          403, 404, 429) o fallos de conexión: 0.
        - Tiempo agotado: la reserva entera, porque pudo generar todo.
        - Errores del servidor y respuestas ilegibles: la entrada estimada.
        """
        if exc.clase in (Clase.PETICION, Clase.AUTENTICACION, Clase.MODELO,
                         Clase.CUOTA, Clase.RED, Clase.BLOQUEO_CLIENTE):
            return 0
        if exc.clase is Clase.TIEMPO:
            return reserva.tokens
        return reserva.entrada_estimada

    def _consultar(self, mensajes: list[dict], max_tokens: int) -> Respuesta:
        cuerpo = json.dumps(cuerpo_peticion(self.endpoint, mensajes, max_tokens,
                                            stream=False)).encode("utf-8")

        cabeceras = cabeceras_peticion(self.endpoint, self._clave())
        solicitud = urllib.request.Request(
            self.endpoint.url.rstrip("/") + "/chat/completions",
            data=cuerpo, headers=cabeceras, method="POST",
        )
        inicio = time.monotonic()
        try:
            with urllib.request.urlopen(solicitud, timeout=self.timeout_s) as r:
                datos = json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            raise self._error_http(exc) from exc
        except (TimeoutError, urllib.error.URLError) as exc:
            motivo_red = getattr(exc, "reason", exc)
            clase = (Clase.TIEMPO if "timed out" in str(motivo_red).lower()
                     else Clase.RED)
            raise ErrorProveedor(
                clase, f"{self.nombre}: {registro.redactar(motivo_red)}"
            ) from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise ErrorProveedor(
                Clase.OTRO, f"{self.nombre}: {registro.redactar(exc)}"
            ) from exc

        texto = self._extraer(datos)
        motivo_fin = self._motivo_fin(datos)
        entrada, salida = self._uso(datos)
        if not texto and motivo_fin != FIN_TRUNCADA:
            raise ErrorProveedor(Clase.VACIA,
                                 f"{self.nombre} no devolvió texto.")
        # Una truncada vacía (un modelo de razonamiento que gastó el tope
        # pensando) se devuelve igual: la decide el orquestador con la
        # política de truncado, sin otra llamada.
        return Respuesta(
            texto=texto, proveedor=self.nombre, modelo=self.modelo,
            segundos=time.monotonic() - inicio,
            motivo_fin=motivo_fin, tokens_entrada=entrada,
            tokens_salida=salida,
        )

    @staticmethod
    def _motivo_fin(datos: dict) -> str:
        """A2: por qué terminó la generación (`finish_reason`)."""
        try:
            crudo = datos["choices"][0].get("finish_reason")
        except (KeyError, IndexError, TypeError, AttributeError):
            return FIN_DESCONOCIDO
        return normalizar_motivo_fin(crudo)

    @staticmethod
    def _uso(datos: dict) -> tuple[int | None, int | None]:
        """A3: tokens que informa el proveedor; (None, None) si no informa."""
        uso = datos.get("usage") if isinstance(datos, dict) else None
        if not isinstance(uso, dict):
            return None, None

        def entero(clave: str) -> int | None:
            valor = uso.get(clave)
            try:
                return int(valor) if valor is not None else None
            except (TypeError, ValueError):
                return None

        entrada, salida = entero("prompt_tokens"), entero("completion_tokens")
        if entrada is None and salida is None:
            total = entero("total_tokens")
            if total is not None:
                return total, 0
        return entrada, salida

    def _error_http(self, exc: urllib.error.HTTPError) -> ErrorProveedor:
        try:
            cuerpo = exc.read().decode("utf-8", "replace")
        except Exception:
            cuerpo = ""
        detalle = cuerpo[:500]
        # El cuerpo COMPLETO decide si contestó la API (JSON) o un
        # cortafuegos de borde; el recorte a 500 caracteres es solo para el
        # mensaje.
        clase = clasificar_http(exc.code, cuerpo)
        if clase is Clase.CUOTA:
            self.presupuesto.registrar_rechazo_cuota(self.modelo)
        mensaje = f"{self.nombre}: HTTP {exc.code} | {registro.redactar(detalle)}"
        log.warning("Consulta a %s fallida (%s): %s", self.nombre,
                    clase.value, mensaje[:300])
        return ErrorProveedor(clase, mensaje)

    @staticmethod
    def _extraer(datos: dict) -> str:
        try:
            mensaje = datos["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            return ""
        # Algunos modelos de razonamiento devuelven el razonamiento aparte;
        # al robot solo le interesa lo que debe pronunciar.
        texto = mensaje.get("content") or ""
        return str(texto).strip()


def cargar_endpoints(ruta) -> dict[str, Endpoint]:
    """Lee config/proveedores.json. Las claves que empiezan por _ son notas."""
    if not ruta.is_file():
        log.warning("No encontré %s; sin proveedores OpenAI.", ruta.name)
        return {}
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.error("No pude leer %s: %s", ruta.name, exc)
        return {}
    if not isinstance(datos, dict):
        return {}

    endpoints: dict[str, Endpoint] = {}
    for nombre, crudo in datos.items():
        if nombre.startswith("_") or not isinstance(crudo, dict):
            continue
        endpoints[nombre] = Endpoint(
            nombre=nombre,
            url=str(crudo.get("url", "")).strip(),
            modelo=str(crudo.get("modelo", "")).strip(),
            clave=str(crudo.get("clave", "")).strip(),
            descripcion=str(crudo.get("descripcion", "")).strip(),
            max_tokens=int(crudo.get("max_tokens", 120) or 120),
            temperatura=float(crudo.get("temperatura", 0.6)),
            max_dia=int(crudo.get("max_dia", 200) or 200),
            max_minuto=int(crudo.get("max_minuto", 10) or 10),
            max_tokens_dia=int(crudo.get("max_tokens_dia", 0) or 0),
            max_tokens_minuto=int(crudo.get("max_tokens_minuto", 0) or 0),
            cabeceras=crudo.get("cabeceras") or {},
            parametros=crudo.get("parametros") if isinstance(
                crudo.get("parametros"), dict) else {},
            papel=str(crudo.get("papel", "")).strip(),
        )
    return endpoints
