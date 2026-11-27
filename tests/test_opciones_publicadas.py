"""D10, tanda 2: las opciones publicadas de cada eje.

Verificación POR EJES, no por combinaciones (3 × 2 × 5 × 5 × 2 no tiene
sentido probarlas todas: la tanda 1 demostró que los ejes son independientes):

- Rostros: comparten la GRAMÁTICA de expresión y el marco; solo cambia el
  aspecto. Los colores de estado conservan su significado. Todos caben.
- Voces: cada una con su propia velocidad, y su atribución en el README.
- Techo ÚNICO de personalidad + estilo: ninguna combinación publicada se pasa,
  y una opción nueva que se pase hace fallar la batería.
- §14.5 contra CADA opción publicada de cada eje, no solo la sintética.
"""
import colorsys
import dataclasses
import itertools
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from emotibot import ajustes as mod_ajustes
from emotibot import identidad as mod_identidad
from emotibot import perfil_usuario as pu
from emotibot import rutas
from emotibot.dialogo import Gestor, Tipo
from emotibot.dialogo import directorio as mod_directorio
from emotibot.dialogo import gestor as mod_gestor
from emotibot.dialogo.intencion import Intencion
from emotibot.dialogo.seguridad import Guardia, cargar_recursos
from emotibot.ia.base import Respuesta
from emotibot.ia.orquestador import Orquestador
from emotibot.rostro import EXPRESIONES
from emotibot.rostro import cara as mod_cara
from emotibot.rostro import perfil as mod_perfil
from tests.test_rostro import LienzoSimulado, caja_barras

ROSTROS = sorted(p.stem for p in mod_perfil.DIRECTORIO.glob("*.json"))
DEFECTO = "hybrid_balanced"
TAMANOS = ((800, 480), (1280, 720), (1024, 600), (800, 600))

# La gramática de expresión: cómo se traduce cada parámetro de la expresión
# (estados.py) a geometría. Idéntica en todos los rostros: así lo validado en
# C4 con un rostro vale para los demás.
GRAMATICA = {
    "cejas": ("curva", "subida", "giro"),
    "alegria": ("umbral_apertura", "altura", "altura_cierre", "bajada"),
    "boca": ("apertura", "curva", "ensanche_sonrisa"),
    "ojos": ("mirada_x", "mirada_y", "alto_minimo"),
    "rasgos": ("y_ojos", "y_ceja", "y_boca"),
}
# El marco no es el rostro: la carcasa es dónde va montada la pantalla.
# El modo sin carcasa y el indicador del micrófono son iguales en todos. La
# cabeza o el mueble (tamaño, tipo, pantalla) es aspecto de cada rostro; la
# carcasa sí/no es un ajuste aparte (rostro.carcasa).
# Canales que un rostro puede no tener: la sección entera falta (null) y
# entonces tampoco cuentan los campos de otras secciones que son de ese
# canal. Los canales que SÍ tiene significan lo mismo en los tres.
CANALES_OPCIONALES = {"cejas": {("cejas", c) for c in GRAMATICA["cejas"]} | {("rasgos", "y_ceja")}}
MARCO = ("sin_carcasa", "barras")
COLORES_MARCO = ("fondo", "tinta", "tenue")
COLORES_ESTADO = ("ojos", "ojos_feliz", "ojos_atento", "ojos_preocupado", "ojos_error")


def _cara(rostro, carcasa=True, ancho=800, alto=480, estado="reposo", voz=0.0, escucha=0.0,
          funcional=None):
    lienzo = LienzoSimulado(ancho, alto)
    cara = mod_cara.Cara(lienzo, carcasa=carcasa, perfil=mod_perfil.cargar(rostro))
    if funcional:
        cara.fijar(funcional=funcional, expresion=estado)
    else:
        cara.fijar_estado(estado)
    cara.fijar_nivel_voz(voz)
    cara.fijar_nivel_escucha(escucha)
    for _ in range(4):
        cara.asentar()
        cara._anim.parpadeo = 1.0
        cara._inicio = mod_cara.time.monotonic()
        cara.dibujar()
    return lienzo, cara


