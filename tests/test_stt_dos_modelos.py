"""Dos trabajos, dos modelos de Whisper (27-11-2026, corpus de voz real):
despertar con base + pista del nombre; conversación con small SIN pista
(la pista rompía «no sé qué hacer»). Y el banco de regresión no guarda texto.
Sin cargar modelos reales."""
import importlib.util
import json
import sys
import types
import unittest
from unittest import mock

from emotibot import ajustes as mod_ajustes
from emotibot import rutas
from emotibot import stt as mod_stt
from emotibot.stt import whisper_local
from emotibot.stt.base import Transcripcion


class _Modelo:
    creados: list = []

    def __init__(self, nombre, device, compute_type):
        self.nombre, self.llamadas = nombre, []
        _Modelo.creados.append(self)

    def transcribe(self, audio, **kw):
        self.llamadas.append(kw)
        return iter(()), None


def _faster_whisper():
    _Modelo.creados = []
    return mock.patch.object(whisper_local, "importar_opcional",
                             lambda nombre: types.SimpleNamespace(WhisperModel=_Modelo)
                             if nombre == "faster_whisper" else __import__("numpy"))


class RepartoTest(unittest.TestCase):
    def test_los_modelos_de_cada_trabajo(self):
        for stt in (mod_ajustes.AjustesStt(), mod_ajustes.cargar().stt):
            self.assertEqual((stt.modelo_whisper, stt.modelo_activacion), ("small", "base"))

    def test_la_conversacion_va_sin_pista(self):
        with _faster_whisper():
            stt = mod_stt.crear(mod_ajustes.cargar())
            stt.transcribir(b"\x01\x00" * 1600, 16000)
        self.assertEqual(stt.modelo, "small")
        self.assertIsNone(_Modelo.creados[0].llamadas[0]["initial_prompt"])

    def test_el_despertar_va_con_base_y_la_pista(self):
        from emotibot import app as mod_app
        config = mod_ajustes.cargar()
        falsa = types.SimpleNamespace(config=config)
        with _faster_whisper(), mock.patch.object(mod_app.descargas, "whisper_en_disco",
                                                  lambda nombre: True):
            transcriptor = mod_app.Aplicacion._transcriptor_activacion(falsa)
            transcriptor.transcribir(b"\x01\x00" * 1600, 16000)
        self.assertEqual(transcriptor.modelo, "base")
        self.assertEqual(_Modelo.creados[0].llamadas[0]["initial_prompt"],
                         whisper_local.PISTA_NOMBRE)
        self.assertEqual(transcriptor.nombre, "whisper-local", "local: el audio no sale")


class EmpaquetadoTest(unittest.TestCase):
    """Ejecutable (28-11-2026): «small» va dentro del paquete; «base» (solo el
    despertar) se baja a petición en un hilo, sin bloquear la ventana."""

    def test_sin_base_en_disco_no_carga_y_lo_baja(self):
        from emotibot import app as mod_app
        bajadas = []
        falsa = types.SimpleNamespace(config=mod_ajustes.cargar(),
                                      _bajar_whisper_activacion=bajadas.append)
        with _faster_whisper(), mock.patch.object(mod_app.descargas, "whisper_en_disco",
                                                  lambda nombre: False):
            self.assertIsNone(mod_app.Aplicacion._transcriptor_activacion(falsa))
        self.assertEqual(bajadas, ["base"])
        self.assertEqual(_Modelo.creados, [], "ni intenta cargarlo (bajaría en el acto)")

    def test_small_empaquetado_se_carga_de_su_carpeta(self):
        import tempfile
        from pathlib import Path
        from emotibot import rutas as mod_rutas
        with tempfile.TemporaryDirectory() as d:
            carpeta = Path(d) / "modelos" / "whisper-small"
            carpeta.mkdir(parents=True)
            (carpeta / "model.bin").write_bytes(b"x")
            with mock.patch.object(mod_rutas, "RECURSOS", Path(d)), _faster_whisper():
                stt = mod_stt.crear(mod_ajustes.cargar())
            self.assertEqual(_Modelo.creados[0].nombre, str(carpeta))
            self.assertEqual(stt.modelo, "small")


class BancoDeRegresionTest(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location(
            "medir_stt_corpus", rutas.RAIZ / "bin" / "medir_stt_corpus.py")
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    def test_el_resultado_no_lleva_lo_dicho(self):
        secreto = "frase privada que nunca debe guardarse"
        frases = [{"n": 2, "texto": secreto, "clave": "privada", "pcm": b"\x00\x00" * 160,
                   "duracion": 1.0}]

        class Transcriptor:
            def transcribir(self, pcm, frecuencia):
                return Transcripcion(secreto + " oída", "whisper-local")

        filas = self.mod.medir_modelo(Transcriptor(), frases, 16000, 2, False)
        guardado = json.dumps(self.mod.resumen("x", filas, 2, 0.1, {2}), ensure_ascii=False)
        self.assertNotIn("privada", guardado)
        self.assertIn('"exactas"', guardado)

    def test_el_corpus_vive_fuera_del_proyecto(self):
        defecto = self.mod.main.__code__.co_consts
        self.assertTrue(str(rutas.CONFIG_USUARIO / "corpus").startswith(str(rutas.CONFIG_USUARIO)))
        self.assertFalse(str(rutas.CONFIG_USUARIO).startswith(str(rutas.RAIZ)))
        ignorado = (rutas.RAIZ / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("corpus/", ignorado)
        self.assertIn("*.wav", ignorado)


if __name__ == "__main__":
    unittest.main()
