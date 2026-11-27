"""Directorio de ayuda de República Dominicana y su horario.

Lo que se comprueba:
- config/crisis.json: las tres entradas (911, 711 y *212) con su franja, su
  etiqueta de situación y la marca de verificación en false;
- el HORARIO como requisito: entre medianoche y las 8:00 la línea de salud
  mental no es la respuesta principal, ni en la ruta de crisis ni en el
  directorio (reloj simulado a las 3:00 y a las 15:00, y los bordes);
- el país configurable: con otro país no se da ningún número;
- la petición hablada se resuelve sin modelo y sin memoria;
- ningún modelo da un número: si su respuesta trae uno, se sustituye;
- la barra lateral: tecla A, petición hablada, orden, «fuera de horario»,
  lejos de la línea del aviso de crisis.json;
- la ruta de crisis y el directorio no comparten interfaz.
"""
import ast
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from emotibot import rutas
from emotibot.ajustes import Ajustes, AjustesRegion
from emotibot.dialogo import Gestor, Tipo
from emotibot.dialogo import directorio as mod_directorio
from emotibot.dialogo import horario as mod_horario
from emotibot.dialogo.seguridad import Guardia, cargar_recursos
from emotibot.identidad import Identidad
from emotibot.ia.base import Respuesta
from emotibot.panel_directorio import (SEGUNDOS_SI_SE_PIDE_HABLANDO, PanelDirectorio,
                                       entradas_panel)
from emotibot.rostro import PALETA

RD = "República Dominicana"
CRISIS = rutas.CONFIG_REPO / "crisis.json"
TRES = dt.time(3, 0)
QUINCE = dt.time(15, 0)
FRASE_DE_RIESGO = "ya no quiero vivir"


def _datos():
    return json.loads(CRISIS.read_text(encoding="utf-8"))


class _Orquestador:
    ultimo_aviso = None

    def __init__(self, texto="respuesta del modelo"):
        self.texto, self.llamadas = texto, 0

    def responder(self, texto, historial=()):
        self.llamadas += 1
        return Respuesta(texto=self.texto, proveedor="remoto")


def _gestor(texto_modelo="respuesta del modelo", pais=RD):
    orquestador = _Orquestador(texto_modelo)
    ajustes = Ajustes(region=AjustesRegion(pais=pais))
    gestor = Gestor(ajustes, Identidad(), orquestador,
                    Guardia(cargar_recursos(pais=pais)))
    return gestor, orquestador


# ---------------------------------------------------------------- configuración
class ConfiguracionTest(unittest.TestCase):
    def test_tres_entradas_con_su_franja(self):
        lineas = {l["numero"]: l for l in _datos()["lineas"]}
        self.assertEqual(set(lineas), {"911", "711", "*212"})
        self.assertEqual(lineas["911"]["horario"], "24h")
        self.assertEqual(lineas["711"]["horario"], "08:00-24:00", "el 711 NO es 24 h")
        self.assertEqual(lineas["*212"]["horario"], "24h")
        self.assertEqual(lineas["*212"]["idiomas"], "español y criollo")

    def test_etiquetas_dicen_la_situacion(self):
        etiquetas = {l["numero"]: l["etiqueta"] for l in _datos()["lineas"]}
        self.assertEqual(etiquetas, {"911": "peligro ahora mismo",
                                     "711": "crisis emocional",
                                     "*212": "violencia hacia la mujer"})
        for etiqueta in etiquetas.values():
            self.assertLessEqual(len(etiqueta.split()), 4)
            self.assertNotIn("ministerio", etiqueta.lower(), "situación, no organismo")

    def test_sin_numeros_sustituidos_ni_dudosos(self):
        texto = CRISIS.read_text(encoding="utf-8")
        for muerto in ("809-200-1400", "8092001400", "809 200 1400", "811"):
            self.assertNotIn(muerto, texto)

    def test_la_verificacion_la_pone_el_responsable(self):
        datos = _datos()
        self.assertIs(datos["verificado_por_responsable"], False)
        self.assertIn("DOCUMENTAL", datos["_verificacion"])
        self.assertIn("NADIE HA MARCADO", datos["_verificacion"])

    def test_el_pais_es_configurable(self):
        self.assertEqual(Ajustes().region.pais, RD)
        crudo = json.loads((rutas.CONFIG_REPO / "ajustes.json").read_text(encoding="utf-8"))
        self.assertEqual(crudo["region"]["pais"], RD)


