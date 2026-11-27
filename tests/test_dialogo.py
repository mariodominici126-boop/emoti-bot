"""Gestor de diálogo: orden de decisión y aislamiento de la ruta de seguridad."""
import unittest

from emotibot.ajustes import Ajustes
from emotibot.dialogo import Gestor, Tipo
from emotibot.dialogo.intencion import Intencion, detectar
from emotibot.dialogo.seguridad import Guardia, Recursos
from emotibot.identidad import Identidad
from emotibot.ia.base import Respuesta


class OrquestadorFalso:
    def __init__(self):
        self.llamadas = []
        self.ultimo_aviso = None

    def responder(self, texto, historial=()):
        self.llamadas.append(texto)
        return Respuesta(texto="respuesta del modelo", proveedor="remoto")


def gestor_de_prueba():
    orquestador = OrquestadorFalso()
    guardia = Guardia(Recursos(
        respuesta="Acompañamiento local.",
        cierre_sin_recursos="Pide ayuda a alguien cercano.",
        verificado=True,
    ))
    gestor = Gestor(Ajustes(), Identidad(), orquestador, guardia)
    return gestor, orquestador


class IntencionTest(unittest.TestCase):
    def test_detecta_intenciones_locales(self):
        casos = {
            "¿quién eres?": Intencion.IDENTIDAD,
            "¿qué puedes hacer?": Intencion.CAPACIDADES,
            "ayúdame a respirar": Intencion.RESPIRACION,
            "quiero ordenar mis ideas": Intencion.ORDENAR_IDEAS,
            "adiós": Intencion.DESPEDIDA,
            "para": Intencion.DETENER,
            "cuéntame algo sobre los planetas": Intencion.CONVERSACION,
        }
        for texto, esperada in casos.items():
            with self.subTest(texto=texto):
                self.assertIs(detectar(texto), esperada)


class GestorTest(unittest.TestCase):
    def test_seguridad_va_primero_y_no_llama_al_modelo(self):
        gestor, orquestador = gestor_de_prueba()
        resultado = gestor.procesar("ya no quiero vivir")
        self.assertIs(resultado.tipo, Tipo.SEGURIDAD)
        self.assertEqual(orquestador.llamadas, [],
                         "la ruta de seguridad no debe consultar al modelo")

    def test_seguridad_no_entra_en_la_memoria(self):
        gestor, _ = gestor_de_prueba()
        gestor.procesar("me quiero morir")
        self.assertEqual(len(gestor.memoria), 0,
                         "ese turno no debe viajar al proveedor después")

    def test_identidad_la_contesta_el_proveedor(self):
        """La identidad va en las instrucciones, no en un texto fijo.

        Así el robot puede contestar solo la parte que corresponde a la
        pregunta en lugar de recitar siempre la presentación entera.
        """
        gestor, orquestador = gestor_de_prueba()
        resultado = gestor.procesar("¿quién eres?")
        self.assertIs(resultado.tipo, Tipo.CONVERSACION)
        self.assertEqual(len(orquestador.llamadas), 1)

    def test_sin_proveedor_el_guion_da_el_fragmento(self):
        """Sin conexión, la identidad sigue contestándose en el dispositivo."""
        from emotibot.ia.base import Peticion
        from emotibot.ia.guion import ProveedorGuion

        guion = ProveedorGuion(Identidad())
        respuesta = guion.responder(
            Peticion(texto="¿cómo te llamas?", instrucciones="")
        )
        self.assertIn("EMOTI-BOT", respuesta.texto)
        self.assertLess(len(respuesta.texto), 60,
                        "debe ser el fragmento, no la presentación entera")

    def test_conversacion_si_llega_al_modelo_y_se_recuerda(self):
        gestor, orquestador = gestor_de_prueba()
        resultado = gestor.procesar("cuéntame algo sobre el mar")
        self.assertIs(resultado.tipo, Tipo.CONVERSACION)
        self.assertEqual(len(orquestador.llamadas), 1)
        self.assertEqual(len(gestor.memoria), 1)

    def test_respiracion_arranca_como_actividad_local(self):
        gestor, orquestador = gestor_de_prueba()
        resultado = gestor.procesar("necesito calmarme")
        self.assertIs(resultado.tipo, Tipo.ACTIVIDAD)
        self.assertEqual(orquestador.llamadas, [])
        self.assertIsNotNone(gestor.actividad)

    def test_ordenar_ideas_recorre_tres_preguntas(self):
        gestor, _ = gestor_de_prueba()
        gestor.iniciar_actividad("ordenar_ideas")
        vistos = 1
        for respuesta in ("pasó esto", "esto está en mi mano", "llamar mañana"):
            resultado = gestor.procesar(respuesta)
            self.assertIs(resultado.tipo, Tipo.ACTIVIDAD)
            vistos += 1
        self.assertEqual(vistos, 4)
        self.assertIsNone(gestor.actividad)

    def test_detener_cancela_la_actividad(self):
        gestor, _ = gestor_de_prueba()
        gestor.iniciar_actividad("respiracion")
        resultado = gestor.procesar("para")
        self.assertIs(resultado.tipo, Tipo.ACTIVIDAD)
        self.assertIsNone(gestor.actividad)

    def test_memoria_acotada(self):
        gestor, _ = gestor_de_prueba()
        for indice in range(20):
            gestor.procesar(f"dime algo del número {indice}")
        self.assertLessEqual(len(gestor.memoria),
                             Ajustes().dialogo.max_turnos_memoria)


if __name__ == "__main__":
    unittest.main()
