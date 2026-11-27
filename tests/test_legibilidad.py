"""C4 con los tres rostros: opciones que no se resuelven por eliminación,
distractores, palabras corrientes, un rostro por participante por turnos y
análisis por expresión (decide) y rostro contra rostro (informa)."""
import hashlib
import importlib.util
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from emotibot import rutas

UMBRAL = {"acierto_minimo_por_expresion": 0.70, "confusion_maxima_con_otra": 0.25,
          "participantes_minimos": 8, "provisional": True}


def _modulo():
    spec = importlib.util.spec_from_file_location("legibilidad_rostro",
                                                  rutas.RAIZ / "bin" / "legibilidad_rostro.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class DisenoTest(unittest.TestCase):
    def setUp(self):
        self.m = _modulo()

    def test_mas_opciones_que_laminas_y_con_distractores(self):
        m = self.m
        self.assertGreater(len(m.OPCIONES), len(m.EXPRESIONES))
        self.assertEqual(len(set(m.OPCIONES)), len(m.OPCIONES))
        for extra in ("enfadado", "triste", "no sé"):
            self.assertIn(extra, m.OPCIONES)
        correctas = {etiqueta for _, etiqueta in m.EXPRESIONES.values()}
        self.assertFalse({"enfadado", "triste"} & correctas, "los distractores no están en el set")

    def test_palabras_corrientes_no_nombres_internos(self):
        m = self.m
        etiquetas = {e: etiqueta for e, (_, etiqueta) in m.EXPRESIONES.items()}
        self.assertEqual(etiquetas["reposo"], "tranquilo")
        self.assertEqual(etiquetas["error"], "algo va mal")
        for interno in ("reposo", "error", "feliz", "sin_conexion", "no_disponible"):
            self.assertNotIn(interno, m.OPCIONES)

    def test_hablando_y_respiracion_fuera(self):
        for nombre in self.m.EXPRESIONES:
            self.assertFalse(nombre.startswith(("hablando", "respirando")))
        self.assertIn("hablando", self.m.FUERA)

    def test_un_rostro_por_participante_por_turnos(self):
        m = self.m
        asignados = [m.rostro_de(f"P{n:02d}") for n in range(1, 7)]
        self.assertEqual(asignados, list(m.ROSTROS) * 2)
        with self.assertRaises(ValueError):
            m.rostro_de("Maria")

    def test_la_clave_no_delata_nada(self):
        clave = self.m.hacer_clave()
        self.assertEqual(len(clave), 3 * len(self.m.EXPRESIONES))
        for codigo in clave:
            self.assertRegex(codigo, r"^L-[0-9A-F]{4}$")


class PrepararTest(unittest.TestCase):
    def test_prepara_sin_tocar_el_umbral(self):
        m = _modulo()
        umbral = rutas.CONFIG_REPO / "c4_umbral.json"
        antes = (umbral.read_bytes(), umbral.stat().st_mtime)
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            with mock.patch.multiple(m, DIRECTORIO=base, CLAVE=base / "clave.json",
                                     RESPUESTAS=base / "respuestas"):
                argumentos = types.SimpleNamespace(sobrescribir=False, tamano="80x48",
                                                   sin_carcasa=False, participantes=6)
                m.preparar(argumentos, capturar=lambda r, e: Image.new("RGB", (8, 8)))
                clave = json.loads((base / "clave.json").read_text(encoding="utf-8"))
                self.assertEqual(clave["umbral_sha256_al_preparar"],
                                 hashlib.sha256(antes[0]).hexdigest())
                filas = (base / "hoja_registro_papel.csv").read_text(
                    encoding="utf-8-sig").splitlines()[1:]
                for fila in filas:
                    participante, lamina, _ = fila.split(",")
                    self.assertEqual(clave["clave"][lamina]["rostro"], m.rostro_de(participante),
                                     "en papel, cada uno solo su rostro")
                self.assertEqual(len(filas), 6 * len(m.EXPRESIONES))
                pagina = (base / "prueba.html").read_text(encoding="utf-8")
                self.assertIn("Puedes usar la misma palabra", pagina)
        self.assertEqual((umbral.read_bytes(), umbral.stat().st_mtime), antes)


class AnalisisTest(unittest.TestCase):
    def setUp(self):
        self.m = _modulo()
        self.clave = self.m.hacer_clave()
        self.por = {(d["rostro"], d["expresion"]): c for c, d in self.clave.items()}

    def _filas(self, participantes, respuesta):
        filas = []
        for n in range(1, participantes + 1):
            p = f"P{n:02d}"
            rostro = self.m.rostro_de(p)
            for expresion in self.m.EXPRESIONES:
                filas.append({"participante": p, "lamina": self.por[(rostro, expresion)],
                              "respuesta": respuesta(rostro, expresion, n)})
        return filas

    def test_junta_por_expresion_y_compara_rostros(self):
        m = self.m
        correcta = {e: etiqueta for e, (_, etiqueta) in m.EXPRESIONES.items()}

        def respuesta(rostro, expresion, n):
            if expresion == "pensando" and rostro == "tele":
                return "triste"                  # la tele no se lee: y se lee de más
            return correcta[expresion]

        r = m.analizar(self._filas(12, respuesta), self.clave, UMBRAL)
        self.assertEqual(r["participantes"], 12)
        self.assertTrue(r["suficientes"])
        self.assertTrue(r["por_expresion"]["reposo"]["pasa"])
        pensando = r["por_expresion"]["pensando"]
        self.assertFalse(pensando["pasa"], "4 de 12 dicen triste: 67 % y 33 % de confusión")
        self.assertAlmostEqual(pensando["de_mas"]["triste"], 4 / 12)
        self.assertFalse(r["pasan_todas"])
        comparar = r["rostro_contra_rostro"]["pensando"]
        self.assertEqual(comparar["peor"], "tele")
        self.assertTrue(comparar["clara"])
        self.assertFalse(r["por_rostro"]["tele"]["suficientes"], "4 por rostro: informa")

    def test_pocos_participantes_no_decide(self):
        m = self.m
        r = m.analizar(self._filas(3, lambda r, e, n: m.EXPRESIONES[e][1]), self.clave, UMBRAL)
        self.assertFalse(r["suficientes"])
        self.assertFalse(r["pasan_todas"])

    def test_lamina_de_otro_rostro_se_descarta(self):
        m = self.m
        otra = self.por[("tele", "reposo")]            # P01 ve hybrid_balanced
        r = m.analizar([{"participante": "P01", "lamina": otra, "respuesta": "tranquilo"}],
                       self.clave, UMBRAL)
        self.assertEqual(r["participantes"], 0)
        self.assertTrue(r["avisos"])


if __name__ == "__main__":
    unittest.main()
