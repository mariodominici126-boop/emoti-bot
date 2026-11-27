"""Prueba del rostro sin entorno gráfico, con un lienzo simulado.

No comprueba que se vea bonito —eso se juzga mirándolo— pero sí que todas las
figuras existan, que las coordenadas tengan la aridad correcta y que ningún
estado provoque un error. El rostro se dibuja decenas de veces por segundo
durante horas: un fallo en una rama poco frecuente aparecería en medio de una
conversación.
"""
import math
import unittest

from emotibot.rostro import EXPRESIONES
from emotibot.rostro.cara import Cara
from emotibot.rostro.formas import arco, rectangulo_redondeado, rotar
from emotibot.rostro.paleta import PALETA, mezclar


def barras_visibles(lienzo, cara) -> list[bool]:
    return [lienzo.items[i]["config"].get("state") != "hidden"
            for i in cara._barras_items]


def _caja_barra(lienzo, item) -> tuple[float, float, float, float]:
    """Caja de una barra: línea vertical con extremos redondos (cápsula), así
    que mide medio grosor más por cada lado que su trazo."""
    datos = lienzo.items[item]
    r = float(datos["config"].get("width", 1)) / 2
    xs, ys = datos["coords"][0::2], datos["coords"][1::2]
    return min(xs) - r, min(ys) - r, max(xs) + r, max(ys) + r


def alturas_barras(lienzo, cara) -> list[float]:
    return [c[3] - c[1] for c in (_caja_barra(lienzo, i) for i in cara._barras_items)]


def caja_barras(lienzo, cara) -> tuple[float, float, float, float]:
    cajas = [_caja_barra(lienzo, i) for i in cara._barras_items]
    return (min(c[0] for c in cajas), min(c[1] for c in cajas),
            max(c[2] for c in cajas), max(c[3] for c in cajas))


class LienzoSimulado:
    """Imita lo justo de tkinter.Canvas que usa el rostro."""

    def __init__(self, ancho=800, alto=480):
        self._ancho, self._alto = ancho, alto
        self._siguiente = 1
        self.items: dict[int, dict] = {}
        self.borrados = 0

    def winfo_width(self):
        return self._ancho

    def winfo_height(self):
        return self._alto

    def _crear(self, tipo, coords, config=None):
        identificador = self._siguiente
        self._siguiente += 1
        # Se guardan también las opciones de creación (p. ej. state=hidden).
        self.items[identificador] = {"tipo": tipo, "coords": list(coords),
                                     "config": dict(config or {})}
        return identificador

    def create_oval(self, *coords, **kwargs):
        assert len(coords) == 4, f"oval necesita 4 coordenadas, dieron {len(coords)}"
        return self._crear("oval", coords, kwargs)

    def create_arc(self, *coords, **kwargs):
        assert len(coords) == 4
        return self._crear("arc", coords)

    def create_line(self, *coords, **kwargs):
        planas = coords[0] if len(coords) == 1 and isinstance(coords[0], (list, tuple)) else coords
        assert len(planas) >= 4 and len(planas) % 2 == 0
        return self._crear("line", planas, kwargs)

    def create_polygon(self, *coords, **kwargs):
        planas = coords[0] if len(coords) == 1 and isinstance(coords[0], (list, tuple)) else coords
        assert len(planas) >= 6 and len(planas) % 2 == 0
        return self._crear("polygon", planas, kwargs)

    def create_text(self, x, y, **kwargs):
        return self._crear("text", (x, y), kwargs)

    def coords(self, identificador, *valores):
        assert identificador in self.items, "coords sobre un item inexistente"
        planas = valores[0] if len(valores) == 1 and isinstance(valores[0], (list, tuple)) else valores
        tipo = self.items[identificador]["tipo"]
        if tipo in ("oval", "arc"):
            assert len(planas) == 4, f"{tipo} necesita 4 coordenadas"
        elif tipo == "text":
            assert len(planas) == 2
        else:
            assert len(planas) >= 4 and len(planas) % 2 == 0, \
                f"{tipo} con {len(planas)} coordenadas"
        for valor in planas:
            assert isinstance(valor, (int, float)), f"coordenada no numérica: {valor!r}"
            assert valor == valor, "coordenada NaN"
            assert abs(valor) < 1e6, f"coordenada fuera de rango: {valor}"
        self.items[identificador]["coords"] = list(planas)

    def itemconfigure(self, identificador, **kwargs):
        assert identificador in self.items, "itemconfigure sobre un item inexistente"
        if "state" in kwargs:
            assert kwargs["state"] in ("normal", "hidden", "disabled")
        if "width" in kwargs:
            assert kwargs["width"] >= 1, "grosor de línea inválido"
        for clave in ("fill", "outline"):
            if clave in kwargs and kwargs[clave]:
                valor = kwargs[clave]
                assert valor.startswith("#") and len(valor) == 7, \
                    f"color mal formado: {valor!r}"
        self.items[identificador]["config"].update(kwargs)

    itemconfig = itemconfigure

    def delete(self, _etiqueta):
        self.borrados += 1


