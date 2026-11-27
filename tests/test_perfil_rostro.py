"""Perfil de rostro (proporciones y colores como datos) y camino único de dibujo.

- El perfil por defecto carga y es la ÚNICA fuente de colores (PALETA sale
  de él; paleta.py no lleva ningún color escrito).
- La carga es estricta: falta, sobra o tipo erróneo → error que dice cuál.
- Una variante es solo un archivo de datos: cambia la cara sin tocar código.
- La aplicación y el visor crean la cara por la misma fábrica, `crear_cara`,
  y ninguno instancia `Cara` por su cuenta (lo que pasó el 22-11: se juzgó
  la aplicación de antes del porte creyendo que no lo recogía).
"""
import ast
import copy
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from emotibot import ajustes, rutas
from emotibot.rostro import PALETA, crear_cara, perfil as mod_perfil
from emotibot.rostro.cara import Cara
from tests.test_rostro import LienzoSimulado

RAIZ = rutas.RAIZ


def _datos_por_defecto() -> dict:
    return json.loads(mod_perfil.ruta(mod_perfil.POR_DEFECTO).read_text(encoding="utf-8"))


class PerfilPorDefectoTest(unittest.TestCase):
    def test_carga_el_perfil_configurado(self):
        perfil = mod_perfil.cargar(ajustes.cargar().rostro.perfil)
        self.assertEqual(perfil.nombre, "hybrid_balanced")
        self.assertEqual(perfil.rasgos.ojo_ancho, 0.165)
        self.assertEqual(perfil.cabeza.tamano, 0.75)

    def test_palet_sale_del_perfil(self):
        self.assertEqual(PALETA, mod_perfil.cargar().colores)

    def test_paleta_py_no_lleva_colores(self):
        fuente = (RAIZ / "emotibot" / "rostro" / "paleta.py").read_text(encoding="utf-8")
        # Ningún campo de Paleta con valor (blanco y negro de aclarar() y
        # oscurecer() son operaciones, no colores del rostro).
        self.assertFalse(re.findall(r'^\s+[a-z_]+: str = ', fuente, re.MULTILINE))

    def test_la_cara_usa_el_perfil(self):
        cara = Cara(LienzoSimulado())
        self.assertIs(cara.perfil, mod_perfil.cargar())
        self.assertEqual(cara.paleta, cara.perfil.colores)


class CargaEstrictaTest(unittest.TestCase):
    def _leer(self, datos):
        with tempfile.TemporaryDirectory() as carpeta:
            archivo = Path(carpeta) / "prueba.json"
            archivo.write_text(json.dumps(datos), encoding="utf-8")
            return mod_perfil.leer(archivo)

    def test_el_por_defecto_es_valido(self):
        self.assertEqual(self._leer(_datos_por_defecto()).nombre, "hybrid_balanced")

    def test_rechaza_lo_que_falta_sobra_o_no_toca(self):
        # (cómo estropearlo, lo que el mensaje tiene que nombrar)
        casos = {
            "falta": (lambda d: d["rasgos"].pop("ojo_ancho"), "ojo_ancho"),
            "sobra": (lambda d: d["ojos"].update(pestanas=0.2), "pestanas"),
            "no es número": (lambda d: d["cejas"].update(grosor="grueso"), "cejas.grosor"),
            "booleano": (lambda d: d["boca"].update(apertura=True), "boca.apertura"),
            "color": (lambda d: d["colores"].update(ojos="cian"), "colores.ojos"),
            "sección": (lambda d: d.pop("barras"), "barras"),
            "entero": (lambda d: d["barras"].update(numero=2.5), "barras.numero"),
            "color de la paleta": (lambda d: d["barras"].update(color_centro="magenta"),
                                   "barras.color_centro"),
        }
        for nombre, (estropear, nombrado) in casos.items():
            datos = copy.deepcopy(_datos_por_defecto())
            estropear(datos)
            with self.subTest(caso=nombre):
                with self.assertRaises(mod_perfil.ErrorPerfil) as error:
                    self._leer(datos)
                self.assertIn(nombrado, str(error.exception))

    def test_nombre_sin_rutas(self):
        for nombre in ("../ajustes", "a/b", "x.json", ""):
            with self.subTest(nombre=nombre):
                with self.assertRaises(mod_perfil.ErrorPerfil):
                    mod_perfil.ruta(nombre)

    def test_las_notas_con_guion_bajo_se_ignoran(self):
        datos = _datos_por_defecto()
        datos["ojos"]["_nota"] = "para personas"
        self.assertEqual(self._leer(datos).ojos.radio, 0.44)


class VarianteEsSoloDatosTest(unittest.TestCase):
    """D10: una variante es un archivo en config/rostro/, no código nuevo."""

    def test_una_variante_cambia_la_cara(self):
        datos = _datos_por_defecto()
        datos["nombre"] = "variante_prueba"
        datos["rasgos"]["ojo_ancho"] = 0.20
        datos["colores"]["ojos"] = "#ff00ff"
        with tempfile.TemporaryDirectory() as carpeta, \
                mock.patch.object(mod_perfil, "DIRECTORIO", Path(carpeta)), \
                mock.patch.dict(mod_perfil._cache, clear=True):
            (Path(carpeta) / "variante_prueba.json").write_text(json.dumps(datos),
                                                                 encoding="utf-8")
            rostro = ajustes.AjustesRostro(perfil="variante_prueba")
            lienzo = LienzoSimulado()
            cara = crear_cara(lienzo, rostro)
            cara.dibujar()
            self.assertAlmostEqual(cara._geo.ojo_ancho / cara._geo.ref_rasgo, 0.20)
            ojo = lienzo.items[cara._items["ojo_izq"]]["config"]
            self.assertEqual(ojo["outline"], "#ff00ff")


class CaminoUnicoDeDibujoTest(unittest.TestCase):
    """La aplicación y el visor recorren el mismo código para crear la cara."""

    ARCHIVOS = ("emotibot/app.py", "bin/vista_previa_rostro.py")

    def _llamadas(self, archivo: str) -> set[str]:
        arbol = ast.parse((RAIZ / archivo).read_text(encoding="utf-8"))
        nombres = set()
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Call):
                f = nodo.func
                nombres.add(f.id if isinstance(f, ast.Name) else
                            f.attr if isinstance(f, ast.Attribute) else "")
        return nombres

    def test_los_dos_usan_crear_cara_y_ninguno_cara_directamente(self):
        for archivo in self.ARCHIVOS:
            with self.subTest(archivo=archivo):
                llamadas = self._llamadas(archivo)
                self.assertIn("crear_cara", llamadas)
                self.assertNotIn("Cara", llamadas)

    def test_crear_cara_respeta_los_ajustes(self):
        for carcasa in (True, False):
            rostro = ajustes.AjustesRostro(carcasa=carcasa)
            cara = crear_cara(LienzoSimulado(), rostro)
            self.assertIsInstance(cara, Cara)
            self.assertEqual(cara.carcasa, carcasa)
            self.assertEqual(cara.perfil.nombre, rostro.perfil)


if __name__ == "__main__":
    unittest.main()
