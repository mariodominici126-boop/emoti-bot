"""Porte al motor Tkinter de la geometría Hybrid Balanced y modo SIN CARCASA.

Lo que se comprueba:
- las proporciones del prototipo (ojos, separación, cejas, orejas);
- cejas en cápsula gruesa CON arco (no una recta, en ningún estado), boca abierta con interior oscuro y borde, «^ ^» más
  gruesos y destellos dibujados; sin rubor;
- el ÁREA DE ROSTRO: con carcasa es la pantalla; sin ella, la ventana entera
  (la aplicación oculta sus textos). Al quitar la carcasa los rasgos crecen
  en vertical y en horizontal, ocupan la pantalla y no se salen de ella;
- las estrellas de «feliz» acompañan a los ojos, no a los bordes;
- las regresiones de hoy, también sin carcasa: los 18 sitios de emisión
  mueven la boca, la respiración es distinta en cada paso y tiene dirección,
  la sonrisa curva hacia el lado bueno y el piloto solo se enciende al
  escuchar.
"""
import math
import unittest
from unittest import mock

from emotibot.rostro import EXPRESIONES
from emotibot.rostro import cara as mod_cara
from emotibot.rostro.cara import Cara
from emotibot.rostro.perfil import cargar as cargar_perfil
from emotibot.rostro.paleta import PALETA, mezclar
from tests.test_rostro import (LienzoSimulado, alturas_barras, barras_visibles,
                               caja_barras)

TAMANOS = ((800, 480), (1280, 720), (1024, 600), (800, 600))
OCULTOS_SIN_CARCASA = ("carcasa", "pantalla", "oreja_izq", "oreja_der")


def _cara(carcasa=True, ancho=800, alto=480, estado="reposo", funcional=None, voz=0.0,
          escucha=0.0):
    lienzo = LienzoSimulado(ancho, alto)
    cara = Cara(lienzo, PALETA, carcasa=carcasa)
    if funcional:
        cara.fijar(funcional=funcional, expresion=estado)
    else:
        cara.fijar_estado(estado)
    cara.fijar_nivel_voz(voz)
    cara.fijar_nivel_escucha(escucha)
    for _ in range(4):
        cara.asentar()
        cara._anim.parpadeo = 1.0
        cara._inicio = mod_cara.time.monotonic()     # respiración periódica en 0
        cara.dibujar()
    return lienzo, cara


def _caja(lienzo, cara, clave):
    coords = lienzo.items[cara._items[clave]]["coords"]
    xs, ys = coords[0::2], coords[1::2]
    return min(xs), min(ys), max(xs), max(ys)


def _visible(lienzo, item) -> bool:
    return lienzo.items[item]["config"].get("state", "normal") != "hidden"


