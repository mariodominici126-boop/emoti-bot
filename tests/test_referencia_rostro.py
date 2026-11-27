"""Referencia de 720 casos por rostro (bin/referencia_rostro.py).

Cada rostro publicado tiene sus huellas en tests/datos/. Si un cambio de
código o de datos mueve un solo trazo de cualquier rostro, falla aquí. Si el
cambio es intencionado: `python bin/referencia_rostro.py grabar` y anotarlo
en la bitácora.
"""
import importlib.util
import unittest

from emotibot import rutas
from emotibot.rostro import perfil as mod_perfil

_spec = importlib.util.spec_from_file_location(
    "referencia_rostro", rutas.RAIZ / "bin" / "referencia_rostro.py")
referencia = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(referencia)


class ReferenciaRostroTest(unittest.TestCase):
    def test_cada_rostro_publicado_tiene_su_referencia(self):
        for rostro in sorted(p.stem for p in mod_perfil.DIRECTORIO.glob("*.json")):
            with self.subTest(rostro=rostro):
                self.assertTrue(referencia.archivo(rostro).is_file(),
                                "rostro nuevo sin referencia: bin/referencia_rostro.py grabar")

    def test_ningun_trazo_cambia(self):
        for rostro in sorted(p.stem for p in mod_perfil.DIRECTORIO.glob("*.json")):
            with self.subTest(rostro=rostro):
                distintos = referencia.comparar(rostro)
                self.assertEqual(distintos, [], f"{len(distintos)} casos distintos de 720")


if __name__ == "__main__":
    unittest.main()