def _tono(color):
    r, g, b = (int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return colorsys.rgb_to_hls(r, g, b)[0] * 360


# ======================================================================= rostros
class RostrosTest(unittest.TestCase):
    def test_hay_tres_y_el_defecto_sigue_siendo_el_de_hoy(self):
        self.assertEqual(ROSTROS, ["capsula", "hybrid_balanced", "tele"])
        self.assertEqual(pu.POR_DEFECTO.rostro, DEFECTO)

    def test_misma_gramatica_y_mismo_marco(self):
        base = mod_perfil.cargar(DEFECTO)
        for rostro in ROSTROS:
            p = mod_perfil.cargar(rostro)
            ausentes = set().union(*(campos for canal, campos in CANALES_OPCIONALES.items()
                                     if getattr(p, canal) is None))
            for seccion, campos in GRAMATICA.items():
                for campo in campos:
                    if (seccion, campo) in ausentes:
                        continue
                    with self.subTest(rostro=rostro, campo=f"{seccion}.{campo}"):
                        self.assertEqual(getattr(getattr(p, seccion), campo),
                                         getattr(getattr(base, seccion), campo))
            for seccion in MARCO:
                with self.subTest(rostro=rostro, seccion=seccion):
                    self.assertEqual(getattr(p, seccion), getattr(base, seccion))
            for color in COLORES_MARCO:
                with self.subTest(rostro=rostro, color=color):
                    self.assertEqual(getattr(p.colores, color), getattr(base.colores, color))

    def test_los_colores_de_estado_conservan_su_significado(self):
        """Cada color de estado se queda en la familia del de hoy (±25° de
        tono) y los cinco se distinguen entre sí."""
        base = mod_perfil.cargar(DEFECTO).colores
        for rostro in ROSTROS:
            c = mod_perfil.cargar(rostro).colores
            tonos = []
            for nombre in COLORES_ESTADO:
                diferencia = abs(_tono(getattr(c, nombre)) - _tono(getattr(base, nombre)))
                diferencia = min(diferencia, 360 - diferencia)
                with self.subTest(rostro=rostro, color=nombre):
                    self.assertLess(diferencia, 25)
                tonos.append(getattr(c, nombre))
            for a, b in itertools.combinations(tonos, 2):
                distancia = sum(abs(int(a[i:i + 2], 16) - int(b[i:i + 2], 16)) for i in (1, 3, 5))
                with self.subTest(rostro=rostro, par=(a, b)):
                    self.assertGreater(distancia, 40)

    def test_la_gramatica_dibujada_es_la_misma(self):
        """Con cada expresión, lo que significa algo sale igual en los tres:
        ángulo de las cejas, curva de la boca (relativa al tamaño), ojos en
        arco o no, boca abierta al hablar o no, destellos o no."""
        import math

        def eje(coords):
            """Ángulo del eje principal de la figura: sirve igual para una
            cápsula suave que para una tira de píxeles en escalera."""
            xs, ys = coords[0::2], coords[1::2]
            mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
            sxx = sum((x - mx) ** 2 for x in xs)
            syy = sum((y - my) ** 2 for y in ys)
            sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
            return math.degrees(0.5 * math.atan2(2 * sxy, sxx - syy))

        def flecha(coords, ref):
            """Centro menos extremos de la boca (positivo = sonrisa), relativo
            al tamaño: media de los vértices del tercio central menos la de
            los del 15 % de cada extremo."""
            pares = list(zip(coords[0::2], coords[1::2]))
            x0, x1 = min(x for x, _ in pares), max(x for x, _ in pares)
            w = x1 - x0
            centro = [y for x, y in pares if x0 + w / 3 <= x <= x1 - w / 3]
            lados = [y for x, y in pares if x <= x0 + 0.15 * w or x >= x1 - 0.15 * w]
            return (sum(centro) / len(centro) - sum(lados) / len(lados)) / ref

        def lectura(rostro, estado):
            lienzo, cara = _cara(rostro, estado=estado)
            ceja = lienzo.items[cara._items["ceja_izq"]]
            angulo = None if ceja["config"].get("state") == "hidden" else eje(ceja["coords"])
            boca = lienzo.items[cara._items["boca"]]
            if boca["config"].get("outline", ""):
                # Boca entreabierta (la exhalación guiada): no hay curva que
                # leer; su contorno redondeado es aspecto.
                curva = "abierta"
            else:
                curva = flecha(boca["coords"], cara._geo.ref_alto)
            arco = lienzo.items[cara._items["arco_izq"]]["config"].get("state") != "hidden"
            destellos = any(lienzo.items[i]["config"].get("state") != "hidden"
                            for i in cara._destellos_items)
            l2, c2 = _cara(rostro, estado=estado, funcional="hablando", voz=1.0)
            abierta = l2.items[c2._items["boca"]]["config"].get("outline", "") != ""
            return angulo, curva, arco, destellos, abierta

        for estado in EXPRESIONES:
            base = lectura(DEFECTO, estado)
            for rostro in ROSTROS:
                otra = lectura(rostro, estado)
                pixeles = mod_perfil.cargar(rostro).trazo.estilo == "pixeles"
                with self.subTest(estado=estado, rostro=rostro):
                    # La rejilla de píxeles cuantiza el ángulo (~3°). Un rostro
                    # sin cejas no tiene ese canal: se comprueban los demás.
                    cejas = mod_perfil.cargar(rostro).cejas
                    if cejas is None:
                        self.assertIsNone(otra[0], "sin cejas: ninguna ceja visible")
                    elif cejas.ceno < 1 and EXPRESIONES[estado].ceja_angulo < 0:
                        # Sin ceño (tele): el interior abajo no se dibuja.
                        # Las dos cejas van paralelas (solo las inclina la
                        # cabeza): nunca en V, que se leyó como rabia.
                        lienzo, cara = _cara(rostro, estado=estado)
                        izq, der = (eje(lienzo.items[cara._items[f"ceja_{l}"]]["coords"])
                                    for l in ("izq", "der"))
                        self.assertAlmostEqual(izq, der, delta=4.0, msg="cejas paralelas")
                    else:
                        self.assertAlmostEqual(otra[0], base[0], delta=4.0 if pixeles else 2.0,
                                               msg="ángulo de ceja")
                    if base[1] == "abierta":
                        self.assertEqual(otra[1], "abierta")
                    elif abs(base[1]) > 0.004:
                        self.assertEqual(otra[1] > 0, base[1] > 0, "curva de boca: signo")
                    self.assertEqual(otra[2:], base[2:])

    def test_todos_caben(self):
        piezas = ["ceja_izq", "ceja_der", "boca", "ojo_izq", "ojo_der", "arco_izq", "arco_der",
                  "signo_trazo", "signo_punto"]
        for rostro in ROSTROS:
            for ancho, alto in TAMANOS:
                for estado in EXPRESIONES:
                    for carcasa in (True, False):
                        lienzo, cara = _cara(rostro, carcasa, ancho, alto, estado, voz=1.0,
                                             escucha=1.0)
                        items = [cara._items[k] for k in piezas] + list(cara._celdas_signo)
                        items += [cara._items[k] for k in ("parpado_izq", "parpado_der")
                                  if k in cara._items]
                        if carcasa and cara._geo.estatico:
                            # Mueble estático: la pantalla es el área de rostro.
                            a = cara.area_de_rostro()
                            caja = (a[0] - 1, a[1] - 1, a[2] + 1, a[3] + 1)
                        elif carcasa:
                            p = lienzo.items[cara._items["pantalla"]]["coords"]
                            caja = (min(p[0::2]) - 1, min(p[1::2]) - 1,
                                    max(p[0::2]) + 1, max(p[1::2]) + 1)
                        else:
                            items += list(cara._destellos_items)
                            caja = (ancho * 0.015, alto * 0.015, ancho * 0.985, alto * 0.985)
                        for item in items:
                            if lienzo.items[item]["config"].get("state") == "hidden":
                                continue
                            co = lienzo.items[item]["coords"]
                            with self.subTest(rostro=rostro, tamano=(ancho, alto),
                                              estado=estado, carcasa=carcasa, item=item):
                                self.assertTrue(caja[0] <= min(co[0::2]) and max(co[0::2]) <= caja[2]
                                                and caja[1] <= min(co[1::2])
                                                and max(co[1::2]) <= caja[3])

    def test_sin_cejas_preocupado_se_distingue(self):
        """La cápsula no tiene cejas: «preocupado» se dice con el ojo (un
        párpado tapa más por fuera que por dentro y el ojo se achata) y sigue
        siendo distinto del reposo. «Te escucho» no activa la asimetría de la
        curiosidad (ya no la usa ninguna expresión: «curioso» se quitó el
        27-11-2026)."""
        import math
        sin_cejas = [r for r in ROSTROS if mod_perfil.cargar(r).cejas is None]
        self.assertEqual(sin_cejas, ["capsula"])

        def lectura(rostro, estado, carcasa):
            lienzo, cara = _cara(rostro, carcasa=carcasa, estado=estado)
            def caja(clave):
                co = lienzo.items[cara._items[clave]]["coords"]
                return min(co[0::2]), min(co[1::2]), max(co[0::2]), max(co[1::2])
            izq, der = caja("ojo_izq"), caja("ojo_der")
            asimetria = (der[3] - der[1]) / (izq[3] - izq[1])
            parpados = []
            for lado, signo in (("izq", -1), ("der", 1)):
                item = lienzo.items[cara._items[f"parpado_{lado}"]]
                if item["config"].get("state") == "hidden":
                    continue
                pares = list(zip(item["coords"][0::2], item["coords"][1::2]))
                # Los dos vértices de abajo: el de fuera y el de dentro.
                abajo = sorted(pares, key=lambda q: q[1])[-2:]
                fuera = max(abajo, key=lambda q: q[0] * signo)
                dentro = min(abajo, key=lambda q: q[0] * signo)
                parpados.append(fuera[1] - dentro[1])
            return asimetria, parpados, izq[3] - izq[1]

        for rostro in sin_cejas:
            for carcasa in (True, False):
                reposo = lectura(rostro, "reposo", carcasa)
                preocupado = lectura(rostro, "preocupado", carcasa)
                escucha = lectura(rostro, "escuchando", carcasa)
                with self.subTest(rostro=rostro, carcasa=carcasa):
                    self.assertTrue(math.isclose(reposo[0], 1.0, rel_tol=0.01))
                    self.assertEqual(reposo[1], [], "reposo sin párpado")
                    self.assertEqual(len(preocupado[1]), 2, "preocupado: párpados")
                    self.assertTrue(all(d > 0 for d in preocupado[1]),
                                    "el párpado cae hacia fuera")
                    self.assertTrue(math.isclose(preocupado[0], 1.0, rel_tol=0.01))
                    self.assertTrue(math.isclose(escucha[0], 1.0, rel_tol=0.01),
                                    "te escucho no es curiosidad")

    def test_la_capsula_tiene_ojos_sin_pupila(self):
        for carcasa in (True, False):
            for estado in ("reposo", "sin_entender", "preocupado", "hablando"):
                lienzo, cara = _cara("capsula", carcasa=carcasa, estado=estado)
                for lado in ("izq", "der"):
                    with self.subTest(carcasa=carcasa, estado=estado, lado=lado):
                        self.assertEqual(lienzo.items[cara._items[f"punto_{lado}"]]["config"]
                                         .get("state"), "hidden")
                        self.assertEqual(lienzo.items[cara._items[f"ceja_{lado}"]]["config"]
                                         .get("state"), "hidden")

    def test_el_mueble_es_estatico(self):
        """Se dibuja al crear la cara y ningún fotograma lo vuelve a tocar:
        ni coords ni itemconfigure sobre sus figuras."""
        for rostro in ROSTROS:
            if mod_perfil.cargar(rostro).mueble.tipo == "cabeza":
                continue
            lienzo, cara = _cara(rostro)
            mueble = set(cara._mueble_items)
            self.assertGreater(len(mueble), 15, "bandas, antenas, orejas, mandos…")
            antes = {i: (list(lienzo.items[i]["coords"]), dict(lienzo.items[i]["config"]))
                     for i in mueble}
            tocados = []
            coords, configura = lienzo.coords, lienzo.itemconfigure
            lienzo.coords = lambda i, *v: (tocados.append(i), coords(i, *v))[1]
            lienzo.itemconfigure = lambda i, **k: (tocados.append(i), configura(i, **k))[1]
            for estado in list(EXPRESIONES) * 2:
                cara.fijar_estado(estado)
                cara.fijar_nivel_voz(0.7)
                cara._inicio -= 0.4
                cara.dibujar()
            with self.subTest(rostro=rostro):
                self.assertFalse(mueble & set(tocados), "un fotograma tocó el mueble")
                for i in mueble:
                    self.assertEqual((lienzo.items[i]["coords"], lienzo.items[i]["config"]),
                                     antes[i])

    def test_sin_carcasa_solo_los_rasgos(self):
        """Sin carcasa: ni mueble, ni antenas, ni barrido. En la tele, la cara
        de píxeles sola."""
        for rostro in ROSTROS:
            lienzo, cara = _cara(rostro, carcasa=False)
            with self.subTest(rostro=rostro):
                self.assertFalse(getattr(cara, "_mueble_items", []) and any(
                    i in lienzo.items for i in cara._mueble_items))
                for clave in ("carcasa", "pantalla", "oreja_izq", "oreja_der"):
                    self.assertEqual(lienzo.items[cara._items[clave]]["config"].get("state"),
                                     "hidden")
                self.assertNotIn("mueble", {
                    t for d in lienzo.items.values()
                    for t in (d["config"].get("tags") or ()) if isinstance(t, str)})

    def test_la_tele_dibuja_en_pixeles(self):
        """Los rasgos de la tele caen en su rejilla: solo tramos horizontales
        y verticales, y el brillo del ojo es un cuadrado."""
        import math
        lienzo, cara = _cara("tele", estado="reposo")
        lado, ox, oy = cara._rejilla()
        for clave in ("ojo_izq", "ceja_izq", "boca"):
            co = lienzo.items[cara._items[clave]]["coords"]
            pares = list(zip(co[0::2], co[1::2]))
            with self.subTest(pieza=clave):
                for (x0, y0), (x1, y1) in zip(pares, pares[1:] + pares[:1]):
                    self.assertTrue(math.isclose(x0, x1) or math.isclose(y0, y1),
                                    "solo tramos horizontales o verticales")
        brillo = lienzo.items[cara._items["brillo_izq"]]
        self.assertEqual(brillo["tipo"], "polygon")
        xs, ys = brillo["coords"][0::2], brillo["coords"][1::2]
        self.assertAlmostEqual(max(xs) - min(xs), max(ys) - min(ys))

    def test_las_barras_no_pisan_la_cara(self):
        for rostro in ROSTROS:
            for ancho, alto in TAMANOS:
                for estado in EXPRESIONES:
                    lienzo, cara = _cara(rostro, False, ancho, alto, estado,
                                         funcional="escuchando", escucha=1.0)
                    abajo = max(max(lienzo.items[cara._items[k]]["coords"][1::2])
                                for k in ("boca", "ojo_izq", "ojo_der")
                                if lienzo.items[cara._items[k]]["config"].get("state") != "hidden")
                    with self.subTest(rostro=rostro, tamano=(ancho, alto), estado=estado):
                        self.assertGreater(caja_barras(lienzo, cara)[1], abajo)


# ========================================================================= voces
class VocesTest(unittest.TestCase):
    def test_dos_voces_cada_una_con_su_velocidad(self):
        self.assertEqual(pu.opciones("voz"), ["claude", "daniela"])
        daniela, claude = pu.leer_voz("daniela"), pu.leer_voz("claude")
        self.assertTrue(daniela["modelo_piper"].endswith("es_AR-daniela-high.onnx"))
        self.assertTrue(claude["modelo_piper"].endswith("es_MX-claude-high.onnx"))
        self.assertEqual(daniela["velocidad"], 1.0)
        self.assertEqual(claude["velocidad"], 0.71, "medida para igualar el ritmo")

    def test_cambiar_de_voz_cambia_solo_la_voz(self):
        base = mod_ajustes.cargar()
        con_claude = pu.aplicar(base, pu.PerfilUsuario(voz="claude"))
        self.assertEqual(dataclasses.replace(con_claude, voz=base.voz), base)
        self.assertEqual(con_claude.voz.velocidad, 0.71)
        self.assertEqual(con_claude.voz.max_caracteres, base.voz.max_caracteres)

    def test_atribucion_de_las_dos_en_el_readme(self):
        readme = (rutas.RAIZ / "README.md").read_text(encoding="utf-8")
        for fragmento in ("es_AR-daniela-high", "CC BY-SA 4.0", "OpenSLR 61",
                          "es_MX-claude-high", "Apache-2.0", "HirCoir/Piper-TTS-Spanish"):
            with self.subTest(fragmento=fragmento):
                self.assertIn(fragmento, readme)


# ========================================================================== techo
def violaciones_del_techo() -> list[str]:
    """Todas las opciones publicadas de personalidad y estilo, y todas sus
    combinaciones, contra el techo único. Vacía = todo cabe."""
    malas = []
    lineas = {}
    for eje in ("personalidad", "estilo"):
        for nombre in pu.opciones(eje):
            try:
                lineas[eje, nombre] = pu.leer_lineas(eje, nombre)
            except pu.ErrorPerfilUsuario as exc:
                malas.append(f"{eje} {nombre}: {exc}")
    for p, e in itertools.product(pu.opciones("personalidad"), pu.opciones("estilo")):
        if ("personalidad", p) in lineas and ("estilo", e) in lineas:
            try:
                pu.comprobar_techo(lineas["personalidad", p], lineas["estilo", e])
            except pu.ErrorPerfilUsuario as exc:
                malas.append(f"{p} × {e}: {exc}")
    return malas


class TechoUnicoTest(unittest.TestCase):
    def test_ninguna_opcion_ni_combinacion_publicada_se_pasa(self):
        self.assertEqual(violaciones_del_techo(), [])

    def test_las_combinaciones_validas_se_aceptan_enteras(self):
        for p, e in itertools.product(pu.opciones("personalidad"), pu.opciones("estilo")):
            perfil = {**dataclasses.asdict(pu.POR_DEFECTO), "personalidad": p, "estilo": e}
            with self.subTest(combinacion=(p, e)):
                self.assertEqual(pu.validar(perfil).personalidad, p)

    def test_una_opcion_nueva_que_se_pase_hace_fallar_la_bateria(self):
        """Se copia el catálogo real, se añade una personalidad que solo se
        pasa al juntarla con un estilo, y la misma comprobación que vigila el
        catálogo real la detecta. El límite lo pone el código."""
        with tempfile.TemporaryDirectory() as carpeta:
            dirs = {}
            for eje in ("personalidad", "estilo"):
                dirs[eje] = Path(carpeta) / eje
                shutil.copytree(pu.DIRECTORIOS[eje], dirs[eje])
            (dirs["personalidad"] / "habladora.json").write_text(json.dumps(
                {"tono": ["Habla con mucho detalle y con todo tipo de matices, ejemplos "
                          "y comparaciones.", "x" * 95, "y" * 95]}), encoding="utf-8")
            with mock.patch.dict(pu.DIRECTORIOS, dirs):
                malas = violaciones_del_techo()
                self.assertTrue(any("habladora ×" in m for m in malas), malas)
                with self.assertRaises(pu.ErrorPerfilUsuario):
                    pu.validar({**dataclasses.asdict(pu.POR_DEFECTO),
                                "personalidad": "habladora", "estilo": "casual"})
                ident = pu.aplicar_identidad(
                    mod_identidad.cargar(rutas.CONFIG_REPO / "identidad.json"),
                    pu.PerfilUsuario(personalidad="habladora", estilo="casual"))
                self.assertEqual((ident.tono, ident.estilo_elegido), ((), ()),
                                 "en marcha tampoco se añade nada")

    def test_el_techo_esta_un_poco_por_encima_de_lo_publicado(self):
        totales, cuantas, largas = [], [], []
        for p, e in itertools.product(pu.opciones("personalidad"), pu.opciones("estilo")):
            juntas = pu.leer_lineas("personalidad", p) + pu.leer_lineas("estilo", e)
            totales.append(sum(map(len, juntas)))
            cuantas.append(len(juntas))
            largas += [len(linea) for linea in juntas]
        self.assertTrue(max(totales) <= pu.MAX_CARACTERES_JUNTOS <= max(totales) * 1.25)
        self.assertTrue(max(cuantas) <= pu.MAX_LINEAS_JUNTAS <= max(cuantas) + 1)
        self.assertTrue(max(largas) <= pu.MAX_CARACTERES_LINEA <= max(largas) * 1.3)


# ================================================= §14.5 contra cada opción
class _Orq:
    ultimo_aviso = None

    def __init__(self):
        self.llamadas = 0

    def responder(self, texto, historial=()):
        self.llamadas += 1
        return Respuesta(texto="respuesta del modelo", proveedor="remoto")


def _opciones_por_eje():
    for eje in pu.EJES:
        for opcion in pu.opciones(eje):
            yield eje, opcion, dataclasses.replace(pu.POR_DEFECTO, **{eje: opcion})


class InvariantesPorOpcionTest(unittest.TestCase):
    """Cada opción publicada, una a una, contra los invariantes de §14.5."""

    @classmethod
    def setUpClass(cls):
        cls.base_a = mod_ajustes.cargar()
        cls.base_i = mod_identidad.cargar(rutas.CONFIG_REPO / "identidad.json")
        cls.ref = cls._respuestas(cls.base_a, cls.base_i)

    @staticmethod
    def _respuestas(ajustes, identidad):
        def gestor():
            orq = _Orq()
            return Gestor(ajustes, identidad, orq,
                          Guardia(cargar_recursos(pais=ajustes.region.pais))), orq
        g, orq = gestor()
        crisis = g.procesar("ya no quiero vivir")
        directorio = gestor()[0].procesar("dame los números de ayuda")
        with mock.patch.multiple(mod_gestor, detectar=lambda t: Intencion.CAPACIDADES,
                                 respuesta_literal=lambda t: None):
            capacidades = gestor()[0].procesar("¿qué sabes hacer?")
        return {"crisis": (crisis.tipo, crisis.texto, orq.llamadas),
                "directorio": directorio.texto, "capacidades": capacidades.texto}

    def test_cada_opcion_publicada(self):
        clave = lambda nombre: ""                                      # noqa: E731
        orq_base = Orquestador(self.base_a, self.base_i, clave)
        for eje, opcion, perfil in _opciones_por_eje():
            a = pu.aplicar(self.base_a, perfil)
            i = pu.aplicar_identidad(self.base_i, perfil)
            with self.subTest(eje=eje, opcion=opcion):
                # Ruta de seguridad, directorio y capacidades: idénticos.
                r = self._respuestas(a, i)
                self.assertEqual(r["crisis"][0], Tipo.SEGURIDAD)
                self.assertEqual(r, self.ref)
                self.assertEqual(r["crisis"][2], 0, "sin pasar por ningún modelo")
                self.assertEqual(mod_directorio.cargar(a.region.pais).lineas,
                                 mod_directorio.cargar(self.base_a.region.pais).lineas)
                # Topes: ni de longitud ni de consumo.
                for seccion, campos in {"ia": ("max_tokens_respuesta", "presupuesto_diario",
                                               "presupuesto_por_minuto"),
                                        "voz": ("max_caracteres",)}.items():
                    for campo in campos:
                        self.assertEqual(getattr(getattr(a, seccion), campo),
                                         getattr(getattr(self.base_a, seccion), campo))
                orq = Orquestador(a, i, clave)
                for texto in ("hola, ¿qué tal?", "explícame por qué llueve paso a paso"):
                    self.assertEqual(orq.preparar(texto).max_tokens,
                                     orq_base.preparar(texto).max_tokens)
                # Autoría e identidad intactas.
                self.assertEqual(dataclasses.replace(i, tono=(), estilo_elegido=()),
                                 self.base_i)
                texto = i.instrucciones()
                if i.tono or i.estilo_elegido:
                    inicio = texto.index(mod_identidad.ENCABEZADO_PREVALECEN)
                    for invariante in (f"El creador del robot es {self.base_i.creador}.",
                                       self.base_i.limites, *self.base_i.normas,
                                       *mod_identidad.NORMAS_QUE_PREVALECEN):
                        self.assertIn(invariante, texto[inicio:])
                        self.assertNotIn(invariante, texto[:inicio])
                    for linea in i.tono + i.estilo_elegido:
                        self.assertLess(texto.index(linea), inicio)
                else:
                    self.assertEqual(texto, self.base_i.instrucciones())


if __name__ == "__main__":
    unittest.main()