# ---------------------------------------------------------------------- horario
class HorarioTest(unittest.TestCase):
    def test_franjas(self):
        self.assertIsNone(mod_horario.minutos("24h"))
        self.assertEqual(mod_horario.minutos("08:00-24:00"), (480, 1440))
        for malo in ("8-24", "25:00-26:00", "", "siempre"):
            with self.subTest(horario=malo), self.assertRaises(mod_horario.ErrorHorario):
                mod_horario.minutos(malo)

    def test_bordes_del_711(self):
        casos = {dt.time(0, 0): False, dt.time(3, 0): False, dt.time(7, 59): False,
                 dt.time(8, 0): True, dt.time(15, 0): True, dt.time(23, 59): True}
        for hora, esperado in casos.items():
            with self.subTest(hora=hora):
                self.assertIs(mod_horario.abierta("08:00-24:00", hora), esperado)

    def test_hora_del_pais_no_la_del_ordenador(self):
        # 07:00 UTC son las 03:00 en República Dominicana (UTC-4).
        utc = dt.datetime(2026, 11, 22, 7, 0, tzinfo=dt.timezone.utc)
        self.assertEqual(mod_horario.hora_del_pais(-4, utc), dt.time(3, 0))
        self.assertEqual(_datos()["desfase_utc_horas"], -4)


class RutaDeCrisisConRelojTest(unittest.TestCase):
    """La ruta de crisis con la configuración REAL y el reloj simulado."""

    def setUp(self):
        self.guardia = Guardia(cargar_recursos(pais=RD))

    def test_a_las_3_la_linea_de_salud_mental_no_es_la_respuesta(self):
        respuesta = self.guardia.evaluar(FRASE_DE_RIESGO, TRES).respuesta
        self.assertNotIn("711", respuesta)
        self.assertIn("911", respuesta, "la principal es emergencias")
        self.assertIn("persona de confianza", respuesta)

    def test_a_las_15_se_ofrece_la_linea_de_crisis_emocional(self):
        respuesta = self.guardia.evaluar(FRASE_DE_RIESGO, QUINCE).respuesta
        self.assertIn("711", respuesta)
        self.assertIn("911", respuesta)

    def test_bordes_de_la_franja(self):
        for hora, con_711 in ((dt.time(7, 59), False), (dt.time(8, 0), True),
                              (dt.time(23, 59), True), (dt.time(0, 0), False)):
            with self.subTest(hora=hora):
                respuesta = self.guardia.evaluar(FRASE_DE_RIESGO, hora).respuesta
                self.assertEqual("711" in respuesta, con_711)

    def test_la_ruta_de_crisis_no_abre_el_directorio(self):
        gestor, orquestador = _gestor()
        resultado = gestor.procesar(FRASE_DE_RIESGO)
        self.assertIs(resultado.tipo, Tipo.SEGURIDAD)
        self.assertFalse(resultado.mostrar_directorio, "no comparten interfaz")
        self.assertEqual(orquestador.llamadas, 0)


