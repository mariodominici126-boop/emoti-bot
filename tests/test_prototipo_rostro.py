"""Fase 1C: el prototipo de rostro con Pillow, sin ventana.

Pillow es opcional: sin él, estas pruebas se saltan (el robot no lo necesita).
"""
import ast
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

try:
    import PIL  # noqa: F401
    HAY_PILLOW = True
except ImportError:
    HAY_PILLOW = False


class AislamientoTest(unittest.TestCase):
    def test_la_aplicacion_no_importa_el_prototipo(self):
        """Criterio C3: sin cambios en la interfaz principal."""
        for ruta in (RAIZ / "emotibot").rglob("*.py"):
            arbol = ast.parse(ruta.read_text(encoding="utf-8"))
            for nodo in ast.walk(arbol):
                nombres = []
                if isinstance(nodo, ast.Import):
                    nombres = [a.name for a in nodo.names]
                elif isinstance(nodo, ast.ImportFrom) and nodo.module:
                    nombres = [nodo.module]
                for nombre in nombres:
                    self.assertFalse(nombre.startswith(("prototipos", "PIL")),
                                     f"{ruta.name} importa {nombre}")


@unittest.skipUnless(HAY_PILLOW, "Pillow no instalado")
class RenderTest(unittest.TestCase):
    def setUp(self):
        from prototipos.rostro_pillow.animador import Animador
        from prototipos.rostro_pillow.render import RostroPillow
        from prototipos.rostro_pillow.expresiones import EXPRESIONES_C4
        self.Animador, self.RostroPillow = Animador, RostroPillow
        self.expresiones = EXPRESIONES_C4

    def _cuadro(self, nombre, ancho=640, alto=400, voz=0.0, s=1):
        funcional, expresion = self.expresiones[nombre]
        a = self.Animador()
        a.fijar(funcional=funcional, expresion=expresion)
        a.fijar_nivel_voz(voz)
        for _ in range(4):
            a.asentar()
            a.anim.parpadeo = 1.0
        return self.RostroPillow(ancho, alto, supermuestreo=s).cuadro(
            a.anim, a.expresion, 0.0)

    def test_todas_las_expresiones_y_tamanos(self):
        for tamano in ((320, 240), (800, 480), (1280, 720)):
            for nombre in self.expresiones:
                with self.subTest(tamano=tamano, nombre=nombre):
                    imagen = self._cuadro(nombre, *tamano)
                    self.assertEqual(imagen.size, tamano)
                    self.assertEqual(imagen.mode, "RGB")

    def test_la_boca_se_abre_con_la_voz(self):
        from PIL import ImageChops
        callada = self._cuadro("hablando", voz=0.0)
        hablando = self._cuadro("hablando", voz=0.9)
        self.assertIsNotNone(ImageChops.difference(callada, hablando).getbbox())

    def test_reutiliza_la_composicion_de_produccion(self):
        """La animación es la de A1: hablando + feliz abre la boca."""
        a = self.Animador()
        a.fijar(funcional="hablando", expresion="feliz")
        self.assertGreater(a.expresion.apertura_boca, 0.5)
        self.assertTrue(a.expresion.ojos_arco)
        self.assertFalse(a.expresion.anillo_escucha)

    def test_la_sonrisa_curva_hacia_abajo_en_el_centro(self):
        """El prototipo corrige la curva invertida de la boca de producción."""
        from emotibot.rostro.formas import arco
        curva = 0.55 * 100 * 0.035
        puntos = arco(0, 0 - curva * 0.4, 40, -curva, puntos=12)
        ys = puntos[1::2]
        self.assertGreater(ys[6], (ys[0] + ys[-1]) / 2)

    def test_cache_de_giros_acotada_por_memoria(self):
        from prototipos.rostro_pillow import render
        r = self.RostroPillow(1920, 1080)
        for grados in range(-8, 8):          # 16 giros > los ~11 que caben
            r._cabeza_girada(grados / 4)
        por_imagen = r._cabeza.width * r._cabeza.height * 4
        self.assertLessEqual(len(r._giradas) * por_imagen,
                             render._CACHE_GIROS_BYTES + por_imagen)


@unittest.skipUnless(HAY_PILLOW, "Pillow no instalado")
class LegibilidadTest(unittest.TestCase):
    def setUp(self):
        from prototipos.rostro_pillow import legibilidad
        self.l = legibilidad
        self.umbral = json.loads((RAIZ / "config" / "c4_umbral.json").read_text(
            encoding="utf-8"))

    def test_codigos_neutrales(self):
        clave = self.l.codigos(["feliz", "curioso"])
        self.assertEqual(len(clave), 4)
        for codigo in clave:
            self.assertRegex(codigo, r"^L-[0-9A-F]{4}$")

    def test_el_umbral_se_fija_antes(self):
        directorio = Path(tempfile.mkdtemp())
        umbral = directorio / "u.json"
        hoja = directorio / "r.csv"
        umbral.write_text("{}")
        hoja.write_text("x")
        os.utime(umbral, (time.time() - 100, time.time() - 100))
        self.assertTrue(self.l.umbral_valido(umbral, [hoja])[0])
        os.utime(umbral, (time.time() + 100, time.time() + 100))
        valido, motivo = self.l.umbral_valido(umbral, [hoja])
        self.assertFalse(valido)
        self.assertIn("13.8c", motivo)

    def test_analisis(self):
        clave = {"L-AAAA": {"diseno": "A", "expresion": "feliz"},
                 "L-BBBB": {"diseno": "B", "expresion": "feliz"}}
        filas = []
        for p in range(10):
            filas.append({"participante": f"P{p}", "lamina": "L-AAAA",
                          "respuesta": "feliz" if p < 5 else "curioso"})
            filas.append({"participante": f"P{p}", "lamina": "L-BBBB",
                          "respuesta": "feliz" if p < 9 else "no sé"})
        r = self.l.analizar(filas, clave, self.umbral)
        self.assertTrue(r["suficientes"])
        a = r["disenos"]["A"]["expresiones"]["feliz"]
        b = r["disenos"]["B"]["expresiones"]["feliz"]
        self.assertFalse(a["pasa"])
        self.assertEqual(a["confusion_principal"], "curioso")
        self.assertTrue(b["pasa"], "«no sé» no cuenta como confusión")

    def test_umbral_provisional_y_marcado(self):
        self.assertTrue(self.umbral["provisional"])
        self.assertEqual(self.umbral["acierto_minimo_por_expresion"], 0.70)


if __name__ == "__main__":
    unittest.main()
