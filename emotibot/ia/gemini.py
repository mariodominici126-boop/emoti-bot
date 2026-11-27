"""Proveedor remoto (Gemini) en modo SOLO TEXTO.

Cuatro correcciones medidas frente al prototipo:

1. SOLO TEXTO. La versión 0.6 enviaba el WAV completo al modelo para que
   hiciera transcripción y razonamiento a la vez. El audio es, con diferencia,
   la parte más costosa de una petición, inflaba la latencia por la subida y
   el prefill multimodal, y ataba la disponibilidad del reconocimiento de voz
   a la del modelo. Aquí el reconocimiento se hace aparte (módulo stt) y a
   este proveedor solo le llega texto. El camino con audio sigue existiendo,
   pero como respaldo explícito en `transcribir()`.

2. CLIENTE REUTILIZADO. Antes se construía un `genai.Client` nuevo dentro de
   cada consulta: conexión y handshake TLS en cada turno. Sobre Wi-Fi en una
   Raspberry eso son cientos de milisegundos por turno, regalados.

3. SIN REINTENTO EN 429. Un 429 no es un fallo pasajero, es un techo. El
   prototipo reenviaba el audio completo a un segundo modelo ante errores
   transitorios, con un caso peor de 25 s + 20 s = 45 s antes de avisar al
   usuario. Aquí los reintentos automáticos del SDK se desactivan y hay un
   solo intento, con su timeout PROPIO (`timeout_gemini_ms`): el SDK lo manda
   al servidor como plazo, y con los 12 s de Groq el servidor cortaba con
   504 a los ~11,6 s.

4. SIN ESQUEMA JSON DOBLE. El prototipo exigía un objeto con `transcripcion`
   y `respuesta`: tokens de salida que nadie escucha y que impiden empezar a
   hablar antes de tener el JSON completo y válido.
"""
from __future__ import annotations

import threading
import time

from .. import registro
from ..ajustes import AjustesIa
from . import tokens
from .base import (FIN_DESCONOCIDO, FIN_TRUNCADA, Clase, ErrorProveedor,
                   Peticion, Respuesta, normalizar_motivo_fin)
from .presupuesto import Presupuesto

log = registro.obtener("ia.gemini")

_clientes: dict[str, object] = {}
_lock_clientes = threading.Lock()


def _motivo_fin(resultado) -> str:
    """A2: `finish_reason` del primer candidato (MAX_TOKENS = truncada)."""
    try:
        candidato = (getattr(resultado, "candidates", None) or [None])[0]
    except (TypeError, IndexError):
        return FIN_DESCONOCIDO
    return normalizar_motivo_fin(getattr(candidato, "finish_reason", None))


def _uso(resultado) -> tuple[int | None, int | None]:
    """A3: tokens de `usage_metadata`; (None, None) si no viene."""
    meta = getattr(resultado, "usage_metadata", None)
    if meta is None:
        return None, None

    def entero(nombre: str) -> int | None:
        valor = getattr(meta, nombre, None)
        try:
            return int(valor) if valor is not None else None
        except (TypeError, ValueError):
            return None

    entrada = entero("prompt_token_count")
    salida = entero("candidates_token_count")
    # Con razonamiento activado, lo pensado también se cobra como salida.
    pensado = entero("thoughts_token_count")
    if pensado:
        salida = (salida or 0) + pensado
    return entrada, salida


def _cargar_sdk():
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:  # pragma: no cover
        raise ErrorProveedor(
            Clase.NO_DISPONIBLE,
            "El paquete google-genai no está instalado (pip install google-genai).",
        ) from exc
    return genai, types


def _cliente(clave: str, timeout_ms: int):
    """Un cliente por clave, reutilizado entre turnos."""
    registro.proteger(clave)
    firma = f"{clave[-6:]}|{timeout_ms}"
    with _lock_clientes:
        existente = _clientes.get(firma)
        if existente is not None:
            return existente
        genai, types = _cargar_sdk()
        opciones = types.HttpOptions(timeout=timeout_ms)
        # Un solo intento: los reintentos ocultos del SDK gastan cuota y
        # alargan la espera sin que el usuario sepa por qué.
        if hasattr(types, "HttpRetryOptions"):
            try:
                opciones.retry_options = types.HttpRetryOptions(attempts=1)
            except Exception:
                log.debug("El SDK no aceptó retry_options; sigo sin tocarlo.")
        cliente = genai.Client(api_key=clave, http_options=opciones)
        _clientes[firma] = cliente
        return cliente


