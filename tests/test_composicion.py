"""Fase 1, A1: estado funcional y expresión, separados y superpuestos.

La prueba central recorre los 18 sitios que emiten texto hablado —no una
muestra— y comprueba en cada uno que la boca se abre con la voz, que la
expresión se conserva y que el piloto del micrófono no se enciende.

Para no depender del contenido del detector de intenciones, los sitios del
gestor que pasan por él se alcanzan sustituyendo el detector por uno fijo.
"""
import dataclasses
import ast
import time
import unittest
from pathlib import Path
from unittest import mock

from emotibot.ajustes import Ajustes
from emotibot.dialogo import Gestor, Tipo
from emotibot.dialogo import gestor as mod_gestor
from emotibot.dialogo.intencion import Intencion
from emotibot.dialogo.seguridad import Guardia, Recursos
from emotibot.identidad import Identidad
from emotibot.ia.base import Respuesta
from emotibot.rostro import EXPRESIONES
from emotibot.rostro.cara import Cara
from emotibot.rostro.estados import FUNCIONALES, componer
from emotibot.rostro.paleta import PALETA
from tests.test_rostro import LienzoSimulado

RAIZ = Path(__file__).resolve().parent.parent


class _Orquestador:
    ultimo_aviso = None

    def __init__(self):
        self.llamadas = 0

    def responder(self, texto, historial=()):
        self.llamadas += 1
        return Respuesta(texto="respuesta del modelo", proveedor="remoto")


def _gestor():
    guardia = Guardia(Recursos(
        respuesta="Acompañamiento local.",
        cierre_sin_recursos="Pide ayuda a alguien cercano.",
        verificado=True,
    ))
    return Gestor(Ajustes(), Identidad(), _Orquestador(), guardia)


def _con_intencion(intencion, literal=None):
    """Fija lo que devuelven el detector y las respuestas literales."""
    return mock.patch.multiple(
        mod_gestor,
        detectar=lambda _texto: intencion,
        respuesta_literal=lambda _texto: literal,
    )


def recorrer_sitios() -> dict[str, object]:
    """Devuelve {sitio: Resultado} para los 20 sitios de emisión."""
    sitios: dict[str, object] = {}

    g = _gestor()
    sitios["gestor.actividad_inexistente"] = g.iniciar_actividad("no_existe")
    sitios["gestor.seguridad"] = _gestor().procesar("ya no quiero vivir")
    sitios["gestor.sin_entender"] = _gestor().procesar("")
    with _con_intencion(Intencion.CONVERSACION, literal="Texto literal."):
        sitios["gestor.literal"] = _gestor().procesar("x")
    with _con_intencion(Intencion.CAPACIDADES):
        sitios["gestor.capacidades"] = _gestor().procesar("x")
    with _con_intencion(Intencion.DESPEDIDA):
        sitios["gestor.despedida"] = _gestor().procesar("x")
    with _con_intencion(Intencion.CONVERSACION):
        sitios["gestor.conversacion"] = _gestor().procesar("x")
    # Directorio de ayuda pedido hablando (consulta, no crisis).
    sitios["gestor.directorio"] = _gestor().procesar("dame los números de ayuda")
    # Configuración: abrirla por voz y las actividades apagadas.
    with _con_intencion(Intencion.CONFIGURACION):
        sitios["gestor.configuracion"] = _gestor().procesar("x")
    apagadas = _gestor()
    apagadas.config = dataclasses.replace(apagadas.config, dialogo=dataclasses.replace(
        apagadas.config.dialogo, actividades=False))
    sitios["gestor.actividades_apagadas"] = apagadas.iniciar_actividad("respiracion")

    # Respiración: inicio, las tres fases, cierre y cancelación.
    g = _gestor()
    sitios["respiracion.inicio"] = g.iniciar_actividad("respiracion")
    vistos = {}
    while g.actividad is not None:
        r = g.continuar_actividad()
        if r is not None:
            vistos.setdefault(r.estado_rostro, r)
    sitios["respiracion.inhalar"] = vistos["respirando_inhalar"]
    sitios["respiracion.sostener"] = vistos["respirando_sostener"]
    sitios["respiracion.exhalar"] = vistos["respirando_exhalar"]
    sitios["respiracion.cierre"] = vistos["feliz"]
    g = _gestor()
    g.iniciar_actividad("respiracion")
    sitios["respiracion.cancelar"] = g.cancelar_actividad()

    # Ordenar ideas: inicio, pregunta siguiente, cierre y cancelación.
    g = _gestor()
    sitios["ordenar.inicio"] = g.iniciar_actividad("ordenar_ideas")
    sitios["ordenar.pregunta"] = g.continuar_actividad("algo")
    g.continuar_actividad("algo")
    sitios["ordenar.cierre"] = g.continuar_actividad("algo")
    g = _gestor()
    g.iniciar_actividad("ordenar_ideas")
    sitios["ordenar.cancelar"] = g.cancelar_actividad()
    return sitios