class ProporcionesTest(unittest.TestCase):
    """Con carcasa, a 800×480 la cabeza equivalente ES la cabeza real."""

    def test_proporciones_del_prototipo(self):
        _, cara = _cara()
        g = cara._geo
        self.assertAlmostEqual(g.ref_ancho, g.cabeza_ancho, delta=0.5)
        self.assertAlmostEqual(g.ref_alto, g.cabeza_alto, delta=0.5)
        self.assertAlmostEqual(g.sep_ojos / g.cabeza_ancho, 0.200, places=3)
        self.assertAlmostEqual(g.ojo_ancho / g.cabeza_ancho, 0.165, places=3)
        self.assertAlmostEqual(g.ojo_alto / g.cabeza_alto, 0.340, places=3)
        self.assertAlmostEqual((g.centro_y - g.y_ojos) / g.cabeza_alto, 0.04, places=3)
        self.assertAlmostEqual((g.centro_y - g.y_ceja) / g.cabeza_alto, 0.275, places=3)

    def test_con_carcasa_una_cuarta_parte_mas_pequena(self):
        """El rostro siempre fue demasiado grande: la cabeza mide 0,75 de lo
        que medía (antes: hasta 80 % del ancho y 62 % del alto)."""
        for ancho, alto in TAMANOS:
            lienzo, cara = _cara(True, ancho, alto)
            escala = min(ancho, alto)
            x0, y0, x1, y1 = _caja(lienzo, cara, "carcasa")
            with self.subTest(tamano=(ancho, alto)):
                self.assertLessEqual(x1 - x0, min(ancho * 0.80, escala * 1.06) * 0.75 * 1.02)
                self.assertLessEqual(y1 - y0, min(alto * 0.62, escala * 0.78) * 0.75 * 1.02)

    def test_orejas_en_capsula(self):
        lienzo, cara = _cara()
        x0, y0, x1, y1 = _caja(lienzo, cara, "oreja_der")
        g = cara._geo
        self.assertAlmostEqual(y1 - y0, g.cabeza_alto * 0.34, delta=1.0)
        self.assertAlmostEqual(x1 - x0, g.oreja_ancho * 1.15, delta=1.0)
        # Cápsula: el radio es medio ancho, así que arriba no hay tramo recto
        # (en un rectángulo redondeado normal, el borde superior es plano).
        coords = lienzo.items[cara._items["oreja_der"]]["coords"]
        arriba = [x for x, y in zip(coords[0::2], coords[1::2])
                  if y < y0 + (x1 - x0) * 0.005]
        self.assertLess(max(arriba) - min(arriba), (x1 - x0) * 0.35)

    def test_los_rasgos_caben_en_la_pantalla(self):
        for ancho, alto in TAMANOS:
            for estado in ("escuchando", "preocupado", "pensando", "hablando"):
                lienzo, cara = _cara(ancho=ancho, alto=alto, estado=estado, voz=1.0)
                px0, py0, px1, py1 = _caja(lienzo, cara, "pantalla")
                for clave in ("ceja_izq", "ceja_der", "ojo_izq", "ojo_der", "boca"):
                    if not _visible(lienzo, cara._items[clave]):
                        continue
                    x0, y0, x1, y1 = _caja(lienzo, cara, clave)
                    with self.subTest(tamano=(ancho, alto), estado=estado, pieza=clave):
                        self.assertGreaterEqual(x0, px0 - 1)
                        self.assertLessEqual(x1, px1 + 1)
                        self.assertGreaterEqual(y0, py0 - 1)
                        self.assertLessEqual(y1, py1 + 1)


