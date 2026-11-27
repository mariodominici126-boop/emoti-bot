"""Los textos de la aplicación, medidos en Tk real: ni fuera ni encima.

En el peor caso —todos los textos visibles y el detalle a dos líneas—, en
cinco tamaños y con o sin la fila de teclas:
- ningún texto se sale de la ventana;
- ninguno se pisa con otro;
- ninguno entra en la franja del rostro (cabeza inclinada y barras
  incluidas): el nombre y el creador quedan encima, el resto debajo;
- el estado, el detalle, la privacidad y la depuración nunca se quitan;
- sin la fila de teclas, lo de abajo llega al borde: no queda franja muerta;
- la barra lateral del directorio no pisa ningún texto y su contenido cabe.

Se usa el mismo código que la aplicación (disposicion_textos.colocar,
crear_cara, PanelDirectorio). Sin entorno gráfico, se salta.
"""
import datetime as dt
import unittest

from emotibot import disposicion_textos
from emotibot.ajustes import AjustesRostro
from emotibot.dialogo import directorio as mod_directorio
from emotibot.panel_directorio import PanelDirectorio
from emotibot.rostro import PALETA, crear_cara

try:
    import tkinter as tk
    _RAIZ = tk.Tk()
    _RAIZ.withdraw()
except Exception as error:                  # noqa: BLE001 (sin pantalla, sin Tk)
    _RAIZ, _MOTIVO = None, str(error)

TAMANOS = ((800, 480), (1024, 600), (1280, 720), (1920, 1080), (800, 600))
# Los rostros publicados: la tele y la cápsula tienen antenas y zócalo.
ROSTROS = ("hybrid_balanced", "tele", "capsula")
DETALLE_LARGO = ("No pude contactar con el proveedor remoto porque la cuota diaria se "
                 "agotó; seguiré con el guion local hasta mañana y te aviso si cambia "
                 "algo, así que puedes seguir hablándome con normalidad ahora mismo")[:160]
SIEMPRE = ("estado", "detalle", "privacidad", "depuracion")


def _contenidos(con_controles: bool) -> dict:
    from emotibot.app import AYUDA
    contenidos = {
        "nombre": ("EMOTI-BOT", PALETA.tinta),
        "creador": ("creado por el grupo Emoti", PALETA.tenue),
        "estado": ("ESCUCHANDO", PALETA.ojos_atento),
        "detalle": (DETALLE_LARGO, PALETA.tinta),
        "depuracion": ("STT · «hola, ¿qué tal estás hoy?» · 0,8 s", PALETA.ojos_atento),
        "privacidad": ("● micrófono abierto", PALETA.ojos_atento),
        "metricas": ("1,24 s · remoto · conversacion · Revisa config/crisis.json",
                     PALETA.tenue),
    }
    if con_controles:
        contenidos["controles"] = (AYUDA, PALETA.tenue)
    return contenidos


