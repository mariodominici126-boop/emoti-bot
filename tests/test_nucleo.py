"""Identidad completa, ajustes, presupuesto, redacción de secretos y frases."""
import json
import tempfile
import unittest
from pathlib import Path

from emotibot import ajustes as mod_ajustes
from emotibot import registro
from emotibot.ia.base import Clase
from emotibot.ia.presupuesto import Presupuesto
from emotibot.identidad import cargar as cargar_identidad
from emotibot.voz.base import limpiar, partir_en_frases


class IdentidadTest(unittest.TestCase):
    """El prototipo ignoraba `proposito` y `limites` del JSON en silencio."""

    def test_lee_todos_los_campos_del_archivo(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "identidad.json"
            ruta.write_text(json.dumps({
                "nombre": "ROBOT-X",
                "creador": "Ana",
                "proposito": "PROPOSITO_UNICO",
                "limites": "LIMITES_UNICOS",
                "presentacion": "Soy ROBOT-X.",
                "aclaracion_modelo": "ACLARACION_UNICA",
                "estilo": ["Regla uno.", "Regla dos."],
            }), encoding="utf-8")
            identidad = cargar_identidad(ruta)

        self.assertEqual(identidad.nombre, "ROBOT-X")
        self.assertEqual(identidad.creador, "Ana")
        instrucciones = identidad.instrucciones()
        for esperado in ("PROPOSITO_UNICO", "LIMITES_UNICOS",
                         "ACLARACION_UNICA", "Regla uno.", "Regla dos."):
            self.assertIn(esperado, instrucciones,
                          f"{esperado} debe llegar al modelo")

    def test_archivo_invalido_no_rompe_el_arranque(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "identidad.json"
            ruta.write_text("{ esto no es json", encoding="utf-8")
            identidad = cargar_identidad(ruta)
        self.assertEqual(identidad.nombre, "EMOTI-BOT")


class AjustesTest(unittest.TestCase):
    def test_valida_dispositivo_alsa(self):
        self.assertEqual(mod_ajustes.dispositivo_valido("plughw:1,0"),
                         "plughw:1,0")
        self.assertIsNone(mod_ajustes.dispositivo_valido("hw:1,0; rm -rf /"))
        self.assertIsNone(mod_ajustes.dispositivo_valido(None))

    def test_carga_sin_excepciones_y_con_tipos_correctos(self):
        config = mod_ajustes.cargar()
        self.assertIsInstance(config.audio.frecuencia_captura, int)
        self.assertIsInstance(config.audio.factor_umbral, float)
        self.assertIsInstance(config.rostro.pantalla_completa, bool)
        self.assertIsInstance(config.ia.orden_proveedores, tuple)


class PresupuestoTest(unittest.TestCase):
    def _nuevo(self, **extra) -> Presupuesto:
        carpeta = tempfile.mkdtemp()
        base = dict(maximo_diario=3, maximo_por_minuto=2,
                    ruta=Path(carpeta) / "p.json")
        base.update(extra)
        return Presupuesto(**base)

    def test_limite_diario(self):
        p = self._nuevo(maximo_diario=2, maximo_por_minuto=50)
        self.assertTrue(p.puede_consultar("m")[0])
        p.registrar_consulta("m")
        p.registrar_consulta("m")
        self.assertFalse(p.puede_consultar("m")[0])

    def test_un_429_bloquea_sin_reintento(self):
        p = self._nuevo()
        p.registrar_rechazo_cuota("m")
        permitido, motivo = p.puede_consultar("m")
        self.assertFalse(permitido)
        self.assertIn("cuota", motivo.lower())

    def test_tres_429_bloquean_el_dia(self):
        p = self._nuevo()
        for _ in range(3):
            p.registrar_rechazo_cuota("m")
        self.assertTrue(p.modelos["m"].bloqueado_todo_el_dia)
        p.liberar("m")
        self.assertTrue(p.puede_consultar("m")[0])

    def test_modelos_independientes(self):
        p = self._nuevo()
        p.registrar_rechazo_cuota("flash")
        self.assertTrue(p.puede_consultar("flash-lite")[0])


class RedaccionTest(unittest.TestCase):
    def test_redacta_el_secreto_registrado(self):
        registro.olvidar_secretos()
        registro.proteger("supersecreto12345")
        texto = registro.redactar("error con clave supersecreto12345 dentro")
        self.assertNotIn("supersecreto12345", texto)
        self.assertIn(registro.MARCA, texto)

    def test_redacta_claves_con_forma_conocida_sin_registrarlas(self):
        registro.olvidar_secretos()
        texto = registro.redactar("key=AIzaSyA1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q")
        self.assertNotIn("AIzaSy", texto)


class FrasesTest(unittest.TestCase):
    def test_divide_y_une_las_muy_cortas(self):
        frases = partir_en_frases(
            "Hola. Soy EMOTI-BOT y estoy aquí para acompañarte un rato. "
            "¿Cómo estás?"
        )
        self.assertGreaterEqual(len(frases), 2)
        self.assertTrue(all(len(f) >= 10 for f in frases))

    def test_limpia_markdown_porque_se_pronuncia(self):
        self.assertNotIn("*", limpiar("texto con **negritas** y `código`"))

    def test_texto_vacio(self):
        self.assertEqual(partir_en_frases("   "), [])


class ClasesErrorTest(unittest.TestCase):
    def test_la_cuota_no_es_transitoria(self):
        from emotibot.ia.base import ErrorProveedor
        self.assertFalse(ErrorProveedor(Clase.CUOTA).es_transitorio)
        self.assertTrue(ErrorProveedor(Clase.SOBRECARGA).es_transitorio)


if __name__ == "__main__":
    unittest.main()