class FormasTest(unittest.TestCase):
    def test_cejas_son_capsulas_gruesas(self):
        lienzo, cara = _cara()
        for lado in ("izq", "der"):
            item = lienzo.items[cara._items[f"ceja_{lado}"]]
            self.assertEqual(item["tipo"], "polygon")
            x0, y0, x1, y1 = _caja(lienzo, cara, f"ceja_{lado}")
            grosor = cara._geo.unidad * 0.017
            self.assertGreater(y1 - y0, grosor * 0.9, "gruesa, no una raya")
            self.assertAlmostEqual(x1 - x0, cara._geo.ojo_ancho * 1.2, delta=grosor)

    def test_la_ceja_no_es_una_recta_en_ningun_estado(self):
        """El porte las dejó rectas y perdieron la forma: tienen que curvar.

        Se mide el borde superior de la cápsula (los 11 primeros vértices,
        antes de la tapa): su punto central se aparta de la cuerda entre los
        extremos. El sesgo de preocupado o curioso es lineal y no cuenta.
        """
        for carcasa in (True, False):
            for estado in EXPRESIONES:
                lienzo, cara = _cara(carcasa, estado=estado)
                for lado in ("izq", "der"):
                    coords = lienzo.items[cara._items[f"ceja_{lado}"]]["coords"]
                    borde = list(zip(coords[0::2], coords[1::2]))[:11]
                    (xa, ya), (xb, yb) = borde[0], borde[-1]
                    xm, ym = borde[5]
                    largo = math.hypot(xb - xa, yb - ya)
                    flecha = abs((xb - xa) * (ya - ym) - (xa - xm) * (yb - ya)) / largo
                    with self.subTest(carcasa=carcasa, estado=estado, lado=lado):
                        self.assertGreater(flecha, cara._geo.ref_alto * 0.03)

    def test_preocupacion_sube_los_extremos_interiores(self):
        lienzo, cara = _cara(estado="preocupado")
        coords = lienzo.items[cara._items["ceja_izq"]]["coords"]
        puntos = list(zip(coords[0::2], coords[1::2]))
        interior = max(puntos, key=lambda p: p[0])      # el más cercano al centro
        exterior = min(puntos, key=lambda p: p[0])
        self.assertLess(interior[1], exterior[1])

    def test_boca_abierta_con_interior_oscuro_y_borde(self):
        lienzo, cara = _cara(estado="hablando", voz=1.0)
        config = lienzo.items[cara._items["boca"]]["config"]
        self.assertEqual(config["outline"], cara._anim.color)
        self.assertEqual(config["fill"], mezclar(PALETA.boca_interior, PALETA.pantalla, 0.3))
        self.assertNotEqual(config["fill"], cara._anim.color)

    def test_boca_cerrada_es_una_banda_sin_borde(self):
        lienzo, cara = _cara(estado="reposo")
        config = lienzo.items[cara._items["boca"]]["config"]
        self.assertEqual(config["outline"], "")
        self.assertEqual(config["fill"], cara._anim.color)

    def test_alegria_arcos_gruesos_y_estrellas_dibujadas(self):
        lienzo, cara = _cara(estado="feliz")
        arco = lienzo.items[cara._items["arco_izq"]]["config"]
        self.assertGreaterEqual(arco["width"], int(cara._geo.unidad * 0.026))
        for item in cara._destellos_items:
            datos = lienzo.items[item]
            self.assertEqual(datos["tipo"], "polygon", "no el carácter ✦")
            self.assertEqual(len(datos["coords"]), 16, "cuatro puntas, ocho vértices")
            self.assertTrue(_visible(lienzo, item))

    def test_sin_destellos_fuera_de_la_alegria(self):
        lienzo, cara = _cara(estado="reposo")
        for item in cara._destellos_items:
            self.assertFalse(_visible(lienzo, item))

    def test_sin_rubor(self):
        """El responsable rechazó el rubor: el porte no lo reintroduce."""
        _, cara = _cara(estado="feliz")
        self.assertFalse([k for k in cara._items if "rubor" in k or "mejilla" in k])