def olvidar_clientes() -> None:
    with _lock_clientes:
        _clientes.clear()


def _config_pensamiento(types):
    """Configuración de razonamiento, solo si se pide explícitamente.

    LECCIÓN APRENDIDA. Antes esto se enviaba siempre, decidiendo por
    introspección de `ThinkingConfig` en el SDK. El error era comprobar lo que
    acepta el SDK en lugar de lo que acepta EL MODELO: un modelo que no admite
    razonamiento devuelve 400 INVALID_ARGUMENT y la conversación entera se
    cae al guion local, sin que el mensaje diga por qué.

    Para una respuesta de una o dos frases, pensar es latencia y consumo sin
    beneficio, así que el valor por defecto es no enviarlo.
    """
    clase = getattr(types, "ThinkingConfig", None)
    if clase is None:
        return None
    campos = set(getattr(clase, "model_fields", {}) or {})
    try:
        if "thinking_level" in campos:
            return clase(thinking_level="low")
        if "thinking_budget" in campos:
            return clase(thinking_budget=0)
    except Exception:
        return None
    return None


def _codigo(exc: BaseException) -> str:
    for atributo in ("code", "status_code"):
        valor = getattr(exc, atributo, None)
        if valor:
            return str(valor).strip()
    return ""


# Huellas de una respuesta de cortafuegos de borde (Cloudflare y similares).
_MARCAS_BORDE = ("error code: 1010", "error code: 1020", "cloudflare",
                 "<html", "<!doctype html", "attention required")


def clasificar(exc: BaseException) -> Clase:
    codigo = _codigo(exc)
    texto = registro.redactar(exc).lower()
    if codigo == "400" or "invalid_argument" in texto:
        return Clase.PETICION
    if codigo == "429" or "resource_exhausted" in texto or "quota" in texto:
        return Clase.CUOTA
    if codigo in ("401", "403") and any(m in texto for m in _MARCAS_BORDE):
        # Texto de un cortafuegos de borde, no un error de la API de Google:
        # la clave no llegó a comprobarse.
        return Clase.BLOQUEO_CLIENTE
    if codigo in ("401", "403") or "api_key_invalid" in texto \
            or "permission_denied" in texto:
        return Clase.AUTENTICACION
    if codigo == "404" or "not found" in texto:
        return Clase.MODELO
    if codigo == "503" or "unavailable" in texto or "overloaded" in texto:
        return Clase.SOBRECARGA
    if codigo in ("504", "408") or "deadline_exceeded" in texto \
            or "timed out" in texto or "timeout" in texto:
        return Clase.TIEMPO
    if isinstance(exc, (ConnectionError, OSError)) or "connection" in texto \
            or "dns" in texto or "network" in texto:
        return Clase.RED
    return Clase.OTRO


def cuerpo_crudo(exc: BaseException, limite: int = 1200) -> str:
    """Texto íntegro y redactado del error, para el script de diagnóstico.

    Un 429 de Gemini nombra la métrica agotada y su valor; es exactamente el
    dato que hacía falta y que nunca se capturó.
    """
    partes = [registro.redactar(exc)]
    for atributo in ("message", "details", "response_json", "body"):
        valor = getattr(exc, atributo, None)
        if valor:
            partes.append(f"{atributo}={registro.redactar(valor)}")
    codigo = _codigo(exc)
    if codigo:
        partes.insert(0, f"HTTP={codigo}")
    return " | ".join(partes)[:limite]


