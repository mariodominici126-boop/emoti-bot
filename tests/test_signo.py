"""Signo «!» / «?» (27-11-2026): una marca que está o no está.
«algo va mal» lleva «!»; «no te oí / no te entendí» (sin_entender) es la
cara de reposo con «?». «curioso» ya no existe. Se ve con y sin carcasa:
un glifo no es texto de interfaz."""
import unittest

from emotibot.rostro import EXPRESIONES
from emotibot.rostro.estados import componer
from tests.test_opciones_publicadas import ROSTROS, _cara


def _visibles(lienzo, cara):
    items = [cara._items["signo_trazo"], cara._items["signo_punto"], *cara._celdas_signo]
    return [i for i in items if lienzo.items[i]["config"].get("state") != "hidden"]


class SignoTest(unittest.TestCase):
    def test_quien_lleva_signo(self):
        con_signo = {n: e.signo for n, e in EXPRESIONES.items() if e.signo}
        self.assertEqual(con_signo, {"error": "!", "sin_entender": "?"})
        self.assertNotIn("curioso", EXPRESIONES)

    def test_sin_entender_es_el_reposo_con_interrogacion(self):
        reposo, duda = EXPRESIONES["reposo"], EXPRESIONES["sin_entender"]
        for campo in ("apertura_ojos", "curva_boca", "ceja_alto", "ceja_angulo",
                      "inclinacion", "mirada", "color"):
            self.assertEqual(getattr(duda, campo), getattr(reposo, campo), campo)
        self.assertEqual(componer("hablando", "sin_entender").signo, "?",
                         "también mientras dice «¿lo repites?»")

    def test_se_ve_en_los_tres_con_y_sin_carcasa(self):
        for rostro in ROSTROS:
            for carcasa in (True, False):
                for estado, debe in (("error", True), ("sin_entender", True),
                                     ("reposo", False), ("preocupado", False)):
                    lienzo, cara = _cara(rostro, carcasa=carcasa, estado=estado)
                    with self.subTest(rostro=rostro, carcasa=carcasa, estado=estado):
                        self.assertEqual(bool(_visibles(lienzo, cara)), debe)

    def test_la_exclamacion_nunca_va_entre_los_ojos(self):
        """Entre los ojos, una raya vertical es la arruga del ceño: sin
        carcasa, ojos entornados + raya + boca recta era una cara de enfado
        (revisión del responsable, 27-11-2026). El «!» va por fuera del ojo
        derecho, como el «?» con carcasa."""
        from tests.test_opciones_publicadas import TAMANOS
        for rostro in ROSTROS:
            for ancho, alto in TAMANOS:
                for carcasa in (True, False):
                    lienzo, cara = _cara(rostro, carcasa=carcasa, ancho=ancho, alto=alto,
                                         estado="error")
                    xs = [x for i in _visibles(lienzo, cara)
                          for x in lienzo.items[i]["coords"][0::2]]
                    ojo = lienzo.items[cara._items["ojo_der"]]["coords"]
                    with self.subTest(rostro=rostro, tamano=(ancho, alto), carcasa=carcasa):
                        self.assertGreaterEqual(min(xs), max(ojo[0::2]),
                                                "a la derecha del ojo derecho")

    def test_no_pisa_los_ojos(self):
        for rostro in ROSTROS:
            for carcasa in (True, False):
                for estado in ("error", "sin_entender"):
                    lienzo, cara = _cara(rostro, carcasa=carcasa, estado=estado)
                    xs = [x for i in _visibles(lienzo, cara)
                          for x in lienzo.items[i]["coords"][0::2]]
                    ys = [y for i in _visibles(lienzo, cara)
                          for y in lienzo.items[i]["coords"][1::2]]
                    for lado in ("izq", "der"):
                        co = lienzo.items[cara._items[f"ojo_{lado}"]]["coords"]
                        ox0, ox1 = min(co[0::2]), max(co[0::2])
                        oy0, oy1 = min(co[1::2]), max(co[1::2])
                        solapa = (min(xs) < ox1 and max(xs) > ox0
                                  and min(ys) < oy1 and max(ys) > oy0)
                        with self.subTest(rostro=rostro, carcasa=carcasa, estado=estado,
                                          ojo=lado):
                            self.assertFalse(solapa)


if __name__ == "__main__":
    unittest.main()