class SinCarcasaTest(unittest.TestCase):
    def test_no_dibuja_cabeza(self):
        lienzo, cara = _cara(carcasa=False)
        for clave in OCULTOS_SIN_CARCASA:
            with self.subTest(pieza=clave):
                self.assertFalse(_visible(lienzo, cara._items[clave]))
        for clave in ("ojo_izq", "ojo_der", "ceja_izq", "boca"):
            self.assertTrue(_visible(lienzo, cara._items[clave]))

    def test_con_carcasa_si_la_dibuja(self):
        lienzo, cara = _cara(carcasa=True)
        for clave in OCULTOS_SIN_CARCASA:
            self.assertTrue(_visible(lienzo, cara._items[clave]))

    def test_area_de_rostro(self):
        for ancho, alto in TAMANOS:
            _, con = _cara(True, ancho, alto)
            _, sin = _cara(False, ancho, alto)
            g = con._geo
            # Con carcasa: la pantalla.
            self.assertAlmostEqual(con.area_de_rostro()[0],
                                   ancho / 2 - g.cabeza_ancho / 2 + g.marco)
            # Sin carcasa: la ventana entera, menos un margen mínimo.
            m = cargar_perfil().sin_carcasa.margen
            self.assertEqual(sin.area_de_rostro(),
                             (ancho * m, alto * m, ancho * (1 - m), alto * (1 - m)))

    def test_los_rasgos_crecen_al_quitar_la_carcasa(self):
        """También a lo ancho: ojos, boca y separación.

        Medido: en 16:9 y 5:3 los ojos crecen ×2,15 a lo ancho y ×1,87 a lo
        alto, y se separan ×2,3–2,5; en 4:3 (sin ancho de sobra) todo ×1,79.
        """
        for ancho, alto in TAMANOS:
            for estado, voz in (("reposo", 0.0), ("hablando", 1.0)):
                lc, con = _cara(True, ancho, alto, estado, voz=voz)
                ls, sin = _cara(False, ancho, alto, estado, voz=voz)
                for clave in ("ojo_izq", "ceja_izq", "boca"):
                    a = _caja(lc, con, clave)
                    b = _caja(ls, sin, clave)
                    with self.subTest(tamano=(ancho, alto), estado=estado, pieza=clave):
                        self.assertGreater(b[2] - b[0], (a[2] - a[0]) * 1.7)
                        self.assertGreater(b[3] - b[1], (a[3] - a[1]) * 1.7)
                with self.subTest(tamano=(ancho, alto), estado=estado, pieza="separación"):
                    self.assertGreater(sin._geo.sep_ojos, con._geo.sep_ojos * 1.7)

    def test_en_pantalla_ancha_crece_mas_a_lo_ancho(self):
        lc, con = _cara(True, 1280, 720)
        ls, sin = _cara(False, 1280, 720)
        a, b = _caja(lc, con, "ojo_izq"), _caja(ls, sin, "ojo_izq")
        ancho = (b[2] - b[0]) / (a[2] - a[0])
        alto = (b[3] - b[1]) / (a[3] - a[1])
        self.assertGreater(ancho, alto * 1.1)
        self.assertLess(ancho, alto * 1.2, "sin deformar el ojo más de ×1,15")

    def test_la_cara_ocupa_la_pantalla(self):
        """En reposo, los rasgos cubren ≥ 80 % del ancho y ≥ 60 % del alto.

        En reposo ya no hay nada en la barbilla (las barras del micrófono
        solo existen al escuchar), así que el alto va de las cejas a la boca.
        """
        piezas = ("ceja_izq", "ceja_der", "ojo_izq", "ojo_der", "boca")
        for ancho, alto in TAMANOS:
            lienzo, cara = _cara(False, ancho, alto)
            cajas = [_caja(lienzo, cara, k) for k in piezas]
            with self.subTest(tamano=(ancho, alto)):
                self.assertGreater(max(c[2] for c in cajas) - min(c[0] for c in cajas),
                                   ancho * 0.80)
                self.assertGreater(max(c[3] for c in cajas) - min(c[1] for c in cajas),
                                   alto * 0.60)

    def test_nada_se_sale_de_la_ventana(self):
        """Todas las expresiones, con voz y escucha, incluida la inspiración
        (escala 1,08) y la inclinación de «pensando»: margen ≥ 1,5 %."""
        piezas = ["ceja_izq", "ceja_der", "boca",
                  "ojo_izq", "ojo_der", "arco_izq", "arco_der"]
        for ancho, alto in TAMANOS:
            for estado, voz, escucha in [(e, v, x) for e in EXPRESIONES
                                         for v in (0.0, 1.0) for x in (0.0, 1.0)]:
                lienzo, cara = _cara(False, ancho, alto, estado, voz=voz, escucha=escucha)
                items = [cara._items[k] for k in piezas] + list(cara._destellos_items)
                if any(barras_visibles(lienzo, cara)):
                    bx0, by0, bx1, by1 = caja_barras(lienzo, cara)
                    with self.subTest(tamano=(ancho, alto), estado=estado, item="barras"):
                        # Medio píxel de tolerancia: las barras van justo al margen.
                        self.assertTrue(bx0 >= ancho * 0.015 - 0.5
                                        and bx1 <= ancho * 0.985 + 0.5)
                        self.assertTrue(by0 >= alto * 0.015 - 0.5
                                        and by1 <= alto * 0.985 + 0.5)
                for item in items:
                    if not _visible(lienzo, item):
                        continue
                    coords = lienzo.items[item]["coords"]
                    xs, ys = coords[0::2], coords[1::2]
                    with self.subTest(tamano=(ancho, alto), estado=estado, item=item):
                        self.assertGreaterEqual(min(xs), ancho * 0.015)
                        self.assertLessEqual(max(xs), ancho * 0.985)
                        self.assertGreaterEqual(min(ys), alto * 0.015)
                        self.assertLessEqual(max(ys), alto * 0.985)

    def test_las_estrellas_acompanan_a_los_ojos(self):
        """Giran con el tiempo: se comprueba una vuelta entera. Cada estrella
        queda junto a un ojo, a cualquier tamaño, no en el borde."""
        for ancho, alto in TAMANOS:
            lienzo, cara = _cara(False, ancho, alto, "feliz")
            g = cara._geo
            for _ in range(40):
                cara._inicio -= 0.37
                cara.dibujar()
                for item in cara._destellos_items:
                    coords = lienzo.items[item]["coords"]
                    x = sum(coords[0::2]) / 8
                    y = sum(coords[1::2]) / 8
                    cerca = min(abs(x - (g.rasgos_x + s * g.sep_ojos)) for s in (-1, 1))
                    with self.subTest(tamano=(ancho, alto)):
                        self.assertLess(cerca, g.ojo_ancho * 0.8)
                        self.assertLess(abs(y - g.y_ojos), g.ojo_alto * 0.8)

    def test_los_ojos_usan_el_fondo_de_la_ventana(self):
        lienzo, cara = _cara(False)
        self.assertEqual(lienzo.items[cara._items["ojo_izq"]]["config"]["fill"],
                         PALETA.fondo)