class ProveedorGemini:
    nombre = "remoto"

    def __init__(
        self,
        config: AjustesIa,
        presupuesto: Presupuesto,
        obtener_clave,
    ) -> None:
        self.config = config
        self.presupuesto = presupuesto
        self._obtener_clave = obtener_clave
        self.clave_nombre = "gemini"
        self.modelo = config.modelo_remoto
        self.ultimo_motivo = ""
        # Nivel de configuración que este modelo acepta. Cada modelo admite
        # un juego distinto de opciones y la única forma fiable de saberlo es
        # preguntárselo: si devuelve 400, se baja un nivel y se recuerda.
        self._nivel_config = 0

    def _opciones(self, types, peticion: Peticion, nivel: int) -> dict:
        """Opciones de la petición, de más completas a más conservadoras."""
        opciones: dict = {
            "system_instruction": peticion.instrucciones,
            "max_output_tokens": (peticion.max_tokens
                                  or self.config.max_tokens_respuesta),
        }
        if nivel <= 1:
            opciones["temperature"] = self.config.temperatura
            opciones["response_mime_type"] = "text/plain"
        if nivel <= 0 and (self.config.pensamiento or "off").lower() != "off":
            pensamiento = _config_pensamiento(types)
            if pensamiento is not None:
                opciones["thinking_config"] = pensamiento
        return opciones

    # ------------------------------------------------------------ disponibilidad
    def disponible(self) -> bool:
        if not self._obtener_clave(self.clave_nombre):
            self.ultimo_motivo = "Sin clave API configurada."
            return False
        permitido, motivo = self.presupuesto.puede_consultar(self.modelo)
        self.ultimo_motivo = motivo
        return permitido

    # ------------------------------------------------------------------ consulta
    def _contenido(self, peticion: Peticion) -> list[str]:
        if not peticion.historial:
            return [peticion.texto]
        lineas = ["Turnos previos de esta sesión, solo como contexto:"]
        for turno in peticion.historial:
            lineas.append(f"Persona: {turno.usuario}")
            lineas.append(f"Tú: {turno.robot}")
        lineas.append("Responde únicamente a este mensaje nuevo:")
        lineas.append(peticion.texto)
        return ["\n".join(lineas)]

    def responder(self, peticion: Peticion) -> Respuesta:
        clave = self._obtener_clave(self.clave_nombre)
        if not clave:
            raise ErrorProveedor(Clase.AUTENTICACION, "Sin clave API.")
        # A3: reserva previa, igual que en el proveedor compatible con OpenAI.
        entrada = tokens.estimar_entrada(
            [peticion.instrucciones, *self._contenido(peticion)])
        reserva, motivo = self.presupuesto.reservar(
            self.modelo, entrada + (peticion.max_tokens
                                    or self.config.max_tokens_respuesta),
            entrada_estimada=entrada,
        )
        if reserva is None:
            raise ErrorProveedor(Clase.SIN_PRESUPUESTO, motivo)

        try:
            _, types = _cargar_sdk()
            cliente = _cliente(clave, self.config.timeout_gemini_ms)
        except Exception:
            self.presupuesto.anular(reserva, 0)   # no llegó a salir
            raise

        inicio = time.monotonic()
        try:
            resultado = self._generar(cliente, types, peticion)
        except Exception as exc:
            clase = clasificar(exc)
            if clase is Clase.CUOTA:
                # Punto central: se frena, no se reintenta ni se cambia de
                # modelo con la misma petición.
                self.presupuesto.registrar_rechazo_cuota(self.modelo)
            # Lo que pudo contar el proveedor, con la duda hacia arriba.
            if clase in (Clase.PETICION, Clase.AUTENTICACION, Clase.MODELO,
                         Clase.CUOTA, Clase.RED, Clase.BLOQUEO_CLIENTE):
                contados = 0
            elif clase is Clase.TIEMPO:
                contados = reserva.tokens
            else:
                contados = reserva.entrada_estimada
            self.presupuesto.anular(reserva, contados)
            log.warning("Consulta remota fallida (%s): %s",
                        clase.value, cuerpo_crudo(exc, 400))
            raise ErrorProveedor(clase, cuerpo_crudo(exc)) from exc

        texto = (getattr(resultado, "text", "") or "").strip()
        motivo_fin = _motivo_fin(resultado)
        entrada_real, salida_real = _uso(resultado)
        self.presupuesto.confirmar(reserva, entrada_real, salida_real)
        if not texto and motivo_fin != FIN_TRUNCADA:
            raise ErrorProveedor(Clase.VACIA, "El modelo no devolvió texto.")
        return Respuesta(
            texto=texto,
            proveedor=self.nombre,
            modelo=self.modelo,
            segundos=time.monotonic() - inicio,
            motivo_fin=motivo_fin,
            tokens_entrada=entrada_real,
            tokens_salida=salida_real,
        )

    def _generar(self, cliente, types, peticion: Peticion):
        """Consulta, bajando de nivel si el modelo rechaza las opciones.

        Un 400 INVALID_ARGUMENT no es un fallo pasajero ni un techo de cuota:
        es que este modelo no admite alguna de las opciones. Reintentar lo
        mismo no serviría, pero reintentar con MENOS opciones sí, y una vez
        descubierto el nivel que funciona se recuerda y no se vuelve a probar.

        Esto no contradice la regla de no reintentar: un 429 sigue sin
        reintentarse nunca, y aquí no se repite la misma petición.
        """
        ultimo: Exception | None = None
        intentadas: list[frozenset] = []
        for nivel in range(self._nivel_config, 3):
            opciones = self._opciones(types, peticion, nivel)
            # Dos niveles pueden coincidir —con el razonamiento desactivado,
            # el 0 y el 1 son iguales— y repetir la misma petición sería
            # gastar una consulta para obtener el mismo error.
            firma = frozenset(opciones)
            if firma in intentadas:
                continue
            intentadas.append(firma)
            try:
                resultado = cliente.models.generate_content(
                    model=self.modelo,
                    contents=self._contenido(peticion),
                    config=types.GenerateContentConfig(**opciones),
                )
            except Exception as exc:
                if clasificar(exc) is not Clase.PETICION:
                    raise
                ultimo = exc
                log.warning(
                    "El modelo %s rechazó las opciones del nivel %d (%s). "
                    "Pruebo con menos.", self.modelo, nivel,
                    ", ".join(sorted(opciones)),
                )
                continue
            if nivel != self._nivel_config:
                log.info("El modelo %s funciona con el nivel %d de opciones.",
                         self.modelo, nivel)
                self._nivel_config = nivel
            return resultado
        raise ultimo if ultimo is not None else RuntimeError(
            "No se pudo construir una petición válida."
        )

    # -------------------------------------------------- reconocimiento (respaldo)
    def transcribir(self, wav: bytes, idioma: str = "es") -> str:
        """Reconocimiento remoto, solo como respaldo si no hay STT local.

        Cuesta mucho más que una consulta de texto: se usa cuando no hay otra
        opción, y el presupuesto lo cuenta igual que cualquier consulta.
        """
        clave = self._obtener_clave(self.clave_nombre)
        if not clave:
            raise ErrorProveedor(Clase.AUTENTICACION, "Sin clave API.")
        permitido, motivo = self.presupuesto.puede_consultar(self.modelo)
        if not permitido:
            raise ErrorProveedor(Clase.SIN_PRESUPUESTO, motivo)

        _, types = _cargar_sdk()
        cliente = _cliente(clave, self.config.timeout_gemini_ms)
        instruccion = (
            f"Transcribe literalmente el audio en {idioma}. "
            "Devuelve solo la transcripción, sin comentarios ni comillas. "
            "Si no se entiende nada, devuelve una cadena vacía."
        )
        try:
            resultado = cliente.models.generate_content(
                model=self.modelo,
                contents=[
                    instruccion,
                    types.Part.from_bytes(data=wav, mime_type="audio/wav"),
                ],
                config=types.GenerateContentConfig(
                    temperature=0.0,
                    max_output_tokens=256,
                    response_mime_type="text/plain",
                ),
            )
        except Exception as exc:
            clase = clasificar(exc)
            if clase is Clase.CUOTA:
                self.presupuesto.registrar_rechazo_cuota(self.modelo)
            raise ErrorProveedor(clase, cuerpo_crudo(exc)) from exc

        self.presupuesto.registrar_consulta(self.modelo)
        return (getattr(resultado, "text", "") or "").strip()
