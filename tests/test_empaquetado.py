"""Ejecutable de Windows (28-11-2026): voz «claude» dentro y por defecto,
Daniela a petición, registros fuera de la carpeta del programa. Sin red."""
import importlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from emotibot import ajustes as mod_ajustes
from emotibot import descargas, perfil_usuario as pu, rutas
from emotibot import voz as mod_voz


def _con_modelo(ruta):
    import dataclasses
    a = mod_ajustes.Ajustes()
    return dataclasses.replace(a, voz=dataclasses.replace(a.voz, modelo_piper=ruta))


class VozPorDefectoTest(unittest.TestCase):
    def test_paquete_ajustes_perfil_y_readme_dicen_la_misma_voz(self):
        claude = json.loads((rutas.CONFIG_REPO / "voces" / "claude.json")
                            .read_text(encoding="utf-8"))
        self.assertEqual(Path(claude["modelo_piper"]).name, mod_ajustes.VOZ_EMPAQUETADA)
        self.assertEqual(pu.PerfilUsuario().voz, "claude")
        perfil = json.loads((rutas.CONFIG_REPO / "perfil.json").read_text(encoding="utf-8"))
        self.assertEqual(perfil["voz"], "claude")
        ajustes = json.loads((rutas.CONFIG_REPO / "ajustes.json").read_text(encoding="utf-8"))
        self.assertEqual(Path(ajustes["voz"]["modelo_piper"]).name, mod_ajustes.VOZ_EMPAQUETADA)
        self.assertEqual(ajustes["voz"]["velocidad"], claude["velocidad"])
        leeme = (rutas.RAIZ / "README.md").read_text(encoding="utf-8")
        self.assertIn("`claude` (por defecto)", leeme)
        self.assertNotIn("`daniela` (por defecto)", leeme)

    def test_daniela_no_va_en_el_paquete_y_se_puede_bajar(self):
        self.assertTrue(descargas.voz_descargable(Path("es_AR-daniela-high.onnx")))
        self.assertEqual(descargas.licencia_voz(Path("es_AR-daniela-high.onnx")),
                         "CC BY-SA 4.0")


class RutaDeVozTest(unittest.TestCase):
    def test_busca_en_bajadas_y_en_el_paquete(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            config = _con_modelo(str(d / "no_esta" / "x.onnx"))
            usuario, paquete = d / "usuario", d / "paquete"
            with mock.patch.object(rutas, "VOCES_USUARIO", usuario), \
                    mock.patch.object(rutas, "RECURSOS", paquete):
                self.assertEqual(mod_ajustes.ruta_piper(config), d / "no_esta" / "x.onnx")
                (paquete / "voces").mkdir(parents=True)
                (paquete / "voces" / "x.onnx").write_bytes(b"")
                self.assertEqual(mod_ajustes.ruta_piper(config), paquete / "voces" / "x.onnx")
                usuario.mkdir()
                (usuario / "x.onnx").write_bytes(b"")
                self.assertEqual(mod_ajustes.ruta_piper(config), usuario / "x.onnx")

    def test_sin_la_elegida_suena_la_empaquetada_antes_que_espeak(self):
        empaquetada = Path("paquete/voces/es_MX-claude-high.onnx")
        cargadas = []

        class Piper:
            def __init__(self, ruta, *a):
                if ruta != empaquetada:
                    raise mod_voz.ErrorPiper("no está")
                cargadas.append(ruta)
                self.nombre = "piper"

        config = _con_modelo("~/no-existe/es_AR-daniela-high.onnx")
        with mock.patch.object(mod_voz, "VozPiper", Piper), \
                mock.patch.object(mod_ajustes, "ruta_piper_empaquetada", lambda: empaquetada), \
                mock.patch.object(mod_voz, "VozEspeak", side_effect=AssertionError("espeak no")):
            voz = mod_voz.crear(config)
        self.assertEqual((voz.nombre, cargadas), ("piper", [empaquetada]))


class DescargaVozTest(unittest.TestCase):
    def _respuesta(self, datos):
        r = io.BytesIO(datos)
        r.headers = {"Content-Length": str(len(datos))}
        r.__enter__ = lambda *a: r
        r.__exit__ = lambda *a: False
        return mock.MagicMock(__enter__=lambda s: r, __exit__=lambda *a: False)

    def test_baja_los_dos_archivos_con_progreso(self):
        progreso = []
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(rutas, "VOCES_USUARIO", Path(d)), \
                mock.patch.object(descargas.urllib.request, "urlopen",
                                  lambda url, timeout: self._respuesta(b"x" * 1000)):
            final = descargas.descargar_voz(Path("es_AR-daniela-high.onnx"), progreso.append)
            self.assertTrue(final.is_file())
            self.assertTrue((Path(d) / "es_AR-daniela-high.onnx.json").is_file())
            self.assertEqual(progreso[-1], 1.0)
            self.assertEqual(list(Path(d).glob("*.parte")), [])

    def test_sin_red_no_deja_nada_a_medias(self):
        def sin_red(url, timeout):
            raise OSError("sin conexión")
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(rutas, "VOCES_USUARIO", Path(d)), \
                mock.patch.object(descargas.urllib.request, "urlopen", sin_red):
            with self.assertRaises(descargas.ErrorDescarga):
                descargas.descargar_voz(Path("es_AR-daniela-high.onnx"))
            self.assertEqual(list(Path(d).iterdir()), [])


class RegistrosTest(unittest.TestCase):
    def test_en_el_ejecutable_van_a_localappdata(self):
        with tempfile.TemporaryDirectory() as d:
            entorno = {k: v for k, v in os.environ.items()
                       if k not in ("EMOTI_STATE_DIR", "XDG_STATE_HOME")}
            entorno["LOCALAPPDATA"] = d
            try:
                with mock.patch.dict(os.environ, entorno, clear=True), \
                        mock.patch.object(sys, "frozen", True, create=True), \
                        mock.patch.object(os, "name", "nt"):
                    recargado = importlib.reload(rutas)
                    self.assertEqual(recargado.LOGS, Path(d) / "emotibot" / "logs")
            finally:
                importlib.reload(rutas)
        self.assertEqual(rutas.LOGS, rutas.RAIZ / "logs", "desde el código, logs/ del proyecto")


if __name__ == "__main__":
    unittest.main()