class RegresionesSinCarcasaTest(unittest.TestCase):
    """Las regresiones de hoy, repetidas en el modo nuevo."""

    def test_todos_los_sitios_mueven_la_boca(self):
        from tests.test_composicion import recorrer_sitios
        for sitio, resultado in recorrer_sitios().items():
            with self.subTest(sitio=sitio):
                lc, callada = _cara(False, estado=resultado.estado_rostro,
                                    funcional="hablando", voz=0.0)
                la, abierta = _cara(False, estado=resultado.estado_rostro,
                                    funcional="hablando", voz=1.0)
                alto_c = _caja(lc, callada, "boca")[3] - _caja(lc, callada, "boca")[1]
                alto_a = _caja(la, abierta, "boca")[3] - _caja(la, abierta, "boca")[1]
                self.assertGreater(alto_a, alto_c * 2)
                self.assertFalse(abierta.microfono_abierto)

    def test_respiracion_distinta_y_con_direccion(self):
        pasos = ("respirando_inhalar", "respirando_sostener", "respirando_exhalar")
        geometrias = []
        for paso in pasos:
            lienzo, cara = _cara(False, estado=paso)
            geometrias.append({k: tuple(round(v, 1) for v in lienzo.items[i]["coords"])
                               for k, i in cara._items.items()})
        self.assertEqual(len({str(g) for g in geometrias}), 3)

        reloj = [100.0]
        with mock.patch.object(mod_cara.time, "monotonic", lambda: reloj[0]):
            lienzo = LienzoSimulado()
            cara = Cara(lienzo, PALETA, carcasa=False)
            cara.fijar_estado("respirando")
            cara.asentar()
            cara.dibujar()

            def ancho_ojo():
                x0, _, x1, _ = _caja(lienzo, cara, "ojo_izq")
                return x1 - x0
            cara.fijar(funcional="reposo", expresion="respirando_inhalar")
            cara.reiniciar_rampa()
            anchos = []
            for _ in range(5):
                cara.dibujar()
                anchos.append(ancho_ojo())
                reloj[0] += 1.0
            self.assertEqual(anchos, sorted(anchos), "crece al inhalar")
            self.assertGreater(anchos[-1], anchos[0] * 1.04)

    def test_la_sonrisa_curva_hacia_el_lado_bueno(self):
        def centro_menos_extremos(estado):
            lienzo, cara = _cara(False, estado=estado)
            coords = lienzo.items[cara._items["boca"]]["coords"]
            ys = coords[1::2][:len(coords) // 4]
            return ys[len(ys) // 2] - (ys[0] + ys[-1]) / 2
        self.assertGreater(centro_menos_extremos("feliz"), 1.0)
        self.assertLess(centro_menos_extremos("preocupado"), 0.0)

    def test_las_barras_solo_al_escuchar_de_verdad(self):
        for carcasa in (True, False):
            with self.subTest(carcasa=carcasa):
                lienzo, cara = _cara(carcasa, estado="reposo", escucha=0.8)
                self.assertFalse(any(barras_visibles(lienzo, cara)))
                lienzo, cara = _cara(carcasa, estado="escuchando", funcional="hablando",
                                     escucha=0.8)
                self.assertFalse(any(barras_visibles(lienzo, cara)))
                lienzo, cara = _cara(carcasa, estado="escuchando", escucha=0.0)
                self.assertTrue(all(barras_visibles(lienzo, cara)))
                silencio = max(alturas_barras(lienzo, cara))
                lienzo, cara = _cara(carcasa, estado="escuchando", escucha=0.8)
                self.assertGreater(max(alturas_barras(lienzo, cara)), silencio * 2)


class SitioDeLasBarrasTest(unittest.TestCase):
    """Fuera de la cabeza, debajo; sin carcasa, abajo del todo. Sin pisar nada."""

    def _todas(self, carcasa, ancho, alto):
        for estado in EXPRESIONES:
            yield _cara(carcasa, ancho, alto, estado, funcional="escuchando", escucha=1.0)

    def test_con_carcasa_debajo_de_la_cabeza(self):
        for ancho, alto in TAMANOS:
            for lienzo, cara in self._todas(True, ancho, alto):
                bx0, by0, bx1, by1 = caja_barras(lienzo, cara)
                abajo_cabeza = max(_caja(lienzo, cara, k)[3]
                                   for k in ("carcasa", "oreja_izq", "oreja_der"))
                with self.subTest(tamano=(ancho, alto), estado=cara.estado):
                    self.assertGreater(by0, abajo_cabeza, "fuera de la cabeza, debajo")

    def test_los_limites_verticales_cubren_todo_el_rostro(self):
        """Los textos de la aplicación se colocan fuera de estos límites; si se
        quedaran cortos, la cabeza inclinada o las barras pisarían un texto."""
        for ancho, alto in TAMANOS:
            todas = []
            for lienzo, cara in self._todas(True, ancho, alto):
                arriba, abajo = cara.limites_verticales()
                cajas = [_caja(lienzo, cara, k) for k in ("carcasa", "oreja_izq", "oreja_der")]
                cajas.append(caja_barras(lienzo, cara))
                todas += cajas
                with self.subTest(tamano=(ancho, alto), estado=cara.estado):
                    self.assertLessEqual(arriba, min(c[1] for c in cajas) + 0.01)
                    self.assertGreaterEqual(abajo, max(c[3] for c in cajas) - 0.01)
            with self.subTest(tamano=(ancho, alto)):
                # El peor caso entre todas las expresiones queda justo al límite.
                self.assertLess(min(c[1] for c in todas) - arriba, alto * 0.02,
                                "sin desperdiciar sitio arriba")
        _, sin = _cara(False)
        self.assertIsNone(sin.limites_verticales())

    def test_sin_carcasa_abajo_del_todo_sin_pisar_la_cara(self):
        for ancho, alto in TAMANOS:
            for lienzo, cara in self._todas(False, ancho, alto):
                bx0, by0, bx1, by1 = caja_barras(lienzo, cara)
                rasgos = [cara._items[k] for k in ("boca", "ojo_izq", "ojo_der",
                                                   "arco_izq", "arco_der")]
                abajo = max(max(lienzo.items[i]["coords"][1::2]) for i in rasgos
                            if _visible(lienzo, i))
                with self.subTest(tamano=(ancho, alto), estado=cara.estado):
                    self.assertGreater(by0, abajo)
                    self.assertGreater(by1, alto * 0.95, "abajo del todo")
                    self.assertLessEqual(by1, alto * 0.985 + 0.5, "sin tocar el borde")
                    self.assertGreater(by0 - abajo, alto * 0.05,
                                       "hueco con la boca (medido: 6-8 % del alto)")

    def test_con_carcasa_hueco_amplio_incluso_inclinada(self):
        """Antes 27 px a 1280×720 (0,038 del alto); ahora ×2,75 en recto, y la
        cabeza inclinada de «pensando» tampoco se acerca a las barras."""
        for ancho, alto in TAMANOS:
            for lienzo, cara in self._todas(True, ancho, alto):
                g = cara._geo
                by0 = caja_barras(lienzo, cara)[1]
                abajo = max(_caja(lienzo, cara, k)[3]
                            for k in ("carcasa", "oreja_izq", "oreja_der"))
                with self.subTest(tamano=(ancho, alto), estado=cara.estado):
                    self.assertGreater(by0 - (g.centro_y + g.cabeza_alto / 2), alto * 0.10)
                    self.assertGreater(by0 - abajo, alto * 0.06)

    def test_cabeza_y_barras_son_un_bloque_centrado(self):
        """Con la cabeza recta, el bloque cabeza + hueco + barras está centrado
        en la ventana: no pesa arriba ni deja el tercio inferior vacío."""
        for ancho, alto in TAMANOS:
            lienzo, cara = _cara(True, ancho, alto, "escuchando", funcional="escuchando",
                                 escucha=1.0)
            cara.fijar(funcional="escuchando", expresion="reposo")   # sin inclinación
            for _ in range(4):
                cara.asentar()
                cara._anim.inclinacion = 0.0
                cara._inicio = __import__("time").monotonic()
                cara.dibujar()
            g = cara._geo
            maximo = g.unidad * cara.perfil.barras.alto_maximo
            arriba = g.centro_y - g.cabeza_alto / 2
            abajo = caja_barras(lienzo, cara)[1] + maximo
            with self.subTest(tamano=(ancho, alto)):
                self.assertAlmostEqual((arriba + abajo) / 2, alto / 2, delta=alto * 0.01)

    def test_no_giran_ni_respiran_con_la_cabeza(self):
        _, recta = _cara(True, estado="escuchando", escucha=0.5)
        lienzo, curiosa = _cara(True, estado="pensando", funcional="escuchando", escucha=0.5)
        self.assertEqual(len({round(sum(lienzo.items[i]["coords"][1::2]) / 2, 4)
                              for i in curiosa._barras_items}), 1,
            "con la cabeza inclinada, las barras siguen en horizontal")


    def test_todos_los_estados_se_dibujan_sin_fallar(self):
        for estado in EXPRESIONES:
            for voz in (0.0, 1.0):
                with self.subTest(estado=estado, voz=voz):
                    _cara(False, estado=estado, voz=voz)


class TextosDeLaAplicacionTest(unittest.TestCase):
    """Sin carcasa la cara usa la ventana entera: no se escribe encima."""

    def setUp(self):
        try:
            from emotibot.app import TEXTOS, textos_visibles
        except ImportError as error:          # sin tkinter u otra dependencia
            self.skipTest(f"no se puede importar la aplicación: {error}")
        self.textos, self.visibles = TEXTOS, textos_visibles

    def test_con_carcasa_se_ven(self):
        self.assertEqual(self.visibles(True, False, True, True), set(self.textos))
        self.assertNotIn("metricas", self.visibles(True, False, False, True))

    def test_sin_carcasa_no_se_ve_ninguno(self):
        for metricas in (True, False):
            for controles in (True, False):
                self.assertEqual(self.visibles(False, False, metricas, controles), set())

    def test_la_depuracion_activa_se_ve_siempre(self):
        """B2: si la transcripción se está mostrando, tiene que verse."""
        self.assertEqual(self.visibles(False, True, True, True), {"depuracion"})
        self.assertIn("depuracion", self.visibles(True, True, False, False))


if __name__ == "__main__":
    unittest.main()
