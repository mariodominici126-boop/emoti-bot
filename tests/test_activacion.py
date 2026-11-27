"""Activación por voz («Hola Emoti»), sin micrófono ni red."""
import threading
import time
import unittest
from unittest import mock

from emotibot import activacion as mod
from emotibot.audio.captura import Captura, MotivoFin
from emotibot.stt.base import Transcripcion
from tests.test_asistente import _AppSimulada


def _captura(util=1.2, motivo=MotivoFin.SILENCIO, pcm=b"\x01\x00" * 800):
    return Captura(pcm=pcm, frecuencia=16000, motivo=motivo, duracion_bruta_s=util + 1,
                   duracion_util_s=util, t_primera_voz=0.5, instante_ultima_voz=0.0)


class _Mic:
    """escuchar() devuelve las capturas dadas; sin capturas, se queda
    «escuchando» hasta que lo cancelen, como el de verdad."""

    def __init__(self, *capturas):
        self.capturas = list(capturas)
        self.llamadas = 0
        self.abierto = threading.Event()

    def disponible(self):
        return True

    def motor(self):
        return "simulado"

    def escuchar(self, cancelar, al_cambiar_fase=None, al_nivel=None):
        self.llamadas += 1
        if self.capturas:
            return self.capturas.pop(0)
        self.abierto.set()
        while not cancelar.is_set():
            time.sleep(0.01)
        self.abierto.clear()
        return _captura(motivo=MotivoFin.CANCELADO, pcm=b"")


class _Whisper:
    nombre = "whisper-local"

    def __init__(self, texto="Hola Emoti"):
        self.texto, self.llamadas = texto, 0

    def disponible(self):
        return True

    def transcribir(self, pcm, frecuencia):
        self.llamadas += 1
        return Transcripcion(self.texto, self.nombre)

    def cerrar(self):
        pass


class FrasesTest(unittest.TestCase):
    def test_las_tres_frases_y_variaciones_menores(self):
        for texto in ("Hola Emoti", "hola, emoti.", "Buenos días, Emoti", "Buenas tardes Emoti",
                      "Ola Emoti", "Hola emotti", "hola imoti", "Hola e moti",
                      "Oye, hola Emoti", "Hola Emoti, ¿cómo estás?", "BUENOS DIAS EMOTY"):
            with self.subTest(texto=texto):
                self.assertTrue(mod.es_activacion(texto))

    def test_lo_que_no_activa(self):
        for texto in ("", "Hola", "Emoti", "buenos días", "Hola remoto", "hola emoción",
                      "Hola Emilio", "Emoti hola", "Buenas noches Emoti",
                      "Le dije hola Emoti a mi hermano ayer",
                      "Hola Emoti que tal estas hoy amigo"):
            with self.subTest(texto=texto):
                self.assertFalse(mod.es_activacion(texto))


class EscuchaTest(unittest.TestCase):
    def _escucha(self, mic, whisper, puede=lambda: True):
        activaciones = []
        e = mod.EscuchaActivacion(mic, whisper, puede, lambda s: activaciones.append(s))
        return e, activaciones

    def test_activa_con_la_frase(self):
        e, act = self._escucha(_Mic(_captura()), _Whisper("Buenas tardes, Emoti"))
        self.assertTrue(e.escuchar_una_vez())
        self.assertEqual(act, ["buenas tardes"], "dice qué saludo fue")

    def test_otra_frase_no_activa(self):
        e, act = self._escucha(_Mic(_captura()), _Whisper("¿Qué hora es?"))
        self.assertFalse(e.escuchar_una_vez())
        self.assertEqual(act, [])

    def test_lo_largo_o_sin_voz_ni_se_transcribe(self):
        for captura in (_captura(util=mod.MAX_SEGUNDOS_FRASE + 0.5),
                        _captura(motivo=MotivoFin.SIN_VOZ),
                        _captura(pcm=b"")):
            w = _Whisper()
            e, act = self._escucha(_Mic(captura), w)
            with self.subTest(captura=captura.motivo):
                self.assertFalse(e.escuchar_una_vez())
                self.assertEqual((w.llamadas, act), (0, []))

    def test_si_entretanto_empezo_a_hablar_no_activa(self):
        estado = {"puede": True}
        w = _Whisper()

        def transcribir(pcm, frecuencia):
            estado["puede"] = False          # el robot empezó a hablar
            return Transcripcion("Hola Emoti", "whisper-local")

        w.transcribir = transcribir
        e, act = self._escucha(_Mic(_captura()), w, lambda: estado["puede"])
        self.assertFalse(e.escuchar_una_vez())
        self.assertEqual(act, [])

    def test_solo_con_reconocimiento_local(self):
        self.assertTrue(mod.EscuchaActivacion.admite(_Whisper()))
        for nombre in ("remoto", "gemini", "ninguno", ""):
            self.assertFalse(mod.EscuchaActivacion.admite(type("T", (), {"nombre": nombre})()))

    def test_no_abre_el_microfono_mientras_no_puede_y_lo_suelta_al_pausar(self):
        mic = _Mic()
        puede = threading.Event()
        e, _ = self._escucha(mic, _Whisper(), puede.is_set)
        e.iniciar()
        self.addCleanup(e.detener)
        time.sleep(0.4)
        self.assertEqual(mic.llamadas, 0, "sin permiso no escucha")
        puede.set()
        self.assertTrue(mic.abierto.wait(2))
        puede.clear()                         # empieza un turno
        e.pausar()
        self.assertFalse(mic.abierto.is_set(), "micrófono libre para el turno")
        llamadas = mic.llamadas
        time.sleep(0.4)
        self.assertEqual(mic.llamadas, llamadas)