def contar_sitios_en_el_codigo() -> int:
    """Cuenta por análisis estático los puntos que construyen texto hablado.

    - En el gestor: cada `Resultado(...)` con texto no vacío, salvo el de
      `_de_paso`, que solo reenvía el texto de una actividad.
    - En las actividades: cada `Paso(...)` con texto no vacío.
    Si alguien añade un sitio nuevo, este número cambia y la prueba avisa
    de que hay que incluirlo en el recorrido.
    """
    def texto_de(llamada: ast.Call):
        for kw in llamada.keywords:
            if kw.arg == "texto":
                return kw.value
        return llamada.args[0] if llamada.args else None

    def vacio(nodo) -> bool:
        return isinstance(nodo, ast.Constant) and nodo.value == ""

    total = 0
    archivos = {
        RAIZ / "emotibot/dialogo/gestor.py": "Resultado",
        RAIZ / "emotibot/dialogo/actividades/respiracion.py": "Paso",
        RAIZ / "emotibot/dialogo/actividades/ordenar_ideas.py": "Paso",
    }
    for archivo, clase in archivos.items():
        arbol = ast.parse(archivo.read_text(encoding="utf-8"))
        for funcion in ast.walk(arbol):
            if not isinstance(funcion, ast.FunctionDef) or funcion.name == "_de_paso":
                continue
            for nodo in ast.walk(funcion):
                if (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name)
                        and nodo.func.id == clase):
                    texto = texto_de(nodo)
                    if texto is not None and not vacio(texto):
                        total += 1
    return total


def _alto_boca(lienzo, cara) -> float:
    coords = lienzo.items[cara._items["boca"]]["coords"]
    return max(coords[1::2]) - min(coords[1::2])


from tests.test_rostro import alturas_barras, barras_visibles  # noqa: E402


def _asentar(cara, nivel_voz=None, veces=5):
    for _ in range(veces):
        if nivel_voz is not None:
            cara.fijar_nivel_voz(nivel_voz)
        cara.asentar()
        cara.dibujar()


class ComposicionTest(unittest.TestCase):
    def test_hablando_abre_la_boca_con_cualquier_expresion(self):
        for expresion in EXPRESIONES:
            with self.subTest(expresion=expresion):
                self.assertGreaterEqual(
                    componer("hablando", expresion).apertura_boca, 0.6)

    def test_fuera_de_hablando_no_hay_amplitud_de_boca(self):
        for funcional in FUNCIONALES:
            if funcional == "hablando":
                continue
            for expresion in EXPRESIONES:
                self.assertEqual(
                    componer(funcional, expresion).apertura_boca, 0.0,
                    f"{funcional}+{expresion}")

    def test_la_expresion_conserva_ojos_cejas_e_inclinacion(self):
        for expresion in ("feliz", "preocupado", "pensando", "sin_entender", "respirando_inhalar"):
            base, compuesta = EXPRESIONES[expresion], componer("hablando", expresion)
            with self.subTest(expresion=expresion):
                self.assertEqual(compuesta.apertura_ojos, base.apertura_ojos)
                self.assertEqual(compuesta.ceja_angulo, base.ceja_angulo)
                self.assertEqual(compuesta.inclinacion, base.inclinacion)
                self.assertEqual(compuesta.signo, base.signo)
                self.assertEqual(compuesta.color, base.color)
                self.assertEqual(compuesta.ojos_arco, base.ojos_arco)

    def test_solo_escuchar_de_verdad_enciende_el_indicador(self):
        """Con el micrófono abierto (calibrando o escuchando), siempre; sin él,
        nunca, sea cual sea la expresión."""
        from emotibot.rostro.estados import MICROFONO_ABIERTO
        self.assertEqual(set(MICROFONO_ABIERTO), {"calibrando", "escuchando"})
        for funcional in FUNCIONALES:
            for expresion in EXPRESIONES:
                self.assertEqual(
                    componer(funcional, expresion).anillo_escucha,
                    funcional in MICROFONO_ABIERTO,
                    f"{funcional}+{expresion}")

    def test_etiqueta_funcional_si_la_expresion_es_un_estado(self):
        """Pronunciar una pregunta con cara de escucha no dice «TE ESCUCHO»."""
        self.assertEqual(componer("hablando", "escuchando").etiqueta, "HABLANDO")
        self.assertEqual(componer("hablando", "respirando_inhalar").etiqueta,
                         "INHALA")
        self.assertEqual(componer("hablando", "feliz").etiqueta, "")


