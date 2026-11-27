"""Respuestas locales deterministas, sin ningún modelo de IA.

Esta es la pieza que convierte a EMOTI-BOT en un robot que FUNCIONA cuando no
hay cuota ni Internet, en lugar de una carcasa que muestra un error. No
pretende conversar: cubre identidad, cortesía, orientación y derivación a las
actividades locales, que es lo que una persona espera que siga funcionando.

Todo lo de aquí está escrito a mano, se pronuncia tal cual y no sale del
dispositivo.
"""
from __future__ import annotations

import random
import time

from ..identidad import Identidad
from ..texto import normalizar
from .base import FIN_COMPLETA, Peticion, Respuesta


_SALUDOS = ("hola", "buenas", "buenos dias", "buenas tardes", "buenas noches",
            "que tal", "saludos", "hey")
# Fragmentos de identidad: cada tipo de pregunta recibe solo la parte que la
# contesta, no la presentación entera. Se recorren en orden, de lo más
# específico a lo más general.
_NOMBRE = ("como te llamas", "cual es tu nombre", "tu nombre", "como se llama")
_AUTORIA = ("quien te creo", "quien te hizo", "quien te diseno", "quien te programo",
            "tu creador", "quien te fabrico", "de quien eres", "quien te desarrollo")
_NATURALEZA = ("que eres", "eres humano", "eres una persona", "eres real",
               "eres un robot", "eres una maquina")
_DESARROLLO = ("estas terminado", "ya estas listo", "estas completo",
               "estas en desarrollo", "te falta algo")
_DESPEDIDAS = ("adios", "hasta luego", "nos vemos", "chao", "me voy",
               "hasta manana", "buenas noches me voy")
_GRACIAS = ("gracias", "te lo agradezco", "muy amable")
_IDENTIDAD = ("quien eres", "como te llamas", "tu nombre", "presentate",
              "quien te creo", "quien te hizo", "tu creador", "que eres")
_CAPACIDADES = ("que puedes hacer", "que sabes hacer", "en que me puedes ayudar",
                "para que sirves", "que haces", "ayudame")
_ESTADO = ("como estas", "como te sientes", "como va todo")
# Fase 1, A4: sin conexión también hay que contestar la verdad a esto.
_SALUD = ("monitorear", "monitorea", "monitoreo", "monitorizar", "mi salud",
          "signos vitales", "constantes vitales", "presion arterial",
          "ritmo cardiaco", "frecuencia cardiaca", "diagnostic")
_LIMITACIONES = ("limitaciones", "tus limites", "que no puedes hacer",
                 "que no sabes hacer", "que no haces")

_ACOMPANAMIENTO = (
    "Te escucho. Ahora mismo no tengo conexión con mi parte de inteligencia, "
    "así que no puedo conversar con soltura, pero sí puedo acompañarte con un "
    "ejercicio de respiración o ayudarte a ordenar lo que tienes en la cabeza.",
    "Estoy aquí, aunque sin conexión no puedo seguir una conversación larga. "
    "Si quieres, hacemos una respiración corta, o te ayudo a poner en orden lo "
    "que te preocupa paso a paso.",
    "Te escuché. Sin conexión me quedo corto para charlar, pero las "
    "actividades funcionan igual: dime si prefieres respirar un momento o "
    "ordenar ideas.",
)


class ProveedorGuion:
    """Último recurso: siempre disponible, nunca falla, nunca usa la red."""

    nombre = "guion"

    def __init__(self, identidad: Identidad, con_conexion_fallida: bool = True) -> None:
        self.identidad = identidad
        self.con_conexion_fallida = con_conexion_fallida
        self._aleatorio = random.Random()

    def disponible(self) -> bool:
        return True

    def responder(self, peticion: Peticion) -> Respuesta:
        inicio = time.monotonic()
        texto = self._elegir(normalizar(peticion.texto))
        return Respuesta(
            texto=texto,
            proveedor=self.nombre,
            modelo="local",
            segundos=time.monotonic() - inicio,
            motivo_fin=FIN_COMPLETA,   # escrito a mano: nunca se trunca
        )

    def respuesta_cortada(self, original: Respuesta | None = None) -> Respuesta:
        """Respaldo local para una respuesta truncada sin frase completa (A2).

        Dice la verdad —se cortó— en lugar de fingir falta de conexión, y no
        repite nada de lo que el modelo llegó a generar.
        """
        return Respuesta(
            texto=("Se me cortó la respuesta antes de terminarla. ¿Me lo "
                   "preguntas otra vez, quizá un poco más concreto?"),
            proveedor=self.nombre,
            modelo="local",
            segundos=0.0,
            motivo_fin=FIN_COMPLETA,
        )

    def _elegir(self, plano: str) -> str:
        def contiene(claves) -> bool:
            return any(clave in plano for clave in claves)

        if not plano.strip():
            return ("No llegué a entender lo que dijiste. ¿Lo repites un poco "
                    "más cerca?")
        if contiene(_NOMBRE):
            return f"Me llamo {self.identidad.nombre}."
        if contiene(_AUTORIA):
            return (f"Me diseña {self.identidad.creador}. "
                    "El modelo de inteligencia artificial que uso lo "
                    "desarrolla otra empresa.")
        if contiene(_NATURALEZA):
            return ("Soy un robot acompañante con inteligencia artificial, no "
                    "una persona. Todavía estoy en desarrollo.")
        if contiene(_DESARROLLO):
            return ("Todavía estoy en desarrollo, así que aún no hago todo lo "
                    "que pretendo hacer.")
        if contiene(_SALUD):
            return ("No. No monitoreo la salud: no tengo sensores ni mido "
                    "constantes vitales, y no hago diagnósticos. Para eso lo "
                    "indicado es un profesional de salud. Lo que sí puedo es "
                    "conversar contigo o guiarte una respiración corta.")
        if contiene(_LIMITACIONES):
            return self.identidad.limites
        if contiene(_IDENTIDAD):
            return self.identidad.presentacion
        if contiene(_CAPACIDADES):
            return (
                "Puedo conversar cuando tengo conexión, guiarte en una "
                "respiración corta, y ayudarte a ordenar ideas con tres "
                "preguntas sencillas. Las dos actividades funcionan sin "
                "Internet. ¿Quieres probar una?"
            )
        if contiene(_DESPEDIDAS):
            return "Me alegró acompañarte. Cuando quieras, aquí estoy."
        if contiene(_GRACIAS):
            return "Con gusto."
        if contiene(_SALUDOS):
            return (f"Hola. Soy {self.identidad.nombre}. ¿Cómo va tu día?")
        if contiene(_ESTADO):
            return (
                "Soy un programa, así que no tengo estados de ánimo, pero "
                "funciono bien. Cuéntame cómo va lo tuyo."
            )
        return self._aleatorio.choice(_ACOMPANAMIENTO)
