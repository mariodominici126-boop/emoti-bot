"""Conversación seguida: el micrófono se reabre solo tras contestar.

Apagada por defecto; con las barras a la vista siempre que el micrófono esté
abierto; sin oírse a sí mismo; con tope de turnos y de tiempo; nunca tras la
ruta de seguridad ni tras una despedida. Sin micrófono ni red.
"""
import json
import time
import unittest
from unittest import mock

from emotibot import ajustes as mod_ajustes
from emotibot import perfil_usuario as pu
from emotibot.ia import disponibilidad as disp
from tests.test_activacion import _Mic, _Whisper
from tests.test_asistente import _AppSimulada, _Tecla
from tests.test_carcasa import _ConfigTemporal

COMPLETO = {"completo": True, "actividad": False, "escuchar": False, "seguridad": False,
            "fin": False, "espera": 0.0}


class ConversacionSeguidaTest(_AppSimulada, unittest.TestCase):
    def _app_con(self, continua=True, maximo=6):
        self.cfg = _ConfigTemporal().__enter__()
        self.addCleanup(self.cfg.__exit__, None, None, None)
        pu.guardar(pu.POR_DEFECTO)
        self.cfg.ajustes.write_text(json.dumps({"dialogo": {
            "conversacion_continua": continua, "turnos_seguidos_max": maximo}}),
            encoding="utf-8")
        self.mic = _Mic()
        for parche in (mock.patch.object(self.mod_app, "Microfono", lambda *a: self.mic),
                       mock.patch.object(self.mod_app.mod_stt, "crear", lambda *a: _Whisper())):
            parche.start()
            self.addCleanup(parche.stop)
        app = self._app()
        self.programado = []
        parche = mock.patch.object(app.raiz, "after",
                                   lambda ms, f=None: self.programado.append((ms, f)))
        parche.start()
        self.addCleanup(parche.stop)
        self.turnos = []
        original = app._pedir_turno

        def pedir(fijo, continuo=False):
            self.turnos.append(continuo)
            with mock.patch.object(self.mod_app.threading, "Thread"):
                original(fijo, continuo)
        app._pedir_turno = pedir
        return app

    def _turno_y_respuesta(self, app, datos=COMPLETO):
        """Un turno que termina de hablar: lo que llega en «fin_habla»."""
        app.ocupado = True
        self.programado.clear()
        app._tras_hablar(dict(datos))

    def _reabre(self):
        for ms, f in self.programado:
            if getattr(f, "__name__", "") == "_escuchar_de_nuevo":
                return ms, f
        return None

    # -------------------------------------------------------------------
    def test_apagada_por_defecto(self):
        self.assertFalse(mod_ajustes.AjustesDialogo().conversacion_continua)
        self.assertFalse(mod_ajustes.cargar().dialogo.conversacion_continua)
        app = self._app_con(continua=False)
        app._pedir_turno(fijo=False)
        self._turno_y_respuesta(app)
        self.assertIsNone(self._reabre())
        self.assertIsNone(app._cadena)

    def test_reabre_solo_con_margen_y_es_un_turno_nuevo(self):
        app = self._app_con()
        app._pedir_turno(fijo=False)
        self._turno_y_respuesta(app)
        ms, reabrir = self._reabre()
        self.assertGreaterEqual(ms, 500, "margen para que el altavoz calle (sin eco)")
        reabrir()
        self.assertEqual(self.turnos, [False, True])
        self.assertEqual(app._cadena[0], 1)

    def test_las_barras_se_ven_en_cuanto_se_abre(self):
        app = self._app_con()
        app._pedir_turno(fijo=False)
        self._turno_y_respuesta(app)
        self._reabre()[1]()
        self.assertEqual(app.cara.funcional, "calibrando")
        self.assertTrue(app.cara.microfono_abierto)
        for _ in range(3):
            app.cara.asentar()
            app.cara.dibujar()
        visibles = [i for i in app.cara._barras_items
                    if app.lienzo.itemcget(i, "state") != "hidden"]
        self.assertTrue(visibles, "barras visibles desde que el micrófono se abre")
        app._pintar_textos()
        self.assertTrue(any("micrófono abierto" in app.lienzo.itemcget(i, "text")
                            for i in app._textos.values()))

    def test_no_se_oye_a_si_mismo(self):
        app = self._app_con()
        app._pedir_turno(fijo=False)
        self._turno_y_respuesta(app)
        with mock.patch.object(app.altavoz, "hablando", lambda: True):
            self._reabre()[1]()
        self.assertEqual(self.turnos, [False], "con el altavoz sonando, no se reabre")
        self.assertIsNone(app._cadena)

    def test_tope_de_turnos(self):
        app = self._app_con(maximo=3)
        app._pedir_turno(fijo=False)
        for _ in range(5):
            self._turno_y_respuesta(app)
            reabre = self._reabre()
            if reabre is None:
                break
            reabre[1]()
        self.assertEqual(self.turnos, [False, True, True], "3 turnos y a reposo")
        self.assertIn("Pulsa ESPACIO", app.detalle)

    def test_tope_de_tiempo(self):
        app = self._app_con()
        app._pedir_turno(fijo=False)
        app._cadena[1] -= self.mod_app.MAX_SEGUNDOS_CONVERSACION + 1
        self._turno_y_respuesta(app)
        self.assertIsNone(self._reabre())

    def test_nunca_tras_seguridad_despedida_actividad_ni_sin_inteligencia(self):
        casos = {"seguridad": dict(COMPLETO, seguridad=True), "despedida": dict(COMPLETO, fin=True),
                 "incompleto": dict(COMPLETO, completo=False)}
        for nombre, datos in casos.items():
            with self.subTest(caso=nombre):
                app = self._app_con()
                app._pedir_turno(fijo=False)
                self._turno_y_respuesta(app, datos)
                self.assertIsNone(self._reabre())
        app = self._app_con()
        app._pedir_turno(fijo=False)
        app._ia_turno = (disp.NO_DISPONIBLE, disp.CUOTA)
        self._turno_y_respuesta(app)
        self.assertIsNone(self._reabre(), "sin inteligencia no tiene sentido seguir")

    def test_la_despedida_marca_el_fin(self):
        app = self._app_con()
        self.assertTrue(app.gestor.procesar("adiós").fin_conversacion)

    def test_silencio_vuelve_a_reposo_y_pide_la_frase(self):
        app = self._app_con()
        app._pedir_turno(fijo=False)
        self._turno_y_respuesta(app)
        self._reabre()[1]()
        app._atender("sin_voz", None)
        self.assertIsNone(app._cadena)
        self.assertFalse(app.ocupado)
        self.assertEqual(app.detalle, self.mod_app.FIN_CONVERSACION)
        self.assertFalse(app.cara.microfono_abierto)

    def test_silencio_en_un_turno_normal_sigue_como_antes(self):
        app = self._app_con()
        app._pedir_turno(fijo=False)
        with mock.patch.object(app, "_explicar_sin_voz") as explicar:
            app._atender("sin_voz", None)
        explicar.assert_called_once()

    def test_s_corta_la_conversacion(self):
        app = self._app_con()
        app._pedir_turno(fijo=False)
        app._tecla(_Tecla("s", "s"))
        self.assertIsNone(app._cadena)


if __name__ == "__main__":
    unittest.main()
