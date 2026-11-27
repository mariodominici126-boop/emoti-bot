"""Regresiones de los hallazgos de bin/diagnostico_ia.py (22-11-2026).

1. Groq devolvía 403/1010: urllib se presentaba como «Python-urllib».
2. Ese 403 de Cloudflare se clasificaba como «autenticación».
3. Un identificador de cuenta de un cuerpo de error salía tal cual.
5. El diagnóstico construía Gemini con una función de clave sin argumentos.

Sin red ni claves reales. El identificador de cuenta de los ejemplos es
inventado.
"""
import contextlib
import importlib.util
import io
import json
import logging
import tempfile
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from emotibot import registro, rutas
from emotibot.ajustes import Ajustes
from emotibot.identidad import Identidad
from emotibot.ia import gemini as mod_gemini
from emotibot.ia import openai_compat
from emotibot.ia.base import Clase, ErrorProveedor, Peticion, clasificar_http
from emotibot.ia.openai_compat import (AGENTE_USUARIO, Endpoint, ProveedorOpenAI,
                                       cabeceras_peticion, cargar_endpoints)
from emotibot.ia.presupuesto import Presupuesto

RAIZ = Path(__file__).resolve().parent.parent
PETICION = Peticion(texto="hola", instrucciones="sé breve")
ID_FALSO = "user_2AbCdEfGhIjKlMnOpQrStUvWxYz"
CUERPO_OPENROUTER = json.dumps({
    "error": {"message": "This model is unavailable for free. The paid version "
                         "is available now - use this slug instead: "
                         "deepseek/ejemplo-1017", "code": 404},
    "user_id": ID_FALSO,
})
CUERPO_CLOUDFLARE = "error code: 1010"


