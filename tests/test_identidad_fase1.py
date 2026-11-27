"""Fase 1, A4: la presentación dice la verdad sobre lo que el robot hace.

Las cinco preguntas de aceptación se recorren por el gestor con el guion
local como proveedor, es decir, en el caso más exigente: sin conexión, sin
modelo que pueda matizar nada.
"""
import json
import unittest
from pathlib import Path

from emotibot import identidad as mod_identidad
from emotibot.ajustes import Ajustes
from emotibot.dialogo import Gestor
from emotibot.dialogo.seguridad import Guardia, Recursos
from emotibot.ia.base import Peticion
from emotibot.ia.guion import ProveedorGuion
from emotibot.texto import normalizar

RAIZ = Path(__file__).resolve().parent.parent
PREGUNTAS = ("¿Quién eres?", "¿Qué puedes hacer?", "¿Quién te creó?",
             "¿Puedes monitorear mi salud?", "¿Qué limitaciones tienes?")


class _OrquestadorGuion:
    """El orquestador sin conexión: todo lo contesta el guion local."""

    ultimo_aviso = None

    def __init__(self, identidad):
        self.guion = ProveedorGuion(identidad)

    def responder(self, texto, historial=()):
        return self.guion.responder(Peticion(texto=texto, instrucciones=""))


def _respuestas() -> dict[str, str]:
    identidad = mod_identidad.cargar()
    gestor = Gestor(Ajustes(), identidad, _OrquestadorGuion(identidad),
                    Guardia(Recursos(respuesta="r", cierre_sin_recursos="c",
                                     verificado=True)))
    return {p: gestor.procesar(p).texto for p in PREGUNTAS}


class IdentidadTest(unittest.TestCase):
    def setUp(self):
        self.archivo = json.loads(
            (RAIZ / "config/identidad.json").read_text(encoding="utf-8"))
        self.identidad = mod_identidad.cargar()

    def test_la_presentacion_no_afirma_monitoreo_de_salud(self):
        plano = normalizar(self.archivo["presentacion"])
        self.assertNotIn("monitore", plano)
        self.assertNotIn("salud", plano)

    def test_conserva_la_autoria_configurada(self):
        self.assertEqual(self.archivo["creador"], "el grupo Emoti")
        self.assertIn("el grupo Emoti", self.archivo["presentacion"])

    def test_conserva_el_acompanamiento_y_los_limites_medicos(self):
        self.assertIn("acompañante", self.archivo["presentacion"])
        limites = self.archivo["limites"]
        self.assertIn("No realizo diagnósticos", limites)
        self.assertIn("No monitoreo la salud", limites)

    def test_los_limites_llegan_a_las_instrucciones_del_modelo(self):
        self.assertIn("No monitoreo la salud", self.identidad.instrucciones())

    def test_caben_en_los_limites_del_cargador(self):
        """Lo que pasa de 700 caracteres o de 14 reglas se corta en silencio."""
        for campo in ("presentacion", "proposito", "limites", "aclaracion_modelo"):
            self.assertLessEqual(len(self.archivo[campo]), 700, campo)
        self.assertLessEqual(len(self.archivo["estilo"]), 14)
        self.assertEqual(len(self.identidad.estilo), len(self.archivo["estilo"]))


class ReglasDeConversacionTest(unittest.TestCase):
    """22-11: el robot se fijaba en la respiración y metía frases de relleno.

    Es comportamiento del modelo y no se puede probar sin consultarlo; lo que
    se comprueba aquí es que las reglas llegan ÍNTEGRAS a las instrucciones,
    sin que el límite de 14 reglas las recorte en silencio.
    """

    def setUp(self):
        self.instrucciones = mod_identidad.cargar().instrucciones()

    def test_no_proponer_actividad_en_cada_turno(self):
        # 26-11: además, no antes de que la persona se haya sentido escuchada.
        self.assertIn("hasta que la persona se haya sentido escuchada", self.instrucciones)
        self.assertIn("sin repetir la oferta", self.instrucciones)

    def test_pregunta_abierta_se_contesta_conversando(self):
        self.assertIn("¿y entonces qué hago?", self.instrucciones)
        self.assertIn("No respondas con las instrucciones de un ejercicio",
                      self.instrucciones)

    def test_sin_relleno_generico(self):
        self.assertIn("a veces el día se puede tornar así", self.instrucciones)

    def test_se_conservan_las_reglas_anteriores(self):
        for fragmento in ("Una o dos frases", "Entiendo",
                          "listas", "SOLO la parte", "no lo sabes",
                          "recuerdos entre sesiones", "funciones futuras"):
            with self.subTest(fragmento=fragmento):
                self.assertIn(fragmento, self.instrucciones)


class CincoPreguntasSinConexionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = _respuestas()

    def test_ninguna_respuesta_afirma_monitorear(self):
        for pregunta, texto in self.r.items():
            plano = normalizar(texto)
            with self.subTest(pregunta=pregunta):
                if "monitore" in plano:
                    self.assertTrue(plano.startswith("no") or "no monitore" in plano,
                                    "solo puede mencionarlo para negarlo")

    def test_quien_eres(self):
        self.assertIn("Emoti-Bot", self.r["¿Quién eres?"])

    def test_que_puedes_hacer(self):
        texto = normalizar(self.r["¿Qué puedes hacer?"])
        self.assertIn("respiracion", texto)
        self.assertIn("ordenar ideas", texto)

    def test_quien_te_creo(self):
        self.assertIn("el grupo Emoti", self.r["¿Quién te creó?"])

    def test_puedes_monitorear_mi_salud(self):
        texto = self.r["¿Puedes monitorear mi salud?"]
        self.assertTrue(texto.startswith("No."), texto)
        self.assertIn("profesional", texto)

    def test_que_limitaciones_tienes(self):
        texto = self.r["¿Qué limitaciones tienes?"]
        self.assertIn("no una persona", texto)
        self.assertIn("No monitoreo la salud", texto)

    def test_son_breves(self):
        for pregunta, texto in self.r.items():
            with self.subTest(pregunta=pregunta):
                self.assertLess(len(texto.split()), 70)


if __name__ == "__main__":
    unittest.main()
