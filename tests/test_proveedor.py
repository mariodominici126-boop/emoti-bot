"""Comportamiento del proveedor remoto ante los errores del servicio.

Sin red ni clave: se simulan las respuestas del servicio. Lo que se comprueba
es la política, que es donde estuvo el fallo real.
"""
import dataclasses
import tempfile
import unittest
from pathlib import Path

from emotibot.ajustes import cargar
from emotibot.ia.base import Clase, Peticion
from emotibot.ia.gemini import ProveedorGemini, clasificar
from emotibot.ia.presupuesto import Presupuesto

PETICION = Peticion(texto="hola", instrucciones="sé breve")


class Error400(Exception):
    code = 400

    def __str__(self):
        return "400 INVALID_ARGUMENT. Request contains an invalid argument."


class Error429(Exception):
    code = 429

    def __str__(self):
        return "429 RESOURCE_EXHAUSTED. Quota exceeded."


class Error503(Exception):
    code = 503

    def __str__(self):
        return "503 UNAVAILABLE"


class _Resultado:
    text = "listo"


class TypesFalso:
    class ThinkingConfig:
        model_fields = {"thinking_level": None}

        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class GenerateContentConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs


class ClienteFalso:
    """Rechaza con 400 cualquier petición que lleve las opciones indicadas."""

    def __init__(self, rechaza=(), error=Error400):
        self.rechaza = set(rechaza)
        self.error = error
        self.intentos: list[list[str]] = []
        self.models = self

    def generate_content(self, model, contents, config):
        self.intentos.append(sorted(config.kwargs))
        if not self.rechaza or self.rechaza & set(config.kwargs):
            if self.rechaza:
                raise self.error()
            raise self.error()
        return _Resultado()


class ClienteSiempreFalla(ClienteFalso):
    def generate_content(self, model, contents, config):
        self.intentos.append(sorted(config.kwargs))
        raise self.error()


def proveedor(**extra) -> ProveedorGemini:
    config = dataclasses.replace(cargar().ia, **extra)
    presupuesto = Presupuesto(
        100, 50, ruta=Path(tempfile.mkdtemp()) / "presupuesto.json"
    )
    # Mismo contrato que la aplicación: obtener_clave(nombre) -> clave.
    return ProveedorGemini(config, presupuesto, lambda _nombre: "clave-de-prueba")


class ClasificacionTest(unittest.TestCase):
    def test_distingue_peticion_invalida_de_cuota(self):
        """Confundirlas fue el fallo: un 400 caía en 'otro' y no decía nada."""
        self.assertIs(clasificar(Error400()), Clase.PETICION)
        self.assertIs(clasificar(Error429()), Clase.CUOTA)
        self.assertIs(clasificar(Error503()), Clase.SOBRECARGA)


class DegradacionTest(unittest.TestCase):
    def test_un_400_baja_de_nivel_y_acaba_funcionando(self):
        """El caso real: el modelo no admitía `thinking_config`."""
        prov = proveedor(pensamiento="bajo")
        cliente = ClienteFalso(rechaza={"thinking_config"})
        resultado = prov._generar(cliente, TypesFalso, PETICION)
        self.assertEqual(resultado.text, "listo")
        self.assertEqual(len(cliente.intentos), 2)
        self.assertIn("thinking_config", cliente.intentos[0])
        self.assertNotIn("thinking_config", cliente.intentos[1])

    def test_sin_razonamiento_acierta_a_la_primera(self):
        """Valor por defecto: no se envía lo que suele sobrar."""
        prov = proveedor()
        cliente = ClienteFalso(rechaza={"thinking_config"})
        prov._generar(cliente, TypesFalso, PETICION)
        self.assertEqual(len(cliente.intentos), 1)

    def test_no_repite_dos_niveles_identicos(self):
        """Repetir la misma petición solo gastaría una consulta de más."""
        prov = proveedor()
        cliente = ClienteFalso(rechaza={"response_mime_type"})
        prov._generar(cliente, TypesFalso, PETICION)
        firmas = [tuple(i) for i in cliente.intentos]
        self.assertEqual(len(firmas), len(set(firmas)))

    def test_recuerda_el_nivel_que_funciona(self):
        prov = proveedor()
        prov._generar(ClienteFalso(rechaza={"response_mime_type"}),
                      TypesFalso, PETICION)
        segundo = ClienteFalso(rechaza={"response_mime_type"})
        prov._generar(segundo, TypesFalso, PETICION)
        self.assertEqual(len(segundo.intentos), 1,
                         "no debe volver a probar lo que ya falló")

    def test_un_429_no_se_reintenta_jamas(self):
        """La regla central: un 429 es un techo, no un fallo pasajero."""
        prov = proveedor()
        cliente = ClienteSiempreFalla(error=Error429)
        with self.assertRaises(Error429):
            prov._generar(cliente, TypesFalso, PETICION)
        self.assertEqual(len(cliente.intentos), 1)

    def test_una_sobrecarga_tampoco_se_reintenta_aqui(self):
        prov = proveedor()
        cliente = ClienteSiempreFalla(error=Error503)
        with self.assertRaises(Error503):
            prov._generar(cliente, TypesFalso, PETICION)
        self.assertEqual(len(cliente.intentos), 1)

    def test_si_ningun_nivel_vale_propaga_el_error(self):
        prov = proveedor()
        cliente = ClienteSiempreFalla(error=Error400)
        with self.assertRaises(Error400):
            prov._generar(cliente, TypesFalso, PETICION)
        self.assertGreaterEqual(len(cliente.intentos), 2)
        self.assertLessEqual(len(cliente.intentos), 3)


if __name__ == "__main__":
    unittest.main()
