"""Enrutado entre el modelo de conversación y el de razonamiento."""
import unittest

from emotibot.ia import enrutador
from emotibot.ia.openai_compat import Endpoint, cargar_endpoints
from emotibot import rutas

CHARLA = (
    "hola, ¿cómo estás?",
    "¿quién eres?",
    "gracias por todo",
    "cuéntame un chiste",
    "me siento solo hoy",
    "estoy agobiado y no sé qué hacer",
    "adiós",
)

ANALISIS = (
    "¿por qué el cielo es azul?",
    "compara Python y Java",
    "¿cuál es el mejor momento para estudiar?",
    "ayúdame a decidir si cambio de carrera",
    "explícame cómo funciona un motor",
    "¿debería aceptar ese trabajo?",
    "no sé si juntar las dos versiones o seguir por separado",
)


class PapelTest(unittest.TestCase):
    def test_la_charla_va_al_modelo_rapido(self):
        for texto in CHARLA:
            with self.subTest(texto=texto):
                self.assertEqual(enrutador.papel(texto),
                                 enrutador.CONVERSACION)

    def test_el_analisis_va_al_modelo_de_razonamiento(self):
        for texto in ANALISIS:
            with self.subTest(texto=texto):
                self.assertEqual(enrutador.papel(texto),
                                 enrutador.RAZONAMIENTO)

    def test_lo_emocional_se_queda_en_conversacion(self):
        """Decisión de producto: ante malestar importa la rapidez y el tono,
        no un análisis más profundo que además tarda más."""
        self.assertEqual(enrutador.papel("hoy me siento fatal, todo me sale mal"),
                         enrutador.CONVERSACION)

    def test_una_intervencion_larga_pide_razonamiento(self):
        largo = ("tengo que entregar el robot el viernes y el micrófono "
                 "todavía falla, además mi compañero empezó otra versión "
                 "por su cuenta y no tengo claro cómo encajarlo todo antes "
                 "de la fecha")
        self.assertEqual(enrutador.papel(largo), enrutador.RAZONAMIENTO)

    def test_texto_vacio_no_rompe(self):
        self.assertEqual(enrutador.papel(""), enrutador.CONVERSACION)
        self.assertEqual(enrutador.papel("   "), enrutador.CONVERSACION)


class OrdenTest(unittest.TestCase):
    BASE = ("conversacion", "razonamiento", "remoto", "local", "guion")

    def test_pone_delante_el_papel_elegido(self):
        self.assertEqual(enrutador.ordenar(self.BASE, "hola")[0],
                         "conversacion")
        self.assertEqual(enrutador.ordenar(self.BASE, "compara A y B")[0],
                         "razonamiento")

    def test_conserva_todos_los_proveedores(self):
        """Reordenar no puede perder respaldos: el guion siempre al final."""
        orden = enrutador.ordenar(self.BASE, "analiza esto")
        self.assertEqual(sorted(orden), sorted(self.BASE))
        self.assertEqual(orden[-1], "guion")

    def test_si_el_papel_no_esta_en_el_orden_no_cambia_nada(self):
        base = ("remoto", "guion")
        self.assertEqual(enrutador.ordenar(base, "compara A y B"), list(base))


class EndpointTest(unittest.TestCase):
    def test_el_archivo_del_repositorio_se_lee(self):
        endpoints = cargar_endpoints(rutas.ARCHIVO_PROVEEDORES)
        for esperado in ("conversacion", "razonamiento", "local"):
            self.assertIn(esperado, endpoints)

    def test_las_notas_con_guion_bajo_no_son_proveedores(self):
        endpoints = cargar_endpoints(rutas.ARCHIVO_PROVEEDORES)
        self.assertFalse([n for n in endpoints if n.startswith("_")])

    def test_sin_url_no_esta_configurado(self):
        self.assertFalse(Endpoint("x", url="", modelo="m").configurado)
        self.assertFalse(Endpoint("x", url="http://a/v1", modelo="").configurado)
        self.assertTrue(Endpoint("x", url="http://a/v1", modelo="m").configurado)

    def test_reconoce_un_servidor_local(self):
        self.assertTrue(Endpoint("x", url="http://127.0.0.1:8080/v1").es_local)
        self.assertTrue(Endpoint("x", url="http://localhost:8080/v1").es_local)
        self.assertFalse(Endpoint("x", url="https://api.deepseek.com/v1").es_local)

    def test_sin_nombre_de_clave_no_necesita_clave(self):
        self.assertFalse(Endpoint("local", clave="").necesita_clave)
        self.assertTrue(Endpoint("deepseek", clave="deepseek").necesita_clave)

    def test_cada_proveedor_trae_su_propio_limite(self):
        """Groq da 1.000 solicitudes al día y un :free de OpenRouter 50: un
        tope global dejaría corto a uno y pasado de rosca al otro."""
        endpoints = cargar_endpoints(rutas.ARCHIVO_PROVEEDORES)
        conversacion = endpoints["conversacion"]
        razonamiento = endpoints["razonamiento"]
        self.assertGreater(conversacion.max_dia, razonamiento.max_dia)
        for endpoint in endpoints.values():
            self.assertGreaterEqual(endpoint.max_dia, 1)
            self.assertGreaterEqual(endpoint.max_minuto, 1)


class PresupuestoPorModeloTest(unittest.TestCase):
    def _presupuesto(self):
        import tempfile
        from pathlib import Path as P
        from emotibot.ia.presupuesto import Presupuesto
        return Presupuesto(500, 60, ruta=P(tempfile.mkdtemp()) / "p.json")

    def test_cada_modelo_respeta_su_limite(self):
        presupuesto = self._presupuesto()
        presupuesto.fijar_limites("generoso", 100, 30)
        presupuesto.fijar_limites("estricto", 2, 30)
        for _ in range(2):
            presupuesto.registrar_consulta("estricto")
            presupuesto.registrar_consulta("generoso")
        self.assertFalse(presupuesto.puede_consultar("estricto")[0])
        self.assertTrue(presupuesto.puede_consultar("generoso")[0])

    def test_sin_limite_propio_usa_el_general(self):
        presupuesto = self._presupuesto()
        permitido, _ = presupuesto.puede_consultar("desconocido")
        self.assertTrue(permitido)


if __name__ == "__main__":
    unittest.main()
