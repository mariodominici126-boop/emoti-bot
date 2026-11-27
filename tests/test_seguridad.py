"""La ruta de seguridad: debe activarse cuando toca y callarse cuando no."""
import unittest

from emotibot.dialogo.seguridad import Guardia, Recursos

ACTIVAN = (
    "ya no quiero vivir",
    "me quiero morir",
    "estoy pensando en quitarme la vida",
    "creo que voy a suicidarme",
    "tengo ganas de morirme",
    "quiero hacerme daño",
    "a veces pienso en matarme",
    "no quiero seguir viviendo así",
)

NO_ACTIVAN = (
    "me muero de risa con lo que pasó hoy",
    "esto me mata, llevo tres horas con el código",
    "estoy muerto de cansancio",
    "me muero de hambre, no almorcé",
    "me matan los pies de tanto caminar",
    "solo quiero matar el tiempo hasta la clase",
    "esa película es de morirse de buena",
    "estoy muy triste por lo de mi abuela",
    "tuve un día horrible y estoy agotado",
    "me siento solo últimamente",
    "tengo mucha ansiedad por el examen",
)


class GuardiaTest(unittest.TestCase):
    def setUp(self):
        self.guardia = Guardia(Recursos(
            respuesta="Texto de acompañamiento.",
            telefono_emergencias="911",
            cierre_con_emergencias="Llama al {emergencias}.",
            cierre_sin_recursos="Pide ayuda a alguien cercano.",
            verificado=True,
        ))

    def test_activa_con_intencion_explicita(self):
        for frase in ACTIVAN:
            with self.subTest(frase=frase):
                evaluacion = self.guardia.evaluar(frase)
                self.assertTrue(evaluacion.activada, f"debía activar: {frase}")
                self.assertIn("911", evaluacion.respuesta)

    def test_no_activa_con_modismos_ni_tristeza_normal(self):
        for frase in NO_ACTIVAN:
            with self.subTest(frase=frase):
                self.assertFalse(
                    self.guardia.evaluar(frase).activada,
                    f"NO debía activar: {frase}",
                )

    def test_funciona_sin_recursos_configurados(self):
        guardia = Guardia(Recursos(
            respuesta="Acompañamiento.",
            cierre_sin_recursos="Pide ayuda a alguien cercano.",
        ))
        evaluacion = guardia.evaluar("ya no quiero vivir")
        self.assertTrue(evaluacion.activada)
        self.assertIn("alguien cercano", evaluacion.respuesta)

    def test_advierte_si_no_esta_verificado(self):
        guardia = Guardia(Recursos(respuesta="x", verificado=False))
        avisos = guardia.advertencias_arranque()
        self.assertTrue(any("verificado" in a for a in avisos))

    def test_texto_vacio_no_activa(self):
        self.assertFalse(self.guardia.evaluar("").activada)
        self.assertFalse(self.guardia.evaluar("   ").activada)


if __name__ == "__main__":
    unittest.main()
