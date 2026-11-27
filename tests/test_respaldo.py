"""La cadena de respaldo (23-11-2026).

- Gemini tiene su timeout PROPIO (20 s), más largo que los 12 s de Groq. El
  SDK lo manda al servidor como plazo (X-Server-Timeout): con 12 s era el
  servidor el que cortaba con 504 a los ~11,6 s.
- gpt-oss-20b va justo detrás de Qwen: si Qwen falla o se cuelga, contesta
  gpt-oss antes de ir a Gemini. Qwen sigue siendo el principal.
Sin red: la petición del SDK se construye pero no se envía, y los
proveedores de la cadena son simulados.
"""
import unittest
from unittest import mock

from emotibot import ajustes as mod_ajustes
from emotibot import identidad as mod_identidad
from emotibot.ia import gemini
from emotibot.ia.base import Clase, ErrorProveedor, Respuesta
from emotibot.ia.orquestador import Orquestador

CANDIDATO = "candidato_gpt_oss_20b"


class TimeoutGeminiTest(unittest.TestCase):
    def setUp(self):
        self.config = mod_ajustes.cargar()

    def test_gemini_tiene_el_suyo_y_es_mas_largo_que_el_de_groq(self):
        ia = self.config.ia
        self.assertEqual(ia.timeout_gemini_ms, 20000)
        self.assertEqual(ia.timeout_remoto_ms, 12000, "Groq no cambia")
        self.assertGreater(ia.timeout_gemini_ms, ia.timeout_remoto_ms)

    def test_el_cliente_de_gemini_usa_el_suyo(self):
        pedidos = []

        class Cliente:
            class models:
                @staticmethod
                def generate_content(**_):
                    raise RuntimeError("no se llega a enviar")

        def cliente(clave, timeout_ms):
            pedidos.append(timeout_ms)
            return Cliente()

        presupuesto = Orquestador(self.config, mod_identidad.cargar(),
                                  lambda n: "").presupuesto
        proveedor = gemini.ProveedorGemini(self.config.ia, presupuesto, lambda n: "x" * 30)
        from emotibot.ia.base import Peticion
        with mock.patch.object(gemini, "_cliente", cliente):
            with self.assertRaises(ErrorProveedor):
                proveedor.responder(Peticion(texto="hola", instrucciones="i"))
        self.assertEqual(pedidos, [self.config.ia.timeout_gemini_ms])

    def test_el_servidor_recibe_ese_plazo(self):
        """El SDK real pone X-Server-Timeout con el timeout del cliente: es lo
        que convierte nuestro plazo en un 504 del servidor."""
        gemini.olvidar_clientes()
        self.addCleanup(gemini.olvidar_clientes)
        cliente = gemini._cliente("clave-de-prueba-" + "0" * 20,
                                  self.config.ia.timeout_gemini_ms)
        peticion = cliente._api_client._build_request(
            "post", "models/m:generateContent", {}, None)
        self.assertEqual(peticion.headers.get("X-Server-Timeout"), "20")

    def test_groq_sigue_con_12_s(self):
        orq = Orquestador(self.config, mod_identidad.cargar(), lambda n: "")
        for nombre in ("conversacion", CANDIDATO):
            self.assertEqual(orq._por_nombre[nombre].timeout_s, 12.0)


class _Falso:
    def __init__(self, nombre, error=None):
        self.nombre, self.error, self.llamadas = nombre, error, 0

    def disponible(self):
        return True

    def responder(self, peticion):
        self.llamadas += 1
        if self.error:
            raise ErrorProveedor(self.error, f"{self.nombre} falla")
        return Respuesta(texto=f"respuesta de {self.nombre}.", proveedor=self.nombre)


class CadenaTest(unittest.TestCase):
    def _orquestador(self, fallan=()):
        orq = Orquestador(mod_ajustes.cargar(), mod_identidad.cargar(), lambda n: "")
        falsos = {n: _Falso(n, Clase.TIEMPO if n in fallan else None)
                  for n in ("conversacion", CANDIDATO, "remoto", "local")}
        orq._por_nombre.update(falsos)
        return orq, falsos

    def test_qwen_bien_nadie_mas(self):
        orq, f = self._orquestador()
        self.assertEqual(orq.responder("hola, ¿qué tal?").proveedor, "conversacion")
        self.assertEqual([f[n].llamadas for n in (CANDIDATO, "remoto")], [0, 0])
        self.assertIsNone(orq.ultimo_aviso)

    def test_qwen_falla_contesta_gpt_oss_antes_que_gemini(self):
        orq, f = self._orquestador(fallan=("conversacion",))
        self.assertEqual(orq.responder("hola, ¿qué tal?").proveedor, CANDIDATO)
        self.assertEqual(f["remoto"].llamadas, 0)
        self.assertIsNotNone(orq.ultimo_aviso, "degradación avisada")

    def test_qwen_y_gpt_oss_fallan_contesta_gemini(self):
        orq, f = self._orquestador(fallan=("conversacion", CANDIDATO))
        self.assertEqual(orq.responder("hola, ¿qué tal?").proveedor, "remoto")
        self.assertEqual([f[n].llamadas for n in ("conversacion", CANDIDATO, "remoto")],
                         [1, 1, 1])

    def test_el_modelo_principal_sigue_siendo_qwen(self):
        orq = Orquestador(mod_ajustes.cargar(), mod_identidad.cargar(), lambda n: "")
        self.assertEqual(orq.config.ia.orden_proveedores[0], "conversacion")
        self.assertEqual(orq._por_nombre["conversacion"].modelo, "qwen/qwen3.8-27b")


if __name__ == "__main__":
    unittest.main()