class AplicacionTest(_AppSimulada, unittest.TestCase):
    def _app_con(self, activada=True, stt=None, mic=None):
        from emotibot import perfil_usuario as pu
        pu.guardar(pu.POR_DEFECTO)
        mic = mic or _Mic()
        valor = "true" if activada else "false"
        for parche in (mock.patch.dict("os.environ", {"EMOTI_DIALOGO_ACTIVACION_POR_VOZ": valor}),
                       mock.patch.object(self.mod_app, "Microfono", lambda *a: mic),
                       mock.patch.object(self.mod_app.mod_stt, "crear", lambda *a: _Whisper()),
                       mock.patch.object(self.mod_app.Aplicacion, "_transcriptor_activacion",
                                         lambda yo: stt or _Whisper())):
            parche.start()
            self.addCleanup(parche.stop)
        app = self._app()
        app._fin_habla = 0.0
        return app, mic

    def test_apagada_por_defecto_y_el_modo_actual_sigue(self):
        from emotibot import ajustes
        self.assertFalse(ajustes.cargar().dialogo.activacion_por_voz)
        self.assertFalse(ajustes.AjustesDialogo().activacion_por_voz,
                         "sin config/ajustes.json, también apagada")
        app, mic = self._app_con(activada=False)
        self.assertIsNone(app.activacion)
        time.sleep(0.3)
        self.assertEqual(mic.llamadas, 0)

    def test_con_reconocimiento_remoto_no_se_activa(self):
        remoto = _Whisper()
        remoto.nombre = "remoto"
        app, _ = self._app_con(stt=remoto)
        self.assertIsNone(app.activacion)

    def test_no_escucha_durante_turnos_ni_mientras_habla(self):
        app, _ = self._app_con()
        self.assertIsNotNone(app.activacion)
        self.assertTrue(app._puede_escuchar_activacion())
        for cambio in ({"ocupado": True}, {"microfono_silenciado": True}):
            with self.subTest(cambio=cambio):
                for k, v in cambio.items():
                    setattr(app, k, v)
                self.assertFalse(app._puede_escuchar_activacion())
                for k in cambio:
                    setattr(app, k, False)
        with mock.patch.object(app.altavoz, "hablando", lambda: True, create=True):
            self.assertFalse(app._puede_escuchar_activacion())
        app._fin_habla = time.monotonic()
        self.assertFalse(app._puede_escuchar_activacion(), "margen tras hablar")

    def test_saluda_y_despues_escucha_sin_llamar_a_la_ia(self):
        app, mic = self._app_con()
        with mock.patch.object(app, "_pedir_turno") as turno, \
                mock.patch.object(app.raiz, "after", lambda ms, f: f()), \
                mock.patch.object(app.gestor, "procesar", side_effect=AssertionError), \
                mock.patch.object(app.orquestador, "responder", side_effect=AssertionError):
            mic.capturas.append(_captura())
            self.assertTrue(app.activacion.escuchar_una_vez())
            tipo, valor = app.eventos.get(timeout=1)
            while tipo != "activacion":
                tipo, valor = app.eventos.get(timeout=1)
            dicho = len(app.altavoz.dicho)
            app._atender(tipo, valor)
            self.assertEqual(len(app.altavoz.dicho), dicho + 1, "responde al saludo")
            self.assertIn(app.detalle, mod.RESPUESTAS["hola"], "texto local")
            turno.assert_not_called()               # aún saluda: no escucha
            self.assertFalse(app._puede_escuchar_activacion(), "ni se reactiva")
            app._atender("fin_saludo", None)
            turno.assert_called_once_with(fijo=False)
            app.ocupado = True
            turno.reset_mock()
            app._atender("activacion", "hola")
            turno.assert_not_called()

    def test_la_respuesta_al_saludo_varia_y_corresponde(self):
        for saludo, opciones in mod.RESPUESTAS.items():
            anterior = ""
            for _ in range(20):
                frase = mod.respuesta_saludo(saludo, anterior)
                self.assertIn(frase, opciones)
                self.assertNotEqual(frase, anterior, "no repite la anterior")
                anterior = frase
        self.assertEqual(mod.que_saludo("Buenos días, Emoti"), "buenos dias")
        self.assertEqual(mod.que_saludo("Hola Emoti"), "hola")
        self.assertEqual(mod.que_saludo("Hola remoto"), "")

    def test_el_turno_suelta_el_microfono_de_la_activacion(self):
        app, mic = self._app_con()
        self.assertTrue(mic.abierto.wait(3), "escucha ligera en marcha")
        with mock.patch.object(self.mod_app.threading, "Thread"):
            app._pedir_turno(fijo=False)
        self.assertFalse(mic.abierto.is_set())

    def test_se_ve_que_el_microfono_esta_abierto(self):
        app, _ = self._app_con()
        app._pintar_textos()
        textos = [app.lienzo.itemcget(i, "text") for i in app._textos.values()]
        self.assertTrue(any("Hola Emoti" in t for t in textos))


if __name__ == "__main__":
    unittest.main()
