"""D6 (§14.1): GPT-OSS 20B como tercer candidato, sin tocar producción.

Sin red ni claves: las peticiones se capturan con un `urlopen` simulado.
"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from emotibot import ajustes as mod_ajustes
from emotibot import rutas
from emotibot.ia import openai_compat
from emotibot.ia.base import Peticion
from emotibot.ia.openai_compat import (Endpoint, ProveedorOpenAI, cargar_endpoints,
                                       cuerpo_peticion)
from emotibot.ia.presupuesto import Presupuesto

RAIZ = Path(__file__).resolve().parent.parent
CANDIDATO = "candidato_gpt_oss_20b"


def _script(nombre):
    spec = importlib.util.spec_from_file_location(nombre, RAIZ / "bin" / f"{nombre}.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class FueraDeProduccionTest(unittest.TestCase):
    def test_esta_configurado_como_candidato(self):
        e = cargar_endpoints(rutas.ARCHIVO_PROVEEDORES)[CANDIDATO]
        self.assertEqual(e.modelo, "openai/gpt-oss-20b")
        self.assertEqual(e.clave, "groq")
        self.assertEqual(e.papel, "conversacion")
        self.assertEqual(e.parametros, {"reasoning_effort": "low"})

    def test_es_el_respaldo_justo_detras_de_qwen(self):
        """23-11: entra en la cadena detrás de Qwen; Qwen sigue mandando."""
        for orden in (mod_ajustes.Ajustes().ia.orden_proveedores,
                      mod_ajustes.cargar().ia.orden_proveedores):
            self.assertEqual(orden[:2], ("conversacion", CANDIDATO))
            self.assertEqual(orden.count(CANDIDATO), 1)

    def test_el_modelo_de_conversacion_sigue_siendo_qwen(self):
        e = cargar_endpoints(rutas.ARCHIVO_PROVEEDORES)["conversacion"]
        self.assertEqual(e.modelo, "qwen/qwen3.8-27b")


class CuerpoTest(unittest.TestCase):
    def test_produccion_envia_exactamente_lo_mismo_que_antes(self):
        e = cargar_endpoints(rutas.ARCHIVO_PROVEEDORES)["conversacion"]
        cuerpo = cuerpo_peticion(e, [{"role": "user", "content": "hola"}], 120)
        self.assertEqual(set(cuerpo), {"model", "messages", "temperature",
                                       "max_tokens", "stream"})
        self.assertEqual(cuerpo["temperature"], e.temperatura)
        self.assertIs(cuerpo["stream"], False)

    def test_el_candidato_anade_su_esfuerzo_de_razonamiento(self):
        e = cargar_endpoints(rutas.ARCHIVO_PROVEEDORES)[CANDIDATO]
        cuerpo = cuerpo_peticion(e, [], 120)
        self.assertEqual(cuerpo["reasoning_effort"], "low")
        self.assertEqual(cuerpo["max_tokens"], 120)

    def test_la_configuracion_no_puede_pisar_los_campos_del_robot(self):
        """El tope de tokens es contabilidad (A3) y techo (§14.5)."""
        e = Endpoint(nombre="x", url="u", modelo="m", parametros={
            "max_tokens": 99999, "model": "otro", "stream": True,
            "max_completion_tokens": 99999, "n": 5, "top_p": 0.9})
        cuerpo = cuerpo_peticion(e, [], 120)
        self.assertEqual(cuerpo["max_tokens"], 120)
        self.assertEqual(cuerpo["model"], "m")
        self.assertIs(cuerpo["stream"], False)
        self.assertNotIn("max_completion_tokens", cuerpo)
        self.assertNotIn("n", cuerpo)
        self.assertEqual(cuerpo["top_p"], 0.9)

    def test_el_proveedor_envia_los_parametros(self):
        e = cargar_endpoints(rutas.ARCHIVO_PROVEEDORES)[CANDIDATO]
        prov = ProveedorOpenAI(e, Presupuesto(100, 50, ruta=Path(tempfile.mkdtemp()) / "p.json"),
                               lambda _n: "clave-de-prueba")
        enviado = {}

        class Respuesta:
            status = 200

            def read(self):
                return json.dumps({"choices": [{"message": {"content": "Hola."},
                                                "finish_reason": "stop"}]}).encode()

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        def falso(solicitud, timeout=None):
            enviado.update(json.loads(solicitud.data))
            return Respuesta()
        with mock.patch.object(openai_compat.urllib.request, "urlopen", falso):
            prov.responder(Peticion(texto="hola", instrucciones="sé breve"))
        self.assertEqual(enviado["reasoning_effort"], "low")
        self.assertEqual(enviado["model"], "openai/gpt-oss-20b")


class MedicionTest(unittest.TestCase):
    def setUp(self):
        self.mod = _script("medir_modelos")

    def test_plan_por_defecto_compara_qwen_con_gpt_oss(self):
        """Desde el 22-11 (opción d) ya no incluye la ruta de OpenRouter."""
        plan = self.mod.leer_plan(self.mod.PLAN_POR_DEFECTO)
        nombres = {self.mod.separar(k)[0] for k in plan}
        self.assertEqual(nombres, {"conversacion", CANDIDATO, "remoto"})
        self.assertNotIn("razonamiento", plan)

    def test_los_topes_se_suman_por_anfitrion(self):
        """Qwen y GPT-OSS van los dos a Groq: 10 + 11 supera los 20."""
        hosts = {"conversacion": "api.groq.com", CANDIDATO: "api.groq.com",
                 "razonamiento": "openrouter.ai"}
        vacio = {"franjas": {}, "total": {}}
        self.assertEqual(self.mod.comprobar_topes(
            {"conversacion": 10, CANDIDATO: 10, "razonamiento": 4}, hosts, "f", vacio), [])
        problemas = self.mod.comprobar_topes(
            {"conversacion": 10, CANDIDATO: 11}, hosts, "f", vacio)
        self.assertTrue(problemas)
        self.assertIn("21", problemas[0])

    def test_lee_razonamiento_y_cache_tambien_en_x_groq(self):
        r = {"tokens_entrada": None, "tokens_salida": None,
             "tokens_razonamiento": None, "tokens_cache": None}
        self.mod.leer_uso({"x_groq": {"usage": {
            "prompt_tokens": 700, "completion_tokens": 150,
            "completion_tokens_details": {"reasoning_tokens": 90},
            "prompt_tokens_details": {"cached_tokens": 512}}}}, r)
        self.assertEqual((r["tokens_entrada"], r["tokens_salida"],
                          r["tokens_razonamiento"], r["tokens_cache"]),
                         (700, 150, 90, 512))

    def test_tok_s_no_divide_por_casi_cero(self):
        """Regresión: se llegaron a mostrar 44.557 tok/s.

        Fila real de GPT-OSS: 49 tokens de salida (12 de razonamiento),
        primer fragmento 0,276 s, TTFT 0,36 s, total 0,361 s.
        """
        fila = {"tokens_salida": "49", "t_primer_fragmento": "0.276",
                "ttft": "0.36", "t_total": "0.361"}
        self.assertIsNone(self.mod.velocidad_generacion(fila),
                          "85 ms de generación no son medibles")

    def test_tok_s_cuenta_desde_el_primer_fragmento(self):
        """El razonamiento llega antes del TTFT y también es salida."""
        r = {"tokens_salida": 100, "t_primer_fragmento": 0.5, "ttft": 1.4,
             "t_total": 1.5}
        self.assertAlmostEqual(self.mod.velocidad_generacion(r), 100.0)

    def test_tok_s_sin_datos(self):
        self.assertIsNone(self.mod.velocidad_generacion(
            {"tokens_salida": "", "ttft": "", "t_total": "1.0"}))

    def test_sin_detalles_quedan_vacios(self):
        r = {"tokens_entrada": None, "tokens_salida": None,
             "tokens_razonamiento": None, "tokens_cache": None}
        self.mod.leer_uso({"usage": {"prompt_tokens": 10, "completion_tokens": 5}}, r)
        self.assertIsNone(r["tokens_razonamiento"])
        self.assertIsNone(r["tokens_cache"])


if __name__ == "__main__":
    unittest.main()
