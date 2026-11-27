"""Decisión provisional (opción d, 22-11-2026): ruta de razonamiento desactivada.

Criterio de aceptación: una pregunta de razonamiento va DIRECTA al modelo de
conversación, sin llamada fallida y sin el aviso «modelo no disponible» en
pantalla, conservando su tope de 320 tokens.

Se usa la configuración REAL del repositorio (config/proveedores.json), así
que la prueba comprueba la decisión tal como está aplicada. La red está
simulada: no sale ninguna petición.
"""
import json
import tempfile
import unittest

from emotibot.ia import longitud
from pathlib import Path
from unittest import mock

from emotibot import rutas
from emotibot.ajustes import Ajustes
from emotibot.dialogo import Gestor
from emotibot.dialogo import gestor as mod_gestor
from emotibot.dialogo.intencion import Intencion
from emotibot.dialogo.seguridad import Guardia, Recursos
from emotibot.identidad import Identidad
from emotibot.ia import enrutador, openai_compat
from emotibot.ia.base import Clase
from emotibot.ia.openai_compat import cargar_endpoints

PREGUNTA_RAZONAMIENTO = "¿Por qué el cielo se ve azul? Explícamelo paso a paso."
PREGUNTA_CHARLA = "Hola, ¿qué tal estás?"


class _Respuesta:
    status = 200

    def read(self):
        return json.dumps({"choices": [{"message": {"content": "Por la dispersión."},
                                        "finish_reason": "stop"}],
                           "usage": {"prompt_tokens": 700, "completion_tokens": 9}}).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class RutaRazonamientoDesactivadaTest(unittest.TestCase):
    def setUp(self):
        parche = mock.patch.object(rutas, "ARCHIVO_PRESUPUESTO",
                                   Path(tempfile.mkdtemp()) / "p.json")
        parche.start()
        self.addCleanup(parche.stop)
        from emotibot.ia.orquestador import Orquestador
        # Gemini sin clave: su SDK no pasa por urllib y no está simulado, así
        # que el respaldo nunca debe intentar una llamada real en la prueba.
        self.orq = Orquestador(Ajustes(), Identidad(),
                               lambda n: "" if n == "gemini" else "clave-de-prueba")
        self.peticiones = []

        def urlopen(solicitud, timeout=None):
            self.peticiones.append((solicitud.full_url, json.loads(solicitud.data)))
            return _Respuesta()
        parche_red = mock.patch.object(openai_compat.urllib.request, "urlopen", urlopen)
        parche_red.start()
        self.addCleanup(parche_red.stop)

    def test_la_configuracion_la_desactiva_sin_borrarla(self):
        e = cargar_endpoints(rutas.ARCHIVO_PROVEEDORES)["razonamiento"]
        self.assertEqual(e.url, "")
        self.assertFalse(e.configurado)
        crudo = json.loads(rutas.ARCHIVO_PROVEEDORES.read_text(encoding="utf-8"))
        motivo = " ".join(crudo["razonamiento"]["_DESACTIVADO"])
        self.assertIn("3.2", motivo)
        self.assertIn("gratis", motivo)
        self.assertIn("razonamiento", Ajustes().ia.orden_proveedores,
                      "se desactiva en el proveedor, no se toca el orden")

    def test_la_pregunta_es_de_razonamiento(self):
        self.assertEqual(enrutador.papel(PREGUNTA_RAZONAMIENTO), enrutador.RAZONAMIENTO)

    def test_va_directa_a_conversacion_sin_llamada_fallida_ni_aviso(self):
        respuesta = self.orq.responder(PREGUNTA_RAZONAMIENTO)
        self.assertEqual(respuesta.proveedor, "conversacion")
        self.assertEqual(len(self.peticiones), 1, "una sola petición, la buena")
        url, cuerpo = self.peticiones[0]
        self.assertIn("api.groq.com", url)
        self.assertNotIn("openrouter", url)
        self.assertEqual(cuerpo["model"], "qwen/qwen3.8-27b")
        self.assertEqual(cuerpo["max_tokens"], longitud.cargar()["razonamiento"].max_tokens,
                         "conserva el tope de su ruta")
        self.assertIsNone(self.orq.ultimo_aviso, "sin aviso en pantalla")

    def test_por_el_gestor_tampoco_hay_aviso(self):
        gestor = Gestor(Ajustes(), Identidad(), self.orq,
                        Guardia(Recursos(respuesta="r", cierre_sin_recursos="c",
                                         verificado=True)))
        with mock.patch.multiple(mod_gestor, detectar=lambda _t: Intencion.CONVERSACION,
                                 respuesta_literal=lambda _t: None):
            resultado = gestor.procesar(PREGUNTA_RAZONAMIENTO)
        self.assertEqual(resultado.aviso, "")
        self.assertEqual(resultado.proveedor, "conversacion")
        self.assertEqual(resultado.papel, enrutador.RAZONAMIENTO)

    def test_la_charla_sigue_con_su_tope(self):
        self.orq.responder(PREGUNTA_CHARLA)
        self.assertEqual(self.peticiones[0][1]["max_tokens"],
                         longitud.cargar()["conversacion"].max_tokens)
        self.assertIsNone(self.orq.ultimo_aviso)

    def test_un_fallo_real_sigue_avisando(self):
        """Desactivar no es lo mismo que fallar: un 404 real sí avisa."""
        import io
        import urllib.error

        def falla_groq(solicitud, timeout=None):
            raise urllib.error.HTTPError(solicitud.full_url, 404, "x", {},
                                         io.BytesIO(b'{"error":{"message":"no"}}'))
        with mock.patch.object(openai_compat.urllib.request, "urlopen", falla_groq):
            respuesta = self.orq.responder(PREGUNTA_RAZONAMIENTO)
        self.assertNotEqual(respuesta.proveedor, "conversacion")
        self.assertIsNotNone(self.orq.ultimo_aviso)
        self.assertIs(self.orq.ultimo_aviso.clase, Clase.MODELO)


