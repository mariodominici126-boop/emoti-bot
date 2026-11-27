"""Tecla C: con o sin carcasa, en caliente y guardado en los AJUSTES de esta
máquina (decisión de instalación), no en el perfil de usuario (gusto)."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from emotibot import ajustes as mod_ajustes
from emotibot import perfil_usuario as pu
from emotibot import rutas
from tests.test_asistente import _AppSimulada, _PerfilTemporal

REPO = rutas.CONFIG_REPO / "ajustes.json"


class _ConfigTemporal:
    """Carpeta de configuración de la máquina, temporal y vacía."""

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.parche = mock.patch.object(rutas, "CONFIG_USUARIO", self.dir)
        self.parche.start()
        return self

    def __exit__(self, *exc):
        self.parche.stop()
        self.tmp.cleanup()

    @property
    def ajustes(self):
        return self.dir / "ajustes.json"


class GuardarCarcasaTest(unittest.TestCase):
    def setUp(self):
        self.repo_antes = REPO.read_bytes()
        self.addCleanup(lambda: self.assertEqual(REPO.read_bytes(), self.repo_antes,
                                                 "el ajustes.json del repositorio no se toca"))

    def test_persiste_y_se_lee_al_arrancar(self):
        with _ConfigTemporal() as c:
            for valor in (False, True, False):
                mod_ajustes.guardar_carcasa(valor)
                self.assertIs(mod_ajustes.cargar().rostro.carcasa, valor)
            self.assertEqual(json.loads(c.ajustes.read_text(encoding="utf-8")),
                             {"rostro": {"carcasa": False}})
            self.assertEqual(sorted(p.name for p in c.dir.iterdir()), ["ajustes.json"],
                             "sin temporales y sin perfil.json: no es del perfil")

    def test_conserva_lo_demas_del_archivo(self):
        with _ConfigTemporal() as c:
            previo = {"rostro": {"fps": 24, "carcasa": True}, "audio": {"ganancia": 2},
                      "_nota": "mía"}
            c.ajustes.write_text(json.dumps(previo), encoding="utf-8")
            mod_ajustes.guardar_carcasa(False)
            self.assertEqual(json.loads(c.ajustes.read_text(encoding="utf-8")),
                             {**previo, "rostro": {"fps": 24, "carcasa": False}})

    def test_un_archivo_ilegible_no_se_sobrescribe(self):
        for contenido in ("{roto", "[1, 2]", json.dumps({"rostro": "no"})):
            with self.subTest(contenido=contenido), _ConfigTemporal() as c:
                c.ajustes.write_text(contenido, encoding="utf-8")
                with self.assertRaises(ValueError):
                    mod_ajustes.guardar_carcasa(False)
                self.assertEqual(c.ajustes.read_text(encoding="utf-8"), contenido)

    def test_el_perfil_no_tiene_carcasa(self):
        self.assertNotIn("carcasa", pu.EJES)
        cambios = pu.sobrescrituras(pu.POR_DEFECTO, ())
        self.assertNotIn("carcasa", cambios.get("rostro", {}))


class TeclaCTest(_AppSimulada, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.config = _ConfigTemporal().__enter__()
        self.addCleanup(self.config.__exit__, None, None, None)
        pu.guardar(pu.POR_DEFECTO)           # con perfil: sin asistente al arrancar

    def test_alterna_en_caliente_y_sigue_igual_al_arrancar(self):
        mod_ajustes.guardar_carcasa(True)
        app = self._app()
        inicial = app.cara.carcasa
        self.assertTrue(inicial)
        self._teclas(app, "c")
        self.assertIs(app.cara.carcasa, not inicial)
        self.assertIs(app.config.rostro.carcasa, not inicial)
        app._pintar_textos()
        app.cara.dibujar()
        visibles = [k for k, i in app._textos.items()
                    if app.lienzo.itemcget(i, "state") != "hidden"
                    and app.lienzo.itemcget(i, "text")]
        self.assertEqual(visibles, [], "sin carcasa no se escribe encima")
        perfil_antes = self.perfil.ruta.read_text(encoding="utf-8")
        # «Reinicio»: una aplicación nueva lee lo guardado.
        otra = self._app()
        self.assertIs(otra.cara.carcasa, not inicial)
        self._teclas(otra, "c")
        self.assertIs(self._app().cara.carcasa, inicial)
        self.assertEqual(self.perfil.ruta.read_text(encoding="utf-8"), perfil_antes,
                         "el perfil de usuario no cambia")

    def test_si_no_se_puede_guardar_vale_en_la_sesion_y_lo_dice(self):
        self.config.ajustes.write_text("{roto", encoding="utf-8")
        app = self._app()
        inicial = app.cara.carcasa
        self._teclas(app, "c")
        self.assertIs(app.cara.carcasa, not inicial)
        self.assertIn("solo en esta sesión", app.detalle)
        self.assertEqual(self.config.ajustes.read_text(encoding="utf-8"), "{roto")

    def test_con_el_asistente_abierto_c_no_hace_nada(self):
        app = self._app()
        inicial = app.cara.carcasa
        self._teclas(app, "p", "c")
        self.assertIsNotNone(app.asistente)
        self.assertIs(app.cara.carcasa, inicial)
        self.assertFalse(self.config.ajustes.exists())


if __name__ == "__main__":
    unittest.main()