def _se_pisan(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


@unittest.skipIf(_RAIZ is None, "sin entorno gráfico")
class TextosEnLaVentanaTest(unittest.TestCase):
    def _montar(self, ancho, alto, carcasa=True, rostro="hybrid_balanced"):
        lienzo = tk.Canvas(_RAIZ, width=ancho, height=alto)
        self.addCleanup(lienzo.destroy)
        lienzo.configure(width=ancho, height=alto)
        # winfo_* de un lienzo sin mostrar no sirven: la cara lee el tamaño así.
        lienzo.winfo_width = lambda: ancho
        lienzo.winfo_height = lambda: alto
        cara = crear_cara(lienzo, AjustesRostro(carcasa=carcasa, perfil=rostro))
        cara.dibujar()
        items = {clave: lienzo.create_text(0, 0, text="")
                 for clave in disposicion_textos.ARRIBA + disposicion_textos.ABAJO}
        return lienzo, cara, items

    def test_peor_caso_sin_salirse_ni_pisarse(self):
        for rostro, (ancho, alto) in [(r, t) for r in ROSTROS for t in TAMANOS]:
            for con_controles in (True, False):
                lienzo, cara, items = self._montar(ancho, alto, rostro=rostro)
                limites = cara.limites_verticales()
                cajas = disposicion_textos.colocar(
                    lienzo, items, _contenidos(con_controles), ancho, alto, limites)
                with self.subTest(rostro=rostro, tamano=(ancho, alto), controles=con_controles):
                    for clave in SIEMPRE:
                        self.assertIn(clave, cajas, f"{clave} no puede quitarse")
                    self.assertEqual(lienzo.itemcget(items["detalle"], "text"),
                                     DETALLE_LARGO, "el detalle se muestra entero")
                    for clave, caja in cajas.items():
                        self.assertTrue(0 <= caja[0] and caja[2] <= ancho
                                        and 0 <= caja[1] and caja[3] <= alto,
                                        f"{clave} se sale de la ventana: {caja}")
                        if clave in disposicion_textos.ARRIBA:
                            self.assertLessEqual(caja[3], limites[0], f"{clave} pisa el rostro")
                        else:
                            self.assertGreaterEqual(caja[1], limites[1], f"{clave} pisa el rostro")
                    claves = list(cajas)
                    for i, a in enumerate(claves):
                        for b in claves[i + 1:]:
                            self.assertFalse(_se_pisan(cajas[a], cajas[b]),
                                             f"{a} pisa {b}: {cajas[a]} {cajas[b]}")

    def test_detalle_largo_a_tamano_completo_ocupa_dos_lineas(self):
        """El caso de prueba es de verdad el peor: a tamaño completo el
        detalle no cabe en una línea en ningún tamaño."""
        for ancho, alto in TAMANOS:
            lienzo = tk.Canvas(_RAIZ, width=ancho, height=alto)
            self.addCleanup(lienzo.destroy)
            escala = min(ancho, alto)
            una = lienzo.bbox(lienzo.create_text(
                0, 0, anchor="n", text="Una línea",
                font=(disposicion_textos.FUENTE, int(escala * disposicion_textos.TAMANO["detalle"]))))
            dos = lienzo.bbox(lienzo.create_text(
                0, 0, anchor="n", text=DETALLE_LARGO,
                width=int(ancho * disposicion_textos.ANCHO_MAXIMO["detalle"]),
                font=(disposicion_textos.FUENTE, int(escala * disposicion_textos.TAMANO["detalle"]))))
            with self.subTest(tamano=(ancho, alto)):
                self.assertGreater(dos[3] - dos[1], (una[3] - una[1]) * 1.6)

    def test_caso_normal_conserva_el_aviso_y_letra_legible(self):
        """Sin depuración y con un detalle corto, la línea de métricas —donde
        va «Revisa config/crisis.json»— se ve siempre, y el estado no baja de
        9 puntos. Si algo cede, es la fila de teclas."""
        for rostro, (ancho, alto) in [(r, t) for r in ROSTROS for t in TAMANOS]:
            lienzo, cara, items = self._montar(ancho, alto, rostro=rostro)
            contenidos = _contenidos(True)
            contenidos.pop("depuracion")
            contenidos["detalle"] = ("Pulsa ESPACIO y háblame.", PALETA.tinta)
            contenidos["metricas"] = ("Revisa config/crisis.json", PALETA.tenue)
            cajas = disposicion_textos.colocar(lienzo, items, contenidos, ancho, alto,
                                               cara.limites_verticales())
            letra = int(lienzo.itemcget(items["estado"], "font").split()[-1])
            with self.subTest(rostro=rostro, tamano=(ancho, alto)):
                self.assertIn("metricas", cajas)
                self.assertGreaterEqual(letra, 9)
                self.assertLessEqual(set(contenidos) - set(cajas), {"controles"})

    def test_sin_fila_de_teclas_no_queda_franja_muerta(self):
        for ancho, alto in TAMANOS:
            lienzo, cara, items = self._montar(ancho, alto)
            cajas = disposicion_textos.colocar(lienzo, items, _contenidos(False),
                                               ancho, alto, cara.limites_verticales())
            self.assertNotIn("controles", cajas)
            fondo = max(c[3] for c in cajas.values())
            with self.subTest(tamano=(ancho, alto)):
                self.assertGreater(fondo, alto * (1 - disposicion_textos.MARGEN) - 3)
                self.assertEqual(lienzo.itemcget(items["controles"], "state"), "hidden")

    def test_sin_carcasa_solo_la_depuracion_y_dentro(self):
        for ancho, alto in TAMANOS:
            lienzo, cara, items = self._montar(ancho, alto, carcasa=False)
            contenidos = {"depuracion": ("STT · «hola» · 0,8 s", PALETA.ojos_atento)}
            cajas = disposicion_textos.colocar(lienzo, items, contenidos, ancho, alto, None)
            with self.subTest(tamano=(ancho, alto)):
                self.assertEqual(list(cajas), ["depuracion"])
                caja = cajas["depuracion"]
                self.assertTrue(0 <= caja[1] and caja[3] <= alto and 0 <= caja[0]
                                and caja[2] <= ancho)

    def test_la_barra_lateral_no_pisa_ningun_texto(self):
        directorio = mod_directorio.cargar("República Dominicana")
        for ancho, alto in TAMANOS:
            lienzo, cara, items = self._montar(ancho, alto)
            limites = cara.limites_verticales()
            cajas = disposicion_textos.colocar(lienzo, items, _contenidos(True),
                                               ancho, alto, limites)
            panel = PanelDirectorio(lienzo, PALETA, directorio)
            panel.mostrar()
            panel.actualizar(ancho, alto, 0.0, dt.time(3, 0), franja=limites)
            caja_panel = lienzo.bbox("directorio")
            with self.subTest(tamano=(ancho, alto)):
                self.assertIsNotNone(caja_panel)
                for clave, caja in cajas.items():
                    self.assertFalse(_se_pisan(caja_panel, caja), f"la barra pisa {clave}")
                fondo = next(i for i in lienzo.find_withtag("directorio")
                             if lienzo.type(i) == "polygon")
                fx0, fy0, fx1, fy1 = lienzo.bbox(fondo)
                for item in lienzo.find_withtag("directorio"):
                    x0, y0, x1, y1 = lienzo.bbox(item)
                    self.assertTrue(fx0 <= x0 and x1 <= fx1 and fy0 <= y0 and y1 <= fy1,
                                    "el contenido de la barra cabe en ella")
                self.assertTrue(0 <= fx0 and fx1 <= ancho and 0 <= fy0 and fy1 <= alto)


if __name__ == "__main__":
    unittest.main()
