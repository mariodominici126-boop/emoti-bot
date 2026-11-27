"""Gestor de diálogo: decide quién contesta cada turno.

Orden de decisión, y el orden importa:

    1. Guardia de seguridad  (determinista, local, SIEMPRE primero)
    2. Actividad en curso    (local)
    3. Intención local       (identidad, actividades, cortesía)
    4. Orquestador de IA     (remoto → local → guion)

Que la seguridad vaya primero no es un detalle de implementación: significa
que esa ruta no depende de la clave, de la cuota ni de la red, y que el texto
de un turno así nunca llega a un proveedor externo.

La memoria de sesión vive solo en RAM, está acotada y se borra al salir. No
hay base de datos de conversaciones, ni se escribe audio al disco.
"""
from __future__ import annotations

import enum
from collections import deque
from dataclasses import dataclass, field

from .. import registro
from ..ajustes import Ajustes
from ..identidad import Identidad
from ..texto import palabras as contar_palabras
from ..ia import Orquestador, Turno
from . import tono
from .actividades import Actividad, OrdenarIdeas, Paso, Respiracion
from .intencion import Intencion, detectar, respuesta_literal
from . import directorio as mod_directorio
from .seguridad import Guardia

log = registro.obtener("dialogo.gestor")

ACTIVIDADES_APAGADAS = ("Las actividades están desactivadas en la configuración. "
                        "Puedes activarlas en Bienestar.")
ABRO_CONFIGURACION = "Abro la configuración."


class Tipo(enum.Enum):
    CONVERSACION = "conversacion"
    SEGURIDAD = "seguridad"
    ACTIVIDAD = "actividad"
    LOCAL = "local"
    SIN_ENTENDER = "sin_entender"


@dataclass
class Resultado:
    texto: str
    tipo: Tipo
    estado_rostro: str = "hablando"
    espera_s: float = 0.0
    escuchar_despues: bool = False
    proveedor: str = "local"
    aviso: str = ""
    segundos_proveedor: float = 0.0
    pasos_pendientes: tuple[Paso, ...] = field(default_factory=tuple)
    # Fase 1, A2/A3: datos de diagnóstico de la respuesta del proveedor.
    # Solo números y etiquetas, nunca contenido.
    modelo: str = ""
    motivo_fin: str = ""
    recortada: bool = False
    tokens_entrada: int | None = None
    tokens_salida: int | None = None
    # Fase 1, B5: ruta (conversacion/razonamiento) y longitud, como cifras.
    papel: str = ""
    palabras: int = 0
    # Abrir la barra lateral del directorio de ayuda (consulta, no crisis).
    mostrar_directorio: bool = False
    # Abrir la pantalla de configuración (intención local, sin modelo).
    abrir_configuracion: bool = False
    # Despedida: la conversación seguida se acaba aquí.
    fin_conversacion: bool = False


