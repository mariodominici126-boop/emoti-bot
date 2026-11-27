"""Acompañar (26-11-2026): normas positivas, el nombre del robot en Whisper,
español neutro en los textos locales, nada de estados solapados y una cara
que no sonríe mientras alguien cuenta un problema. Sin red."""
import inspect
import re
import unittest
from pathlib import Path
from unittest import mock

from emotibot import identidad as mod_identidad
from emotibot import rutas
from emotibot.ajustes import Ajustes
from emotibot.dialogo import Gestor, Tipo
from emotibot.dialogo import tono
from emotibot.dialogo.seguridad import Guardia, Recursos
from emotibot.ia import disponibilidad as disp
from emotibot.ia.base import Respuesta
from emotibot.identidad import Identidad
from emotibot.rostro import EXPRESIONES
from tests.test_asistente import _AppSimulada


class NormasTest(unittest.TestCase):
    def setUp(self):
        self.identidad = mod_identidad.cargar(rutas.CONFIG_REPO / "identidad.json")
        self.texto = self.identidad.instrucciones()

    def test_normas_positivas_llegan_integras(self):
        for trozo in ("quedarte en lo que la persona acaba de decir",
                      "pregunta por eso mismo, no por otra cosa",
                      "ofrece dos o tres opciones cerradas",
                      "reconoce lo que contó en pocas palabras",
                      "hasta que la persona se haya sentido escuchada",
                      "Como mucho una pregunta por turno",
                      "la mitad de tus respuestas no llevan ninguna",
                      "no interrogar ni hacer terapia"):
            self.assertIn(trozo, self.texto)
        # El tope de reglas de estilo no recorta ninguna en silencio.
        import json
        datos = json.loads((rutas.CONFIG_REPO / "identidad.json").read_text(encoding="utf-8"))
        self.assertEqual(len(self.identidad.estilo), len(datos["estilo"]))
        self.assertEqual(len(self.identidad.normas), len(datos["normas"]))

    def test_no_empuja_a_derivar(self):
        self.assertNotIn("las personas cercanas importan", self.texto)
        self.assertIn("no la derives a nadie salvo que te lo pida", self.texto)
        self.assertIn("Contar un mal día o un problema con alguien no es eso", self.texto)
        # Lo grave sigue orientando fuera, y el límite sigue diciéndose.
        self.assertIn("orienta hacia una persona de confianza o un profesional", self.texto)
        self.assertIn("ni sustituyo relaciones personales", self.texto)

    def test_no_inventa_nombres_y_habla_neutro(self):
        self.assertIn("No llames a la persona por un nombre que no te haya dicho", self.texto)
        self.assertIn("español neutro", self.texto)

    def test_whisper_conoce_el_nombre_del_robot(self):
        """«Emoti» sin pista salía «Polémate», «se mote», «motiz»… La pista va
        SOLO al despertar: en la conversación rompía otras frases (27-11)."""
        from emotibot.stt import whisper_local
        self.assertIn("Emoti", whisper_local.PISTA_NOMBRE)
        fuente = inspect.getsource(whisper_local.WhisperLocal.transcribir)
        self.assertIn("initial_prompt=self.pista", fuente)


class EspanolNeutroTest(unittest.TestCase):
    """Los textos LOCALES que dice o enseña el robot, sin giros de España."""
    ARCHIVOS = ("emotibot/ia/guion.py", "emotibot/dialogo/gestor.py",
                "emotibot/dialogo/actividades/respiracion.py",
                "emotibot/dialogo/actividades/ordenar_ideas.py",
                "emotibot/ia/disponibilidad.py", "emotibot/activacion.py",
                "emotibot/configuracion.py", "emotibot/vista_asistente.py",
                "emotibot/asistente.py", "config/identidad.json")
    PENINSULARES = re.compile(
        r"(?i)apetec|aflojar|bajar revoluciones|mala pata|te he oído|algún sitio|"
        r"\bya está\b|\bguay\b|\bvenga\b|vosotr|\bordenador\b|\bmolar?\b|\bcurro\b")

    def test_ninguno(self):
        for archivo in self.ARCHIVOS:
            texto = (rutas.RAIZ / archivo).read_text(encoding="utf-8")
            if archivo.endswith("identidad.json"):
                # La norma de español neutro las NOMBRA para prohibirlas.
                texto = re.sub(r"Habla en español neutro[^\"]*", "", texto)
            with self.subTest(archivo=archivo):
                self.assertIsNone(self.PENINSULARES.search(texto))