class DirectorioConRelojTest(unittest.TestCase):
    def setUp(self):
        self.directorio = mod_directorio.cargar(RD)

    def test_a_las_3_el_711_va_al_final_y_marcado(self):
        entradas = self.directorio.entradas(TRES)
        self.assertEqual([l.numero for l, _ in entradas], ["911", "*212", "711"])
        self.assertEqual(entradas[-1], (entradas[-1][0], False))
        self.assertEqual(self.directorio.principal(TRES).numero, "911")
        hablado = self.directorio.respuesta_hablada(TRES)
        self.assertIn("fuera de horario", hablado)

    def test_a_las_15_en_el_orden_del_archivo(self):
        entradas = self.directorio.entradas(QUINCE)
        self.assertEqual([l.numero for l, _ in entradas], ["911", "711", "*212"])
        self.assertTrue(all(abierta for _, abierta in entradas))
        self.assertNotIn("fuera de horario", self.directorio.respuesta_hablada(QUINCE))

    def test_una_cerrada_nunca_es_la_primera(self):
        for minuto in range(0, 24 * 60, 30):
            hora = dt.time(minuto // 60, minuto % 60)
            primera, abierta = self.directorio.entradas(hora)[0]
            with self.subTest(hora=hora):
                self.assertTrue(abierta)

    def test_dice_que_no_puede_llamar_y_como_se_dicen(self):
        hablado = self.directorio.respuesta_hablada(QUINCE)
        self.assertIn("no puedo llamar", hablado)
        self.assertIn("asterisco dos uno dos", hablado)
        for etiqueta in ("peligro ahora mismo", "crisis emocional",
                         "violencia hacia la mujer"):
            self.assertIn(etiqueta, hablado)


# --------------------------------------------------------------------------- país
class PaisTest(unittest.TestCase):
    def test_con_otro_pais_no_se_da_ningun_numero(self):
        directorio = mod_directorio.cargar("Colombia")
        self.assertEqual(directorio.lineas, [])
        self.assertIn("Colombia", directorio.respuesta_hablada(QUINCE))
        guardia = Guardia(cargar_recursos(pais="Colombia"))
        respuesta = guardia.evaluar(FRASE_DE_RIESGO, QUINCE).respuesta
        for numero in ("911", "711", "*212"):
            self.assertNotIn(numero, respuesta)
        self.assertIn("servicios de emergencia de tu país", respuesta)
        self.assertTrue(any("region.pais" in a for a in guardia.advertencias_arranque()))

    def test_el_pais_se_compara_sin_tildes_ni_mayusculas(self):
        self.assertTrue(mod_directorio.cargar("republica dominicana").lineas)


# ------------------------------------------------------------- petición hablada
class PeticionHabladaTest(unittest.TestCase):
    PIDEN = ("dame los números de ayuda", "¿a quién puedo llamar?",
             "necesito un teléfono de emergencia", "qué número marco si me siento mal",
             "¿a qué número llamo?", "el número de la línea de crisis",
             "directorio de ayuda", "muéstrame los teléfonos")
    NO_PIDEN = ("hola, qué tal", "marqué el número equivocado", "me siento solo",
                "llámame mañana", "tengo el número de mi prima")

    def test_reconoce_la_peticion(self):
        for frase in self.PIDEN:
            with self.subTest(frase=frase):
                self.assertTrue(mod_directorio.pide_directorio(frase))
        for frase in self.NO_PIDEN:
            with self.subTest(frase=frase):
                self.assertFalse(mod_directorio.pide_directorio(frase))

    def test_se_resuelve_sin_modelo_y_sin_memoria(self):
        gestor, orquestador = _gestor()
        resultado = gestor.procesar("dame los números de ayuda")
        self.assertTrue(resultado.mostrar_directorio)
        self.assertEqual(resultado.proveedor, "local")
        self.assertEqual(orquestador.llamadas, 0, "ningún modelo interviene")
        self.assertEqual(len(gestor.memoria), 0, "los números no entran en la memoria")
        self.assertIn("no puedo llamar", resultado.texto)


# ------------------------------------------------------- números en boca de un modelo
class NingunModeloDaNumerosTest(unittest.TestCase):
    CON_NUMERO = ("llama al 911", "marca el *212", "el 809-200-1400 te atiende",
                  "prueba el 8092001400", "llama al 112", "marca el 106",
                  "llama al nueve uno uno", "llámala al novecientos once",
                  "marca asterisco dos uno dos", "el 711 abre a las ocho")
    SIN_NUMERO = ("en 2026 cambió", "a las 8:00", "tengo 3 ideas", "son 1500 pesos",
                  "llámame en 5 minutos", "marca 3 cosas que te gusten",
                  "cuenta uno, dos, tres y respira", "llama a tu hermana y cuéntale",
                  "marcó un gol en el minuto 90", "llama a dos amigos",
                  "comunícate con una persona de confianza")

    def test_detecta_numeros_y_no_cifras_normales(self):
        numeros = mod_directorio.cargar(RD).numeros()
        for frase in self.CON_NUMERO:
            with self.subTest(frase=frase):
                self.assertTrue(mod_directorio.contiene_telefono(frase, numeros))
        for frase in self.SIN_NUMERO:
            with self.subTest(frase=frase):
                self.assertFalse(mod_directorio.contiene_telefono(frase, numeros))

    def test_la_respuesta_del_modelo_con_numero_se_sustituye(self):
        for texto in ("Si lo necesitas, llama al 112.", "Marca el 711 cuando quieras."):
            with self.subTest(texto=texto):
                gestor, orquestador = _gestor(texto_modelo=texto)
                resultado = gestor.procesar("cuéntame algo")
                self.assertEqual(orquestador.llamadas, 1)
                self.assertEqual(resultado.texto, mod_directorio.REMISION)
                self.assertTrue(resultado.mostrar_directorio)
                memoria = " ".join(t.robot for t in gestor.memoria)
                self.assertNotIn("112", memoria)
                self.assertNotIn("711", memoria)

    def test_la_respuesta_normal_no_se_toca(self):
        gestor, _ = _gestor(texto_modelo="Me alegra que estés aquí.")
        resultado = gestor.procesar("cuéntame algo")
        self.assertEqual(resultado.texto, "Me alegra que estés aquí.")
        self.assertFalse(resultado.mostrar_directorio)


# ------------------------------------------------------------------ barra lateral
class _Lienzo:
    """Lienzo mínimo con etiquetas, para la barra lateral."""

    def __init__(self):
        self.items, self._n = {}, 0

    def _crear(self, tipo, coords, kw):
        self._n += 1
        self.items[self._n] = {"tipo": tipo, "coords": list(coords), "config": kw}
        return self._n

    def create_polygon(self, *c, **kw):
        return self._crear("polygon", c, kw)

    def create_text(self, x, y, **kw):
        return self._crear("text", (x, y), kw)

    def delete(self, etiqueta):
        self.items = {k: v for k, v in self.items.items()
                      if v["config"].get("tags") != etiqueta}

    def textos(self):
        return [v["config"]["text"] for v in self.items.values() if v["tipo"] == "text"]


class BarraLateralTest(unittest.TestCase):
    def setUp(self):
        self.lienzo = _Lienzo()
        self.panel = PanelDirectorio(self.lienzo, PALETA, mod_directorio.cargar(RD))

    def test_entradas_de_la_barra(self):
        entradas = entradas_panel(self.panel.directorio, TRES)
        self.assertEqual([e.numero for e in entradas], ["911", "*212", "711"])
        self.assertIn("ahora fuera de horario", entradas[-1].detalle)
        self.assertFalse(entradas[-1].abierta)
        self.assertIn("español y criollo", entradas[1].detalle)

    def test_se_dibuja_a_un_lado_lejos_del_aviso(self):
        """Ocupa la franja vertical del rostro, que los textos de la
        aplicación nunca invaden (tests/test_textos_ventana.py lo mide en Tk
        real): por eso no puede pisar la línea del aviso de crisis.json."""
        franja = (110.0, 590.0)
        self.panel.alternar()                       # tecla A
        self.panel.actualizar(1280, 720, 0.0, QUINCE, franja=franja)
        textos = " ".join(self.lienzo.textos())
        for cosa in ("911", "711", "*212", "peligro ahora mismo", "crisis emocional",
                     "violencia hacia la mujer", "no puedo llamar"):
            self.assertIn(cosa, textos)
        fondo = next(v for v in self.lienzo.items.values() if v["tipo"] == "polygon")
        xs, ys = fondo["coords"][0::2], fondo["coords"][1::2]
        self.assertGreater(min(xs), 1280 * 0.6, "barra lateral, a la derecha")
        self.assertEqual((min(ys), max(ys)), franja, "exactamente la franja del rostro")
        for x, y in zip(xs, ys):
            self.assertTrue(0 <= x <= 1280 and 0 <= y <= 720)

    def test_tecla_a_abre_y_cierra(self):
        self.panel.alternar()
        self.panel.actualizar(800, 480, 0.0, QUINCE)
        self.assertTrue(self.lienzo.items)
        self.panel.alternar()
        self.assertFalse(self.lienzo.items)

    def test_pedida_hablando_se_cierra_sola(self):
        self.panel.mostrar(SEGUNDOS_SI_SE_PIDE_HABLANDO, ahora=100.0)
        self.panel.actualizar(800, 480, 150.0, QUINCE)
        self.assertTrue(self.panel.visible)
        self.panel.actualizar(800, 480, 100.0 + SEGUNDOS_SI_SE_PIDE_HABLANDO, QUINCE)
        self.assertFalse(self.panel.visible)
        self.assertFalse(self.lienzo.items)

    def test_sin_numeros_lo_dice(self):
        panel = PanelDirectorio(self.lienzo, PALETA, mod_directorio.cargar("Colombia"))
        panel.mostrar()
        panel.actualizar(800, 480, 0.0, QUINCE)
        self.assertTrue(any("Colombia" in t for t in self.lienzo.textos()))


class AplicacionTest(unittest.TestCase):
    """La aplicación: tecla A para la barra y sin mezclar con la ruta de crisis."""

    def setUp(self):
        self.fuente = (rutas.RAIZ / "emotibot" / "app.py").read_text(encoding="utf-8")

    def test_la_tecla_a_alterna_la_barra(self):
        arbol = ast.parse(self.fuente)
        tecla = next(n for n in ast.walk(arbol)
                     if isinstance(n, ast.FunctionDef) and n.name == "_tecla")
        codigo = ast.get_source_segment(self.fuente, tecla)
        self.assertIn('caracter == "a"', codigo)
        self.assertIn("panel_directorio.alternar()", codigo)

    def test_la_barra_solo_se_abre_por_mostrar_directorio(self):
        llamadas = [l for l in self.fuente.splitlines() if "panel_directorio.mostrar(" in l]
        self.assertEqual(len(llamadas), 1)
        self.assertIn("mostrar_directorio", self.fuente)


if __name__ == "__main__":
    unittest.main()