class MedicionB4Test(unittest.TestCase):
    """B4 compara Qwen con GPT-OSS en las dos rutas y muestrea Gemini."""

    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "medir_modelos", Path(__file__).resolve().parent.parent / "bin" / "medir_modelos.py")
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    def _hosts(self, plan):
        return {k: (self.mod.HOST_GEMINI if self.mod.separar(k)[0] == "remoto"
                    else "api.groq.com") for k in plan}

    def test_plan_por_defecto_cabe_en_los_topes(self):
        plan = self.mod.leer_plan(self.mod.PLAN_POR_DEFECTO)
        groq = sum(n for k, n in plan.items() if self.mod.separar(k)[0] != "remoto")
        self.assertEqual(groq, 20)
        self.assertEqual(plan["remoto"], 4)
        self.assertEqual(plan["conversacion@razonamiento"], 3)
        self.assertEqual(plan["candidato_gpt_oss_20b@razonamiento"], 3)
        self.assertEqual(self.mod.comprobar_topes(
            plan, self._hosts(plan), "f", {"franjas": {}, "total": {}}), [])

    def test_orden_alterna_modelos_y_reparte_rutas(self):
        orden = self.mod.orden_alternado(self.mod.leer_plan(self.mod.PLAN_POR_DEFECTO))
        self.assertEqual(len(orden), 24)
        modelos = [self.mod.separar(k)[0] for k, _ in orden]
        # Nunca dos solicitudes seguidas al mismo modelo de Groq.
        for a, b in zip(modelos, modelos[1:]):
            if a != "remoto" and b != "remoto":
                self.assertNotEqual(a, b)
        # Las de razonamiento de Qwen no quedan amontonadas al final.
        qwen = [k for k, _ in orden if k.startswith("conversacion")]
        posiciones = [i for i, k in enumerate(qwen) if "@" in k]
        self.assertLess(posiciones[0], 3)

    def test_con_el_ritmo_nuevo_el_presupuesto_no_corta(self):
        """Regresión del corte de la franja 11h (17 de 20), SIN tocar el
        presupuesto: tope real de 7.000/min, instrucciones REALES del archivo
        y el consumo medido aquel día más 250 tokens de entrada, que es lo
        que añadieron las reglas de estilo del 22-11 con margen."""
        from emotibot.ia import presupuesto as mod_presupuesto
        from emotibot.ia import tokens
        from emotibot.ia.presupuesto import Presupuesto
        endpoints = cargar_endpoints(rutas.ARCHIVO_PROVEEDORES)
        p = Presupuesto(1000, 1000, ruta=Path(tempfile.mkdtemp()) / "p.json")
        for e in endpoints.values():
            if e.configurado:
                p.fijar_limites(e.modelo, e.max_dia, e.max_minuto,
                                e.max_tokens_dia, e.max_tokens_minuto)
        from emotibot import identidad as mod_identidad
        instrucciones = mod_identidad.cargar().instrucciones()
        reales = {"conversacion": (665 + 250, 40),
                  "candidato_gpt_oss_20b": (695 + 250, 60)}
        reloj = [0.0]
        rechazos = []
        with mock.patch.object(mod_presupuesto.time, "monotonic", lambda: reloj[0]):
            for posicion, (clave, i) in enumerate(self.mod.orden_alternado(
                    self.mod.leer_plan(self.mod.PLAN_POR_DEFECTO))):
                reloj[0] = posicion * self.mod.ESPACIO_S
                nombre, ruta = self.mod.separar(clave)
                if nombre == "remoto":
                    continue
                e = endpoints[nombre]
                tope = 320 if ruta == "razonamiento" else 120
                pregunta = self.mod.PREGUNTAS[ruta or "conversacion"][i % 4]
                entrada = tokens.estimar_entrada([instrucciones, pregunta])
                reserva, motivo = p.reservar(e.modelo, entrada + tope, entrada)
                if reserva is None:
                    rechazos.append((clave, motivo))
                    continue
                p.confirmar(reserva, *reales[nombre])
        self.assertEqual(rechazos, [])

    def test_gemini_no_pasa_de_cuatro_por_franja(self):
        plan = {"remoto": 5}
        self.assertTrue(self.mod.comprobar_topes(
            plan, self._hosts(plan), "f", {"franjas": {}, "total": {}}))

    def test_separar_ruta(self):
        self.assertEqual(self.mod.separar("conversacion@razonamiento"),
                         ("conversacion", "razonamiento"))
        self.assertEqual(self.mod.separar("remoto"), ("remoto", ""))

    def test_gemini_se_mide_por_el_camino_del_robot(self):
        from types import SimpleNamespace
        from emotibot.ia import gemini as mod_gemini
        from emotibot.ia.presupuesto import Presupuesto
        resultado = SimpleNamespace(
            text="Hola.", candidates=[SimpleNamespace(finish_reason="STOP")],
            usage_metadata=SimpleNamespace(prompt_token_count=650,
                                           candidates_token_count=4,
                                           thoughts_token_count=None))
        vistos = {}

        class Modelos:
            def generate_content(self, model, contents, config):
                vistos["max"] = config["max_output_tokens"]
                return resultado
        tipos = SimpleNamespace(GenerateContentConfig=lambda **kw: kw, ThinkingConfig=None)
        presupuesto = Presupuesto(100, 50, ruta=Path(tempfile.mkdtemp()) / "p.json")
        with mock.patch.object(mod_gemini, "_cargar_sdk", lambda: (None, tipos)), \
                mock.patch.object(mod_gemini, "_cliente",
                                  lambda *_a: SimpleNamespace(models=Modelos())), \
                mock.patch.object(self.mod.credenciales, "cargar", lambda _n: "clave-de-prueba"):
            r = self.mod.medir_gemini(Ajustes(), presupuesto, "sé breve", "hola", 120)
        self.assertEqual(r["estado"], "ok")
        self.assertEqual((r["tokens_entrada"], r["tokens_salida"]), (650, 4))
        self.assertIsNone(r["ttft"], "sin streaming no hay TTFT")
        self.assertGreaterEqual(r["t_total"], 0)
        self.assertEqual(vistos["max"], 120)
        self.assertEqual(presupuesto._estado(Ajustes().ia.modelo_remoto).tokens, 654)

    def test_un_tiempo_agotado_de_gemini_es_un_dato(self):
        from emotibot.ia import gemini as mod_gemini
        from emotibot.ia.presupuesto import Presupuesto
        from types import SimpleNamespace

        class Lento:
            def generate_content(self, model, contents, config):
                raise TimeoutError("timed out")
        tipos = SimpleNamespace(GenerateContentConfig=lambda **kw: kw, ThinkingConfig=None)
        with mock.patch.object(mod_gemini, "_cargar_sdk", lambda: (None, tipos)), \
                mock.patch.object(mod_gemini, "_cliente",
                                  lambda *_a: SimpleNamespace(models=Lento())), \
                mock.patch.object(self.mod.credenciales, "cargar", lambda _n: "clave-de-prueba"):
            r = self.mod.medir_gemini(Ajustes(), Presupuesto(
                100, 50, ruta=Path(tempfile.mkdtemp()) / "p.json"), "x", "hola", 120)
        self.assertEqual(r["estado"], "tiempo")


if __name__ == "__main__":
    unittest.main()