class _Orq:
    ultimo_aviso = None
    ultimo_papel = "conversacion"

    def responder(self, texto, historial=()):
        return Respuesta(texto="Te escucho.", proveedor="conversacion")


def _gestor():
    guardia = Guardia(Recursos(respuesta="Acompañamiento local.",
                               cierre_sin_recursos="Pide ayuda.", verificado=True))
    return Gestor(Ajustes(), Identidad(), _Orq(), guardia)


class CaraDuranteElMalestarTest(unittest.TestCase):
    def test_las_caras_del_malestar_no_sonrien(self):
        for nombre in ("acompanando", "escucha_atenta"):
            self.assertLess(EXPRESIONES[nombre].curva_boca, 0.1, nombre)
        self.assertEqual(EXPRESIONES["escucha_atenta"].color, EXPRESIONES["escuchando"].color,
                         "el ámbar del micrófono abierto se conserva")

    def test_contar_un_problema_pone_la_cara_neutra(self):
        g = _gestor()
        for texto in ("He tenido un mal día y no sé qué hacer.",
                      "Cosas malas con algunas personas.", "No lo sé."):
            with self.subTest(texto=texto):
                self.assertEqual(g.procesar(texto).estado_rostro, "acompanando")
        # Sigue unos turnos neutra, y vuelve a la normal con una buena noticia.
        self.assertEqual(g.procesar("Mi jefe se llama Pedro.").estado_rostro, "acompanando")
        self.assertEqual(g.procesar("Hoy me fue bien en el examen.").estado_rostro, "hablando")

    def test_sin_malestar_nada_cambia(self):
        self.assertEqual(_gestor().procesar("¿Qué opinas de los perros?").estado_rostro,
                         "hablando")
        self.assertEqual(tono.senal("¿Qué opinas de los perros?"), "")

    def test_la_seguridad_no_cambia(self):
        g = _gestor()
        r = g.procesar("ya no quiero vivir")
        self.assertIs(r.tipo, Tipo.SEGURIDAD)
        self.assertNotEqual(r.estado_rostro, "acompanando")


class AplicacionTest(_AppSimulada, unittest.TestCase):
    def _app_lista(self):
        from emotibot import perfil_usuario as pu
        pu.guardar(pu.POR_DEFECTO)
        return self._app()

    def test_hablando_y_procesando_nunca_a_la_vez(self):
        app = self._app_lista()
        app.ocupado = True
        app._estado_ia(disp.PROCESANDO, "", 0)
        self.assertEqual(app.detalle, disp.TEXTO_PROCESANDO)
        from emotibot.dialogo.gestor import Resultado
        resultado = Resultado(texto="Hola.", tipo=Tipo.CONVERSACION, proveedor="conversacion")
        with mock.patch.object(app, "_frases_de", lambda t, m: iter(())):
            app._decir_resultado(resultado)
        self.assertEqual(app.cara.funcional, "hablando")
        self.assertNotEqual(app.detalle, disp.TEXTO_PROCESANDO)
        app._estado_ia(disp.ESPERANDO, disp.MINUTO, 1)
        with mock.patch.object(app, "_frases_de", lambda t, m: iter(())):
            app._decir_resultado(resultado)
        self.assertNotEqual(app.detalle, disp.TEXTO_ESPERANDO)

    def test_escucha_y_reposo_sin_sonrisa_durante_el_malestar(self):
        from emotibot.audio.vad import Fase
        app = self._app_lista()
        disponible = mock.patch.object(app.orquestador, "disponibilidad",
                                       return_value=(disp.DISPONIBLE, "", 0.0))
        disponible.start()
        self.addCleanup(disponible.stop)
        with mock.patch.object(app.orquestador, "responder",
                               lambda t, h=(): Respuesta("Te escucho.", "conversacion")):
            app.gestor.procesar("He tenido un mal día.")
        app._atender("fase", (Fase.EN_VOZ, "Te escucho"))
        self.assertEqual((app.cara.funcional, app.cara.estado), ("escuchando", "escucha_atenta"))
        self.assertTrue(app.cara.microfono_abierto)
        app._liberar()
        self.assertEqual(app.cara.estado, "acompanando")
        app.gestor.limpiar_memoria()
        app._liberar()
        self.assertEqual(app.cara.estado, "reposo")


if __name__ == "__main__":
    unittest.main()