class CaraDosEjesTest(unittest.TestCase):
    def test_fijar_estado_funcional_fija_ambos_ejes(self):
        cara = Cara(LienzoSimulado(), PALETA)
        cara.fijar_estado("escuchando")
        self.assertEqual((cara.funcional, cara.estado), ("escuchando", "escuchando"))
        self.assertTrue(cara.microfono_abierto)

    def test_fijar_estado_emocional_conserva_el_funcional(self):
        cara = Cara(LienzoSimulado(), PALETA)
        cara.fijar(funcional="hablando", expresion="reposo")
        cara.fijar_estado("feliz")
        self.assertEqual((cara.funcional, cara.estado), ("hablando", "feliz"))

    def test_transicion_suave_entre_expresiones(self):
        """Un fotograma de 33 ms no puede llevar la cara entera a su destino."""
        lienzo = LienzoSimulado()
        cara = Cara(lienzo, PALETA)
        cara.fijar(funcional="hablando", expresion="reposo")
        _asentar(cara, 0.0)
        cara.fijar(expresion="preocupado")
        cara._ultimo_t = time.monotonic() - 0.033
        cara.dibujar()
        objetivo = EXPRESIONES["preocupado"].ceja_angulo
        self.assertGreater(cara._anim.ceja_angulo, 0.0)
        self.assertLess(cara._anim.ceja_angulo, objetivo * 0.6)

    def test_la_boca_no_salta_al_empezar_a_sonar(self):
        lienzo = LienzoSimulado()
        cara = Cara(lienzo, PALETA)
        cara.fijar(funcional="hablando", expresion="feliz")
        _asentar(cara, 0.0)
        cara.fijar_nivel_voz(1.0)
        cara._ultimo_t = time.monotonic() - 0.033
        cara.dibujar()
        self.assertGreater(cara._anim.apertura_boca, 0.0)
        self.assertLess(cara._anim.apertura_boca, 0.62 * 0.8)


class DiecisieteSitiosTest(unittest.TestCase):
    """Criterio de aceptación de A1: los 17 recorridos, no una muestra."""

    @classmethod
    def setUpClass(cls):
        cls.sitios = recorrer_sitios()

    def test_son_dieciocho_y_coinciden_con_el_codigo(self):
        """17 hasta el directorio de ayuda, que añade el suyo; la
        configuración añade dos (abrirla por voz, actividades apagadas)."""
        self.assertEqual(len(self.sitios), 20)
        self.assertEqual(
            contar_sitios_en_el_codigo(), 20,
            "Hay un sitio de emisión nuevo o desaparecido: añádelo al "
            "recorrido de esta prueba.")

    def test_todos_tienen_texto_que_pronunciar(self):
        for sitio, resultado in self.sitios.items():
            with self.subTest(sitio=sitio):
                self.assertTrue(resultado.texto.strip())

    def test_la_boca_sigue_la_voz_en_cada_sitio(self):
        for sitio, resultado in self.sitios.items():
            with self.subTest(sitio=sitio, expresion=resultado.estado_rostro):
                lienzo = LienzoSimulado()
                cara = Cara(lienzo, PALETA)
                # Lo mismo que hace la aplicación al pronunciar un resultado.
                cara.fijar(funcional="hablando", expresion=resultado.estado_rostro)

                _asentar(cara, 0.0)
                callada = _alto_boca(lienzo, cara)
                _asentar(cara, 1.0)
                abierta = _alto_boca(lienzo, cara)
                self.assertGreater(abierta, callada * 2,
                                   "con voz la boca debe abrirse")

                # La expresión se conserva mientras habla.
                self.assertEqual(cara.estado, resultado.estado_rostro)
                self.assertEqual(cara._anim.ceja_angulo,
                                 EXPRESIONES[resultado.estado_rostro].ceja_angulo)

                # Hablar no es escuchar.
                self.assertFalse(cara.microfono_abierto)
                self.assertEqual(cara._anim.anillo, 0.0)

                # Al terminar la reproducción, la boca se cierra aunque el
                # nivel no hubiera caído todavía a cero.
                cara.fijar_funcional("reposo")
                _asentar(cara, 1.0)
                self.assertLess(_alto_boca(lienzo, cara), abierta * 0.5)

    def test_hablando_no_enciende_las_barras_de_escucha(self):
        """ordenar_ideas pronunciaba sus preguntas con el piloto encendido.

        A1, con las barras: la cara de escucha mientras el robot HABLA no las
        dibuja, aunque llegue un nivel de entrada; solo la captura real.
        """
        lienzo = LienzoSimulado()
        cara = Cara(lienzo, PALETA)
        cara.fijar_estado("reposo")
        _asentar(cara)
        self.assertFalse(any(barras_visibles(lienzo, cara)))
        cara.fijar(funcional="hablando", expresion="escuchando")
        cara.fijar_nivel_escucha(0.8)
        _asentar(cara, 0.5)
        self.assertFalse(any(barras_visibles(lienzo, cara)))
        self.assertFalse(cara.microfono_abierto)

        cara.fijar_estado("escuchando")
        _asentar(cara)
        self.assertTrue(all(barras_visibles(lienzo, cara)),
                        "con el micrófono abierto de verdad sí aparecen")
        self.assertGreater(max(alturas_barras(lienzo, cara)),
                           min(alturas_barras(lienzo, cara)) * 1.5)

    def test_la_ruta_de_seguridad_sigue_aislada(self):
        resultado = self.sitios["gestor.seguridad"]
        self.assertIs(resultado.tipo, Tipo.SEGURIDAD)
        self.assertEqual(resultado.proveedor, "local")
        self.assertEqual(resultado.estado_rostro, "preocupado")
        g = _gestor()
        g.procesar("ya no quiero vivir")
        self.assertEqual(len(g.memoria), 0)
        self.assertEqual(g.orquestador.llamadas, 0)


if __name__ == "__main__":
    unittest.main()