class PaletaTest(unittest.TestCase):
    def test_mezcla_produce_hex_valido(self):
        for proporcion in (0.0, 0.25, 0.5, 1.0):
            color = mezclar(PALETA.fondo, PALETA.ojos, proporcion)
            self.assertRegex(color, r"^#[0-9a-f]{6}$")

    def test_mezcla_recorta_fuera_de_rango(self):
        self.assertRegex(mezclar(PALETA.fondo, PALETA.ojos, -3.0),
                         r"^#[0-9a-f]{6}$")
        self.assertRegex(mezclar(PALETA.fondo, PALETA.ojos, 9.0),
                         r"^#[0-9a-f]{6}$")


class FormasTest(unittest.TestCase):
    def test_rectangulo_redondeado_cierra_y_cabe_en_la_caja(self):
        puntos = rectangulo_redondeado(10, 20, 110, 80, 15)
        self.assertEqual(len(puntos) % 2, 0)
        self.assertGreaterEqual(len(puntos) // 2, 12)
        xs, ys = puntos[0::2], puntos[1::2]
        self.assertGreaterEqual(min(xs), 9.9)
        self.assertLessEqual(max(xs), 110.1)
        self.assertGreaterEqual(min(ys), 19.9)
        self.assertLessEqual(max(ys), 80.1)

    def test_radio_se_limita_a_la_mitad_del_lado(self):
        """Un radio mayor que el lado deformaría la figura."""
        puntos = rectangulo_redondeado(0, 0, 40, 20, 999)
        xs, ys = puntos[0::2], puntos[1::2]
        self.assertLessEqual(max(xs), 40.1)
        self.assertLessEqual(max(ys), 20.1)

    def test_rotar_conserva_la_distancia_al_centro(self):
        import math
        x, y = rotar(10.0, 0.0, 0.0, 0.0, 90.0)
        self.assertAlmostEqual(math.hypot(x, y), 10.0, places=5)
        self.assertAlmostEqual(rotar(5.0, 7.0, 1.0, 2.0, 0.0)[0], 5.0)

    def test_arco_curva_hacia_arriba(self):
        puntos = arco(50, 50, 80, 10)
        ys = puntos[1::2]
        self.assertLess(min(ys), 50.0, "la altura positiva curva hacia arriba")


class CaraTest(unittest.TestCase):
    def test_dibuja_todos_los_estados_sin_fallar(self):
        lienzo = LienzoSimulado()
        cara = Cara(lienzo, PALETA)
        for estado in EXPRESIONES:
            cara.fijar_estado(estado)
            for paso in range(12):
                cara.fijar_nivel_voz((paso % 5) / 4.0)
                cara.fijar_nivel_escucha((paso % 3) / 2.0)
                cara.dibujar()
        self.assertGreater(len(lienzo.items), 14,
                           "deben existir carcasa, pantalla, ojos, boca…")

    def test_los_items_se_crean_una_sola_vez(self):
        """El prototipo hacía delete('all') y recreaba todo en cada fotograma."""
        lienzo = LienzoSimulado()
        cara = Cara(lienzo, PALETA)
        cara.dibujar()
        tras_primero = len(lienzo.items)
        for _ in range(40):
            cara.dibujar()
        self.assertEqual(len(lienzo.items), tras_primero,
                         "no debe crear figuras nuevas en cada fotograma")

    def test_tiene_las_piezas_de_la_cabeza(self):
        lienzo = LienzoSimulado()
        cara = Cara(lienzo, PALETA)
        cara.dibujar()
        for pieza in ("carcasa", "pantalla", "oreja_izq", "oreja_der",
                      "ceja_izq", "ceja_der", "ojo_izq", "ojo_der", "boca"):
            self.assertIn(pieza, cara._items, f"falta la pieza {pieza}")
        self.assertNotIn("rubor_izq", cara._items)
        self.assertNotIn("halo0", cara._items)

    def test_la_pantalla_queda_dentro_de_la_carcasa(self):
        """Si la pantalla se saliera del marco, la cabeza se vería rota."""
        lienzo = LienzoSimulado()
        cara = Cara(lienzo, PALETA)
        cara.fijar_estado("reposo")
        cara.dibujar()
        cara.asentar()
        cara.dibujar()

        def caja(clave):
            coords = lienzo.items[cara._items[clave]]["coords"]
            xs = coords[0::2]
            ys = coords[1::2]
            return min(xs), min(ys), max(xs), max(ys)

        cx0, cy0, cx1, cy1 = caja("carcasa")
        px0, py0, px1, py1 = caja("pantalla")
        self.assertGreater(px0, cx0)
        self.assertGreater(py0, cy0)
        self.assertLess(px1, cx1)
        self.assertLess(py1, cy1)

    def test_los_ojos_caben_en_la_pantalla(self):
        lienzo = LienzoSimulado()
        cara = Cara(lienzo, PALETA)
        for estado in ("reposo", "escuchando", "sin_entender"):
            cara.fijar_estado(estado)
            cara.dibujar()
            cara.asentar()
            cara.dibujar()
            pantalla = lienzo.items[cara._items["pantalla"]]["coords"]
            px0, px1 = min(pantalla[0::2]), max(pantalla[0::2])
            py0, py1 = min(pantalla[1::2]), max(pantalla[1::2])
            for lado in ("izq", "der"):
                ojo = lienzo.items[cara._items[f"ojo_{lado}"]]["coords"]
                self.assertGreaterEqual(min(ojo[0::2]), px0 - 1, estado)
                self.assertLessEqual(max(ojo[0::2]), px1 + 1, estado)
                self.assertGreaterEqual(min(ojo[1::2]), py0 - 1, estado)
                self.assertLessEqual(max(ojo[1::2]), py1 + 1, estado)


    def test_rehace_la_geometria_al_cambiar_de_tamano(self):
        lienzo = LienzoSimulado(800, 480)
        cara = Cara(lienzo, PALETA)
        cara.dibujar()
        lienzo._ancho, lienzo._alto = 1280, 720
        cara.dibujar()
        self.assertGreaterEqual(lienzo.borrados, 2)

    def test_boca_cerrada_sin_voz_y_abierta_con_voz(self):
        lienzo = LienzoSimulado()
        cara = Cara(lienzo, PALETA)
        cara.fijar_estado("hablando")
        cara.fijar_nivel_voz(0.0)
        # asentar(): los fotogramas de la prueba se generan en microsegundos,
        # así que la interpolación por tiempo real no avanzaría.
        for _ in range(5):
            cara.asentar()
            cara.dibujar()
        def alto_boca():
            coords = lienzo.items[cara._items["boca"]]["coords"]
            return max(coords[1::2]) - min(coords[1::2])

        cerrada = alto_boca()

        cara.fijar_nivel_voz(1.0)
        for _ in range(5):
            cara.asentar()
            cara.dibujar()
        abierta = alto_boca()
        self.assertGreater(abierta, cerrada * 2,
                           "con voz la boca debe abrirse de verdad")

        cara.fijar_nivel_voz(0.0)
        for _ in range(5):
            cara.asentar()
            cara.dibujar()
        self.assertLess(alto_boca(), abierta * 0.5,
                        "al callar la voz la boca debe cerrarse")

    def test_la_curva_de_la_boca_va_en_el_sentido_correcto(self):
        """Regresión (Fase 1C): «feliz» salía con la boca en ∩.

        Con la boca cerrada, sonrisa = centro MÁS BAJO que los extremos
        (en Tk la y crece hacia abajo); preocupación = centro más alto.
        """
        def centro_menos_extremos(estado):
            lienzo = LienzoSimulado()
            cara = Cara(lienzo, PALETA)
            cara.fijar_estado(estado)
            cara.fijar_nivel_voz(0.0)
            for _ in range(5):
                cara.asentar()
                cara.dibujar()
            coords = lienzo.items[cara._items["boca"]]["coords"]
            # La banda es borde superior (ida) + borde inferior (vuelta):
            # la primera mitad de los puntos es el borde superior.
            ys = coords[1::2][:len(coords) // 4]
            return ys[len(ys) // 2] - (ys[0] + ys[-1]) / 2

        self.assertGreater(centro_menos_extremos("feliz"), 1.0, "feliz sonríe")
        self.assertGreater(centro_menos_extremos("reposo"), 0.5, "reposo sonríe un poco")
        self.assertLess(centro_menos_extremos("preocupado"), 0.0,
                        "preocupado no sonríe")

    def test_las_barras_indican_el_microfono_abierto(self):
        """Los tres casos, y solo tres. Es el indicador de captación.

        - micrófono cerrado: no se dibuja nada;
        - abierto y en silencio: TODAS a la altura mínima, visible (se lee
          «escucho», no «apagado»);
        - abierto y con voz: la altura crece con el nivel real.
        """
        lienzo = LienzoSimulado()
        cara = Cara(lienzo, PALETA)
        self.assertEqual(len(cara._barras_items), 0)
        cara.fijar_estado("reposo")
        for _ in range(5):
            cara.asentar()
            cara.dibujar()
        self.assertEqual(len(cara._barras_items), 21)
        self.assertFalse(any(barras_visibles(lienzo, cara)), "cerrado: nada")

        cara.fijar_estado("escuchando")
        alturas = {}
        for nivel in (0.0, 0.3, 0.9):
            cara.fijar_nivel_escucha(nivel)
            for _ in range(20):
                cara.asentar()
                cara.dibujar()
            self.assertTrue(all(barras_visibles(lienzo, cara)))
            alturas[nivel] = alturas_barras(lienzo, cara)
        silencio = alturas[0.0]
        self.assertLess(max(silencio) - min(silencio), 0.01, "silencio: todas iguales")
        self.assertGreaterEqual(min(silencio), 4.0, "y a una altura visible")
        for nivel in (0.3, 0.9):
            self.assertTrue(all(a >= b - 0.01 for a, b in zip(alturas[nivel], silencio)))
        self.assertGreater(max(alturas[0.3]) - max(silencio), 4.0, "crece con el nivel")
        self.assertGreater(max(alturas[0.9]), max(alturas[0.3]) * 1.5)

        cara.fijar_estado("pensando")
        cara.dibujar()
        self.assertFalse(any(barras_visibles(lienzo, cara)), "al dejar de escuchar se van")
        self.assertEqual(cara._historial_escucha, [], "y no recuerdan nada")

    def test_las_barras_son_capsulas_verticales_y_simetricas(self):
        lienzo = LienzoSimulado()
        cara = Cara(lienzo, PALETA)
        cara.fijar_estado("escuchando")
        cara.fijar_nivel_escucha(0.7)
        for _ in range(20):
            cara.asentar()
            cara.dibujar()
        cajas = []
        for item in cara._barras_items:
            datos = lienzo.items[item]
            self.assertEqual(datos["tipo"], "line")
            self.assertEqual(datos["config"]["capstyle"], "round", "extremos redondos")
            xs = datos["coords"][0::2]
            self.assertEqual(xs[0], xs[1], "vertical")
            cajas.append(_caja_barra(lienzo, item))
        centros = {round((c[1] + c[3]) / 2, 6) for c in cajas}
        self.assertEqual(len(centros), 1, "simétricas respecto a una línea central")
        for c in cajas:
            self.assertGreater(c[3] - c[1], c[2] - c[0], "verticales")
        alturas = [c[3] - c[1] for c in cajas]
        self.assertEqual([round(a, 6) for a in alturas],
                         [round(a, 6) for a in reversed(alturas)], "izquierda = derecha")
        self.assertEqual(alturas.index(max(alturas)), 10, "la más alta, la central")

    def test_las_barras_degradan_dentro_de_la_paleta(self):
        lienzo = LienzoSimulado()
        cara = Cara(lienzo, PALETA)
        cara.fijar_estado("escuchando")
        cara.dibujar()
        colores = [lienzo.items[i]["config"]["fill"] for i in cara._barras_items]
        barras = cara.perfil.barras
        self.assertEqual(colores[10], getattr(PALETA, barras.color_centro))
        self.assertEqual(colores[0], getattr(PALETA, barras.color_extremos))
        self.assertEqual(colores[-1], colores[0])
        self.assertEqual(colores[5], mezclar(getattr(PALETA, barras.color_centro),
                                             getattr(PALETA, barras.color_extremos), 0.5))
        self.assertGreater(len(set(colores)), 8, "degradado barra a barra")

    def test_sin_banda_de_reflejo_en_la_pantalla(self):
        """En Canvas se leía como una línea en la frente, en todos los estados."""
        lienzo = LienzoSimulado()
        cara = Cara(lienzo, PALETA)
        for estado in ("reposo", "escuchando", "feliz"):
            cara.fijar_estado(estado)
            cara.dibujar()
            self.assertNotIn("brillo_pantalla", cara._items)
            colores = {d["config"].get("fill") for d in lienzo.items.values()}
            self.assertNotIn(PALETA.pantalla_brillo, colores)

    def test_no_quedan_ondas_flotando(self):
        lienzo = LienzoSimulado()
        cara = Cara(lienzo, PALETA)
        cara.fijar_estado("escuchando")
        for _ in range(5):
            cara.asentar()
            cara.dibujar()
        self.assertNotIn("onda0", cara._items)

    def test_lienzo_minimo_no_rompe(self):
        lienzo = LienzoSimulado(1, 1)
        cara = Cara(lienzo, PALETA)
        for _ in range(10):
            cara.dibujar()


if __name__ == "__main__":
    unittest.main()