def _script(nombre):
    spec = importlib.util.spec_from_file_location(nombre, RAIZ / "bin" / f"{nombre}.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _presupuesto():
    return Presupuesto(100, 50, ruta=Path(tempfile.mkdtemp()) / "p.json")


def _proveedor(**extra):
    endpoint = Endpoint(nombre="prueba", url="https://ejemplo.invalid/v1",
                        modelo="m", clave="prueba", **extra)
    return ProveedorOpenAI(endpoint, _presupuesto(), lambda _n: "clave-de-prueba")


def _http_error(codigo, cuerpo):
    return urllib.error.HTTPError("https://ejemplo.invalid", codigo, "x", {},
                                  io.BytesIO(cuerpo.encode("utf-8")))


class _Ok:
    status = 200

    def read(self):
        return json.dumps({"choices": [{"message": {"content": "listo"},
                                        "finish_reason": "stop"}]}).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


# ============================================================ 1. User-Agent
class AgenteUsuarioTest(unittest.TestCase):
    def test_cabecera_propia_por_defecto(self):
        cabeceras = cabeceras_peticion(Endpoint(nombre="x"), "clave")
        self.assertEqual(cabeceras["User-Agent"], AGENTE_USUARIO)
        self.assertTrue(AGENTE_USUARIO.startswith("EMOTI-BOT/"))
        self.assertEqual(cabeceras["Authorization"], "Bearer clave")

    def test_la_de_configuracion_manda_sin_duplicar(self):
        e = Endpoint(nombre="x", cabeceras={"user-agent": "Otro/2"})
        cabeceras = cabeceras_peticion(e)
        agentes = [k for k in cabeceras if k.lower() == "user-agent"]
        self.assertEqual(agentes, ["user-agent"])
        self.assertEqual(cabeceras["user-agent"], "Otro/2")

    def test_la_configuracion_no_puede_quitar_la_clave(self):
        e = Endpoint(nombre="x", cabeceras={"Authorization": "Bearer otra"})
        self.assertEqual(cabeceras_peticion(e, "buena")["Authorization"],
                         "Bearer buena")

    def test_la_peticion_real_no_se_presenta_como_python_urllib(self):
        enviadas = []

        def falso(solicitud, timeout=None):
            enviadas.append(solicitud)
            return _Ok()
        with mock.patch.object(openai_compat.urllib.request, "urlopen", falso):
            _proveedor().responder(PETICION)
        agente = enviadas[0].get_header("User-agent")
        self.assertEqual(agente, AGENTE_USUARIO)
        self.assertNotIn("Python-urllib", agente)

    def test_el_sondeo_local_tambien_se_identifica(self):
        enviadas = []

        def falso(solicitud, timeout=None):
            enviadas.append(solicitud)
            raise urllib.error.URLError("apagado")
        prov = ProveedorOpenAI(
            Endpoint(nombre="local", url="http://127.0.0.1:9/v1", modelo="local"),
            _presupuesto(), lambda _n: "")
        with mock.patch.object(openai_compat.urllib.request, "urlopen", falso):
            prov._sondear()
        self.assertTrue(enviadas)
        self.assertEqual(enviadas[0].get_header("User-agent"), AGENTE_USUARIO)

    def test_la_medicion_b4_usa_las_mismas_cabeceras(self):
        medir = _script("medir_modelos")
        enviadas = []

        def falso(solicitud, timeout=None):
            enviadas.append(solicitud)
            raise _http_error(429, "{}")
        with mock.patch.object(medir.urllib.request, "urlopen", falso):
            medir.medir_una(Endpoint(nombre="m", url="https://ejemplo.invalid/v1",
                                     modelo="m"), "clave", [], 10, 5)
        self.assertEqual(enviadas[0].get_header("User-agent"), AGENTE_USUARIO)

    def test_ya_no_hace_falta_el_parche_en_la_configuracion(self):
        for nombre in ("conversacion", "candidato_gpt_oss_20b"):
            e = cargar_endpoints(rutas.ARCHIVO_PROVEEDORES)[nombre]
            self.assertNotIn("User-Agent", e.cabeceras, nombre)


# ======================================================= 2. Clasificación
class ClasificacionTest(unittest.TestCase):
    def test_tabla(self):
        casos = [
            (403, CUERPO_CLOUDFLARE, Clase.BLOQUEO_CLIENTE),
            (403, "<html><title>Attention Required! | Cloudflare</title></html>",
             Clase.BLOQUEO_CLIENTE),
            (401, "", Clase.BLOQUEO_CLIENTE),
            (403, '{"error":{"message":"Invalid API Key"}}', Clase.AUTENTICACION),
            (401, '{"error":{"message":"No auth credentials found"}}', Clase.AUTENTICACION),
            (404, CUERPO_OPENROUTER, Clase.MODELO),
            (404, "Not Found", Clase.OTRO),
            (429, "{}", Clase.CUOTA),
            (429, "rate limited", Clase.CUOTA),
            (400, "{}", Clase.PETICION),
            (500, "{}", Clase.INTERNO),
            (520, "", Clase.INTERNO),
            (502, "", Clase.SOBRECARGA),
            (504, "", Clase.TIEMPO),
        ]
        for codigo, cuerpo, esperada in casos:
            with self.subTest(codigo=codigo, cuerpo=cuerpo[:20]):
                self.assertIs(clasificar_http(codigo, cuerpo), esperada)

    def test_el_403_de_cloudflare_no_dice_que_la_clave_esta_mal(self):
        p = _proveedor()
        with mock.patch.object(openai_compat.urllib.request, "urlopen",
                               mock.Mock(side_effect=_http_error(403, CUERPO_CLOUDFLARE))):
            with self.assertRaises(ErrorProveedor) as ctx:
                p.responder(PETICION)
        self.assertIs(ctx.exception.clase, Clase.BLOQUEO_CLIENTE)
        self.assertNotIn("Pulsa K", ctx.exception.mensaje_usuario())
        self.assertIn("No es la clave", ctx.exception.mensaje_usuario())
        estado = p.presupuesto._estado("m")
        self.assertEqual(estado.tokens, 0, "no llegó a la API: no consume tokens")
        self.assertEqual(estado.tokens_reservados, 0)

    def test_gemini_distingue_el_borde(self):
        class Error403(Exception):
            code = 403

            def __init__(self, texto):
                super().__init__(texto)
        self.assertIs(mod_gemini.clasificar(Error403("error code: 1010")),
                      Clase.BLOQUEO_CLIENTE)
        self.assertIs(mod_gemini.clasificar(Error403("403 PERMISSION_DENIED. API_KEY_INVALID")),
                      Clase.AUTENTICACION)

    def test_la_medicion_b4_clasifica_igual(self):
        medir = _script("medir_modelos")
        endpoint = Endpoint(nombre="m", url="https://ejemplo.invalid/v1", modelo="m")
        with mock.patch.object(medir.urllib.request, "urlopen",
                               mock.Mock(side_effect=_http_error(403, CUERPO_CLOUDFLARE))):
            r = medir.medir_una(endpoint, "c", [], 10, 5)
        self.assertEqual(r["estado"], "bloqueo_cliente")


# ================================================ 3. Identificadores de cuenta
class IdentificadoresTest(unittest.TestCase):
    def test_redacta_el_valor_y_conserva_el_mensaje(self):
        limpio = registro.redactar(CUERPO_OPENROUTER)
        self.assertNotIn(ID_FALSO, limpio)
        self.assertIn(registro.MARCA_ID, limpio)
        self.assertIn("unavailable for free", limpio)
        self.assertIn("deepseek/ejemplo-1017", limpio, "el slug sugerido es útil")

    def test_variantes_de_campo_y_sueltos(self):
        casos = ['"userId": "u-123456"', "account_id=acc_998877", "org_id: org_ab12cd34",
                 '"organization_id":"9f8e7d6c"', f"cuenta {ID_FALSO} bloqueada"]
        for texto in casos:
            with self.subTest(texto=texto):
                limpio = registro.redactar(texto)
                self.assertIn(registro.MARCA_ID, limpio)

    def test_no_toca_modelos_ni_cifras(self):
        texto = "modelo deepseek/deepseek-v4.1-flash-1017 · 663 tokens · HTTP 404"
        self.assertEqual(registro.redactar(texto), texto)

    def test_ni_el_error_ni_el_registro_llevan_el_identificador(self):
        p = _proveedor()
        with mock.patch.object(openai_compat.urllib.request, "urlopen",
                               mock.Mock(side_effect=_http_error(404, CUERPO_OPENROUTER))):
            with self.assertLogs("emotibot", level="WARNING") as capturado:
                with self.assertRaises(ErrorProveedor) as ctx:
                    p.responder(PETICION)
        self.assertIs(ctx.exception.clase, Clase.MODELO)
        self.assertNotIn(ID_FALSO, ctx.exception.detalle)
        self.assertIn("unavailable for free", ctx.exception.detalle)
        self.assertFalse(any(ID_FALSO in linea for linea in capturado.output))

    def test_el_filtro_del_registro_tambien_redacta(self):
        registro_prueba = logging.LogRecord("emotibot.x", logging.WARNING, "", 0,
                                            "cuerpo: %s", (CUERPO_OPENROUTER,), None)
        registro._FiltroRedaccion().filter(registro_prueba)
        self.assertNotIn(ID_FALSO, registro_prueba.getMessage())

    def test_el_diagnostico_no_lo_imprime(self):
        diag = _script("diagnostico_ia")
        endpoint = Endpoint(nombre="razonamiento", url="https://ejemplo.invalid/v1",
                            modelo="m", clave="openrouter")
        salida = io.StringIO()
        with mock.patch.object(diag, "cargar_endpoints", lambda _r: {"razonamiento": endpoint}), \
                mock.patch.object(diag.credenciales, "cargar", lambda _n: "clave-de-prueba"), \
                mock.patch.object(diag.rutas, "ESTADO", Path(tempfile.mkdtemp())), \
                mock.patch.object(openai_compat.urllib.request, "urlopen",
                                  mock.Mock(side_effect=_http_error(404, CUERPO_OPENROUTER))), \
                contextlib.redirect_stdout(salida):
            diag.probar_endpoints(Ajustes(), Identidad())
        texto = salida.getvalue()
        self.assertIn("FALLO (modelo)", texto)
        self.assertNotIn(ID_FALSO, texto)


# =================================================== 5. Firma de Gemini
class FirmaGeminiTest(unittest.TestCase):
    def _sdk_falso(self):
        resultado = SimpleNamespace(text="listo", candidates=[SimpleNamespace(
            finish_reason="STOP")], usage_metadata=None)

        class Modelos:
            def generate_content(self, model, contents, config):
                return resultado
        tipos = SimpleNamespace(GenerateContentConfig=lambda **kw: kw, ThinkingConfig=None)
        return tipos, SimpleNamespace(models=Modelos())

    def test_el_diagnostico_de_gemini_ya_no_lanza_typeerror(self):
        diag = _script("diagnostico_ia")
        tipos, cliente = self._sdk_falso()
        salida = io.StringIO()
        with mock.patch.object(mod_gemini, "_cargar_sdk", lambda: (None, tipos)), \
                mock.patch.object(mod_gemini, "_cliente", lambda *_a: cliente), \
                mock.patch.object(diag.rutas, "ESTADO", Path(tempfile.mkdtemp())), \
                contextlib.redirect_stdout(salida):
            diag.probar_modelo(Ajustes(), Identidad(), "clave-de-prueba", "modelo-x")
        self.assertIn("resultado: OK", salida.getvalue())

    def test_produccion_pide_la_clave_por_nombre(self):
        """El orquestador de la aplicación construye «remoto» con la firma buena."""
        from emotibot.ia.orquestador import Orquestador
        pedidas = []

        def obtener_clave(nombre):
            pedidas.append(nombre)
            return ""
        with mock.patch.object(rutas, "ARCHIVO_PRESUPUESTO",
                               Path(tempfile.mkdtemp()) / "p.json"):
            orq = Orquestador(Ajustes(), Identidad(), obtener_clave)
        self.assertFalse(orq.remoto.disponible())
        self.assertIn("gemini", pedidas)


if __name__ == "__main__":
    unittest.main()