class Gestor:
    def __init__(
        self,
        config: Ajustes,
        identidad: Identidad,
        orquestador: Orquestador,
        guardia: Guardia | None = None,
        directorio: mod_directorio.Directorio | None = None,
    ) -> None:
        self.config = config
        self.identidad = identidad
        self.orquestador = orquestador
        self.guardia = guardia or Guardia()
        self.directorio = directorio or mod_directorio.cargar(config.region.pais)
        self.memoria: deque[Turno] = deque(maxlen=config.dialogo.max_turnos_memoria)
        self.actividad: Actividad | None = None

    # ------------------------------------------------------------------ memoria
    @property
    def en_malestar(self) -> bool:
        """La persona está contando algo que le pesa (solo para la cara)."""
        return getattr(self, "_turnos_malestar", 0) > 0

    def limpiar_memoria(self) -> None:
        cuantos = len(self.memoria)
        self.memoria.clear()
        self._turnos_malestar = 0
        log.info("Memoria de sesión borrada (%d turnos eliminados).", cuantos)

    def cerrar(self) -> None:
        self.memoria.clear()
        self.actividad = None

    # ---------------------------------------------------------------- actividades
    def iniciar_actividad(self, nombre: str) -> Resultado:
        if not getattr(self.config.dialogo, "actividades", True):
            return Resultado(texto=ACTIVIDADES_APAGADAS, tipo=Tipo.LOCAL,
                             estado_rostro="reposo")
        if nombre == Respiracion.nombre:
            from .actividades.respiracion import RITMOS
            self.actividad = Respiracion(ritmo=RITMOS.get(
                getattr(self.config.dialogo, "respiracion_ritmo", "4-4-6"), RITMOS["4-4-6"]))
        elif nombre == OrdenarIdeas.nombre:
            self.actividad = OrdenarIdeas()
        else:
            return Resultado(
                texto="No tengo esa actividad.", tipo=Tipo.LOCAL,
                estado_rostro="reposo",
            )
        paso = self.actividad.iniciar()
        return self._de_paso(paso)

    def cancelar_actividad(self) -> Resultado | None:
        if self.actividad is None:
            return None
        paso = self.actividad.cancelar()
        self.actividad = None
        return self._de_paso(paso)

    def continuar_actividad(self, entrada: str | None = None) -> Resultado | None:
        if self.actividad is None:
            return None
        paso = self.actividad.avanzar(entrada)
        if paso.terminada:
            self.actividad = None
        if not paso.texto and paso.terminada:
            return None
        return self._de_paso(paso)

    @staticmethod
    def _de_paso(paso: Paso) -> Resultado:
        return Resultado(
            texto=paso.texto,
            tipo=Tipo.ACTIVIDAD,
            estado_rostro=paso.estado_rostro,
            espera_s=paso.espera_s,
            escuchar_despues=paso.escuchar_despues,
            proveedor="local",
        )

    # --------------------------------------------------------------------- turno
    def procesar(self, texto: str) -> Resultado:
        limpio = (texto or "").strip()
        # La cara, no el diálogo: mientras cuenta algo que le pesa, no sonríe.
        senal = tono.senal(limpio)
        if senal == "malestar":
            self._turnos_malestar = tono.TURNOS_DE_MALESTAR
        elif senal == "alivio":
            self._turnos_malestar = 0
        else:
            self._turnos_malestar = max(0, getattr(self, "_turnos_malestar", 0) - 1)

        # 1. Seguridad. Antes de todo, sin excepción.
        evaluacion = self.guardia.evaluar(limpio)
        if evaluacion.activada:
            # Una ruta de seguridad interrumpe cualquier actividad y NO entra
            # en la memoria de sesión: así no viaja a ningún proveedor después.
            self.actividad = None
            return Resultado(
                texto=evaluacion.respuesta,
                tipo=Tipo.SEGURIDAD,
                estado_rostro="preocupado",
                proveedor="local",
            )

        if not limpio:
            return Resultado(
                texto="No llegué a entenderte. ¿Lo repites?",
                tipo=Tipo.SIN_ENTENDER,
                estado_rostro="sin_entender",
                proveedor="local",
            )

        # 1b. Directorio de ayuda, si alguien pide los números hablando. Es
        # una consulta, no una crisis: texto fijo con los números de
        # config/crisis.json, sin modelo y sin entrar en la memoria.
        if mod_directorio.pide_directorio(limpio):
            return Resultado(
                texto=self.directorio.respuesta_hablada(self.directorio.hora()),
                tipo=Tipo.LOCAL, estado_rostro="hablando", proveedor="local",
                mostrar_directorio=True,
            )

        literal = respuesta_literal(limpio)
        if literal is not None:
            return Resultado(
                texto=literal, tipo=Tipo.LOCAL, estado_rostro="feliz",
                proveedor="local",
            )

        intencion = detectar(limpio)

        # 2. Actividad en curso.
        if self.actividad is not None and self.actividad.activa:
            if intencion is Intencion.DETENER:
                resultado = self.cancelar_actividad()
                return resultado or Resultado("", Tipo.LOCAL)
            continuacion = self.continuar_actividad(limpio)
            if continuacion is not None:
                return continuacion

        # 3. Intenciones que se resuelven en el dispositivo, sin gastar cuota.
        if intencion is Intencion.CONFIGURACION:
            return Resultado(texto=ABRO_CONFIGURACION, tipo=Tipo.LOCAL,
                             estado_rostro="reposo", abrir_configuracion=True)
        if intencion is Intencion.CAPACIDADES:
            return Resultado(
                texto=(
                    "Puedo conversar contigo, guiarte una respiración corta y "
                    "ayudarte a ordenar ideas con tres preguntas. Las dos "
                    "actividades funcionan aunque me quede sin conexión. "
                    "¿Quieres probar alguna?"
                ),
                tipo=Tipo.LOCAL, estado_rostro="reposo", proveedor="local",
            )
        if intencion is Intencion.RESPIRACION:
            return self.iniciar_actividad(Respiracion.nombre)
        if intencion is Intencion.ORDENAR_IDEAS:
            return self.iniciar_actividad(OrdenarIdeas.nombre)
        if intencion is Intencion.DESPEDIDA:
            return Resultado(
                texto="Me alegró acompañarte. Aquí estoy cuando quieras.",
                tipo=Tipo.LOCAL, estado_rostro="feliz", proveedor="local",
                fin_conversacion=True,
            )

        # 4. Conversación e identidad: al orquestador.
        #
        # Las preguntas sobre quién es NO se responden con un texto fijo: el
        # orquestador recibe la identidad en las instrucciones y contesta solo
        # la parte que corresponde a la pregunta. Si no hay proveedor, el
        # guion local hace lo mismo con fragmentos escritos a mano.
        respuesta = self.orquestador.responder(limpio, tuple(self.memoria))
        texto = respuesta.texto
        # Ningún modelo da, completa ni corrige un número de ayuda: si su
        # respuesta trae algo con forma de teléfono, se sustituye entera por
        # la remisión al directorio, que sí los tiene de config/crisis.json.
        remitir = mod_directorio.contiene_telefono(texto, self.directorio.numeros())
        if remitir:
            log.warning("La respuesta del modelo traía un número de teléfono: se "
                        "sustituye por la remisión al directorio.")
            texto = mod_directorio.REMISION
        self.memoria.append(Turno(usuario=limpio, robot=texto))
        aviso = self.orquestador.ultimo_aviso
        return Resultado(
            mostrar_directorio=remitir,
            texto=texto,
            tipo=Tipo.CONVERSACION,
            estado_rostro="acompanando" if self.en_malestar else "hablando",
            proveedor=respuesta.proveedor,
            aviso=aviso.texto if aviso else "",
            segundos_proveedor=respuesta.segundos,
            modelo=respuesta.modelo,
            motivo_fin=respuesta.motivo_fin,
            recortada=respuesta.recortada,
            tokens_entrada=respuesta.tokens_entrada,
            tokens_salida=respuesta.tokens_salida,
            papel=getattr(self.orquestador, "ultimo_papel", "") or "",
            palabras=contar_palabras(respuesta.texto),
        )

