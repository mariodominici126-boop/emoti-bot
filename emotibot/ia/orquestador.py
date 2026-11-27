"""Selección de proveedor y degradación ordenada.

Principio del proyecto: la disponibilidad de la inteligencia está separada de
la disponibilidad del robot. Aunque no haya claves, ni cuota, ni red,
EMOTI-BOT abre, muestra su rostro, se presenta y ejecuta sus actividades.

Dos modelos con papeles distintos, definidos en `config/proveedores.json`:

- **conversación**: escuchar, acompañar y responder rápido.
- **razonamiento**: comparar, analizar, calcular y decidir.

El enrutador decide cuál va primero con patrones locales, sin gastar una
consulta en preguntarle a un modelo qué modelo usar. Si el elegido no está
disponible, se recorre el resto del orden una sola vez. Nunca se repite la
misma llamada al mismo modelo: eso fue lo que convirtió un fallo transitorio
en doble consumo de cuota y en 45 s de espera en el prototipo.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from .. import registro, rutas
from ..ajustes import Ajustes
from ..identidad import Identidad
from . import disponibilidad as disp
from . import enrutador, longitud, truncado
from .base import Clase, ErrorProveedor, Peticion, Proveedor, Respuesta
from .gemini import ProveedorGemini
from .guion import ProveedorGuion
from .openai_compat import ProveedorOpenAI, cargar_endpoints
from .presupuesto import Presupuesto

log = registro.obtener("ia.orquestador")


class _PlazoAgotado(Exception):
    """Se agotó el plazo del turno con una consulta en curso."""


# Preset «breve» de la configuración: fijo, local, y solo hacia abajo.
FACTOR_BREVE = 0.6
INSTRUCCION_BREVE = "Responde con una o dos frases cortas."

# Tras esperar al límite por minuto tiene que quedar tiempo para la consulta
# (Qwen: p90 de 2,3 s en B4).
MARGEN_TRAS_ESPERA_S = 2.0

_CLASE_DE_CAUSA = {
    disp.PLAZO: Clase.TIEMPO, disp.CUOTA: Clase.CUOTA, disp.MINUTO: Clase.SIN_PRESUPUESTO,
    disp.CONEXION: Clase.RED, disp.CLAVE: Clase.AUTENTICACION,
}


@dataclass
class Aviso:
    """Lo que el usuario debe saber de una degradación, en una frase."""

    texto: str
    clase: Clase


class Orquestador:
    def __init__(
        self,
        config: Ajustes,
        identidad: Identidad,
        obtener_clave,
    ) -> None:
        self.config = config
        self.identidad = identidad
        self.presupuesto = Presupuesto(
            config.ia.presupuesto_diario, config.ia.presupuesto_por_minuto
        )
        self.endpoints = cargar_endpoints(rutas.ARCHIVO_PROVEEDORES)
        self.guion = ProveedorGuion(identidad)
        self.remoto = ProveedorGemini(config.ia, self.presupuesto, obtener_clave)

        self._por_nombre: dict[str, Proveedor] = {
            nombre: ProveedorOpenAI(
                endpoint, self.presupuesto, obtener_clave,
                config.ia.timeout_local_ms if endpoint.es_local
                else config.ia.timeout_remoto_ms,
            )
            for nombre, endpoint in self.endpoints.items()
        }
        self._por_nombre["remoto"] = self.remoto
        self._por_nombre["guion"] = self.guion

        self.longitudes = longitud.cargar()
        self.ultimo_aviso: Aviso | None = None
        # §14.4.1: (estado, causa) del último anuncio, y quién lo escucha
        # (la aplicación): al_estado(estado, causa, segundos), desde el hilo
        # del turno.
        self.ultimo_estado: tuple[str, str] = (disp.DISPONIBLE, "")
        self.al_estado = None
        self.ultimo_proveedor = ""
        self.ultimo_papel = enrutador.CONVERSACION

    # ------------------------------------------------------------------ consulta
    def preparar(self, texto: str, historial=()) -> Peticion:
        """La petición de este turno: instrucciones, historial y tope.

        B5: la longitud va con la ruta de la pregunta, conteste quien
        conteste; sale de config/longitud.json y de ningún sitio más (el
        perfil de usuario no la toca). Sin ese archivo, cada proveedor usa la
        suya. La instrucción de longitud va al final de todo.
        """
        papel = enrutador.papel(texto)
        ruta = self.longitudes.get(papel)
        instrucciones = self.identidad.instrucciones()
        if ruta is not None and ruta.instruccion:
            instrucciones += "\n" + ruta.instruccion
        max_tokens = ruta.max_tokens if ruta is not None else None
        if self.config.ia.longitud_respuesta == "breve":
            # Preset de la configuración: más corto, NUNCA por encima del tope.
            instrucciones += "\n" + INSTRUCCION_BREVE
            if max_tokens:
                max_tokens = min(max_tokens, max(32, round(max_tokens * FACTOR_BREVE)))
        return Peticion(
            texto=texto,
            instrucciones=instrucciones,
            historial=tuple(historial),
            max_tokens=max_tokens,
            papel=papel,
        )

    def responder(self, texto: str, historial=()) -> Respuesta:
        self.ultimo_aviso = None
        peticion = self.preparar(texto, historial)
        self.ultimo_papel = peticion.papel
        # Un proveedor desactivado en la configuración («url» vacía) no es
        # una degradación: no se consulta, no gasta una llamada fallida y no
        # genera aviso. Se retira del orden ANTES de decidir quién va primero,
        # así la pregunta va directa al siguiente proveedor configurado.
        orden = [nombre for nombre in
                 enrutador.ordenar(self.config.ia.orden_proveedores, texto)
                 if not self._desactivado(nombre) and nombre != "guion"]

        # Plazo del TURNO entero (no por proveedor): cada proveedor conserva
        # su timeout como techo individual, y este es el techo del conjunto.
        # Agotado, se deja de probar y contesta lo local, sin esperar a que
        # termine la consulta en curso.
        fin = time.monotonic() + max(0.5, self.config.ia.plazo_turno_ms / 1000.0)
        ultimo_error: ErrorProveedor | None = None
        motivo_degradacion = ""
        clase_degradacion = Clase.NO_DISPONIBLE
        primero = orden[0] if orden else ""
        bloqueos: dict[str, tuple[str, float]] = {}
        errores: list[Clase] = []

        pendientes = orden
        for pasada in (1, 2):
            for nombre in pendientes:
                proveedor = self._por_nombre.get(nombre)
                if proveedor is None:
                    continue
                restante = fin - time.monotonic()
                if restante <= 0:
                    return self._rendirse(peticion, disp.PLAZO)
                if not proveedor.disponible():
                    motivo = getattr(proveedor, "ultimo_motivo", "")
                    bloqueos[nombre] = self._bloqueo(proveedor)
                    log.info("Salto el proveedor %s: %s", nombre,
                             motivo or "no disponible")
                    if not motivo_degradacion:
                        motivo_degradacion = motivo or f"{nombre} no disponible"
                    continue
                bloqueos.pop(nombre, None)
                # PROCESANDO solo aquí: justo antes de una consulta de verdad.
                self._anunciar(disp.PROCESANDO, "")
                try:
                    respuesta = self._con_plazo(nombre, proveedor, peticion, restante)
                except _PlazoAgotado:
                    log.warning("Plazo del turno agotado con %s en curso: dejo de "
                                "probar proveedores y contesto en local.", nombre)
                    return self._rendirse(peticion, disp.PLAZO)
                except ErrorProveedor as exc:
                    ultimo_error = exc
                    errores.append(exc.clase)
                    if exc.clase is Clase.SIN_PRESUPUESTO:
                        bloqueos[nombre] = self._bloqueo(proveedor)
                    log.warning("El proveedor %s falló (%s): %s", nombre,
                                exc.clase.value, exc.detalle[:200])
                    if not motivo_degradacion:
                        motivo_degradacion = exc.mensaje_usuario()
                        clase_degradacion = exc.clase
                    continue
                except Exception as exc:  # un proveedor no debe tumbar el robot
                    log.error("Error inesperado en %s: %s", nombre,
                              registro.resumen_excepcion(exc))
                    ultimo_error = ErrorProveedor(Clase.OTRO, str(exc))
                    errores.append(Clase.OTRO)
                    continue

                if respuesta.truncada:
                    tratada = self._tratar_truncada(nombre, respuesta)
                    if tratada is None:
                        # Sin frase completa que decir: respaldo local, sin otra
                        # llamada (eso duplicaría gasto y espera).
                        self.ultimo_aviso = Aviso(
                            "Se me cortó la respuesta; contesto en modo local.",
                            Clase.TRUNCADA,
                        )
                        self.ultimo_proveedor = self.guion.nombre
                        return self.guion.respuesta_cortada(respuesta)
                    respuesta = tratada

                self.ultimo_proveedor = respuesta.proveedor
                if nombre != primero:
                    self.ultimo_aviso = Aviso(
                        motivo_degradacion or "Estoy respondiendo en modo reducido.",
                        clase_degradacion,
                    )
                return respuesta

            # Nadie contestó. Si alguno solo está frenado por el límite por
            # minuto y vuelve a caber DENTRO del plazo (con margen para la
            # consulta), se espera de verdad —ESPERANDO— y se reintentan solo
            # los frenados. Una vez por turno.
            temporales = sorted((espera, nombre) for nombre, (tipo, espera)
                                in bloqueos.items() if tipo in ("minuto", "pausa"))
            if pasada == 2 or not temporales:
                break
            espera = temporales[0][0]
            if espera + MARGEN_TRAS_ESPERA_S > fin - time.monotonic():
                break
            self._anunciar(disp.ESPERANDO, disp.MINUTO, espera)
            time.sleep(espera + 0.05)
            pendientes = [n for n in orden if n in dict((b, a) for a, b in temporales)]

        log.warning("Ningún proveedor contestó; uso el guion local.")
        if ultimo_error is not None:
            log.info("Último error de la cadena: %s", ultimo_error.clase.value)
        causa = self._causa(bloqueos, errores)
        # La clase del primer fallo real se conserva (diagnóstico); el texto,
        # fijo por causa.
        return self._rendirse(peticion, causa,
                              clase_degradacion if errores and causa == disp.CONEXION
                              else None)

    # ------------------------------------------------------- estados (§14.4.1)
    def _anunciar(self, estado: str, causa: str, segundos: float = 0.0) -> None:
        self.ultimo_estado = (estado, causa)
        if self.al_estado is not None:
            try:
                self.al_estado(estado, causa, segundos)
            except Exception as exc:          # la interfaz no tumba el turno
                log.warning("Aviso de estado fallido: %s", exc)

    def _rendirse(self, peticion: Peticion, causa: str,
                  clase: Clase | None = None) -> Respuesta:
        """NO DISPONIBLE: solo queda lo local. Texto fijo, nunca de un modelo."""
        self.ultimo_aviso = Aviso(disp.TEXTOS_PANTALLA[causa],
                                  clase or _CLASE_DE_CAUSA[causa])
        self._anunciar(disp.NO_DISPONIBLE, causa)
        self.ultimo_proveedor = self.guion.nombre
        return self.guion.responder(peticion)

    def _con_plazo(self, nombre: str, proveedor, peticion: Peticion,
                   segundos: float) -> Respuesta:
        """La consulta en un hilo propio, esperada como mucho `segundos`. Si no
        ha vuelto, se abandona: su propio timeout la acabará cerrando y lo
        que devuelva se descarta (el presupuesto lo concilia el proveedor)."""
        caja: dict[str, object] = {}

        def consultar() -> None:
            try:
                caja["respuesta"] = proveedor.responder(peticion)
            except BaseException as exc:      # se relanza en este hilo
                caja["error"] = exc

        hilo = threading.Thread(target=consultar, name=f"ia-{nombre}", daemon=True)
        hilo.start()
        hilo.join(max(0.0, segundos))
        if hilo.is_alive():
            raise _PlazoAgotado(nombre)
        if "error" in caja:
            raise caja["error"]               # type: ignore[misc]
        return caja["respuesta"]              # type: ignore[return-value]

    def _bloqueo(self, proveedor) -> tuple[str, float]:
        """Por qué no está disponible: el tipo de freno del presupuesto
        («minuto», «pausa», «dia») o, si no es el presupuesto, «clave» u
        «otro»."""
        modelo = getattr(proveedor, "modelo", None)
        if modelo:
            maximo = getattr(getattr(proveedor, "endpoint", None), "max_tokens", 0) or 0
            tipo, espera = self.presupuesto.bloqueo(modelo, maximo)
            if tipo:
                return tipo, espera
        motivo = (getattr(proveedor, "ultimo_motivo", "") or "").lower()
        return ("clave" if "clave" in motivo else "otro"), 0.0

    @staticmethod
    def _causa(bloqueos: dict[str, tuple[str, float]], errores: list[Clase]) -> str:
        tipos = {tipo for tipo, _ in bloqueos.values()}
        if tipos & {"minuto", "pausa"}:
            return disp.MINUTO                # vuelve sola en seguida
        if "dia" in tipos or Clase.CUOTA in errores:
            return disp.CUOTA
        if Clase.AUTENTICACION in errores:
            return disp.CLAVE
        if errores:
            return disp.CONEXION
        if "clave" in tipos:
            return disp.CLAVE
        return disp.CONEXION

    def disponibilidad(self) -> tuple[str, str, float]:
        """Cómo está la inteligencia AHORA, sin consultar a nadie ni salir a
        la red (solo presupuesto y claves): (estado, causa, segundos).
        DISPONIBLE si algún proveedor remoto cabe; ESPERANDO si alguno vuelve
        solo en seguida; NO_DISPONIBLE si no. Los servidores locales no se
        cuentan: comprobarlos sería salir a la red."""
        bloqueos: dict[str, tuple[str, float]] = {}
        for nombre in self.config.ia.orden_proveedores:
            proveedor = self._por_nombre.get(nombre)
            endpoint = getattr(proveedor, "endpoint", None)
            if (proveedor is None or nombre in ("guion", "local") or self._desactivado(nombre)
                    or getattr(endpoint, "es_local", False)):
                continue
            if proveedor.disponible():
                return disp.DISPONIBLE, "", 0.0
            bloqueos[nombre] = self._bloqueo(proveedor)
        if not bloqueos:
            return disp.DISPONIBLE, "", 0.0
        causa = self._causa(bloqueos, [])
        if causa == disp.MINUTO:
            return disp.ESPERANDO, causa, min(e for t, e in bloqueos.values()
                                              if t in ("minuto", "pausa"))
        return disp.NO_DISPONIBLE, causa, 0.0

    def _desactivado(self, nombre: str) -> bool:
        """¿Está apagado a propósito en config/proveedores.json (sin url)?"""
        endpoint = getattr(self._por_nombre.get(nombre), "endpoint", None)
        return endpoint is not None and not endpoint.configurado

    def _tratar_truncada(self, nombre: str, respuesta: Respuesta) -> Respuesta | None:
        """A2: cuenta la truncada y aplica la política (provisional, §13.8a).

        El registro lleva proveedor, modelo y longitud, nunca el texto.
        """
        self.presupuesto.registrar_truncada(respuesta.modelo or nombre)
        tratada = truncado.aplicar(respuesta, self.config.ia.politica_truncado)
        if tratada is None:
            log.warning("Respuesta truncada de %s (%s) sin frase completa "
                        "(%d caracteres): uso el respaldo local.", nombre,
                        respuesta.modelo, len(respuesta.texto))
        elif tratada.recortada:
            log.info("Respuesta truncada de %s (%s): recortada a la última "
                     "frase completa (%d → %d caracteres).", nombre,
                     respuesta.modelo, len(respuesta.texto), len(tratada.texto))
        else:
            log.info("Respuesta truncada de %s (%s) pronunciada tal cual "
                     "(política %s).", nombre, respuesta.modelo,
                     self.config.ia.politica_truncado)
        return tratada

    # -------------------------------------------------------------------- estado
    def estado_corto(self) -> str:
        """Qué proveedor contestaría ahora mismo, o por qué ninguno."""
        for nombre in self.config.ia.orden_proveedores:
            proveedor = self._por_nombre.get(nombre)
            if proveedor is None or nombre == "guion":
                continue
            if proveedor.disponible():
                modelo = getattr(proveedor, "modelo", "")
                return f"{nombre} · {self.presupuesto.resumen(modelo)}"
        primero = self.config.ia.orden_proveedores[0] \
            if self.config.ia.orden_proveedores else ""
        motivo = getattr(self._por_nombre.get(primero), "ultimo_motivo", "")
        return f"modo sin conexión · {motivo or 'sin proveedores'}"

    def claves_pendientes(self) -> list[str]:
        """Nombres de clave que algún proveedor configurado necesita y no tiene."""
        pendientes: list[str] = []
        for nombre in self.config.ia.orden_proveedores:
            proveedor = self._por_nombre.get(nombre)
            endpoint = getattr(proveedor, "endpoint", None)
            if endpoint is None or not endpoint.configurado:
                continue
            if endpoint.necesita_clave and not proveedor.disponible() \
                    and endpoint.clave not in pendientes:
                pendientes.append(endpoint.clave)
        if not self.remoto.disponible() and "gemini" not in pendientes:
            pendientes.append("gemini")
        return pendientes

    def liberar_remoto(self) -> None:
        for proveedor in self._por_nombre.values():
            modelo = getattr(proveedor, "modelo", "")
            if modelo:
                self.presupuesto.liberar(modelo)
