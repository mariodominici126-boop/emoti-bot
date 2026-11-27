"""Fase 1, Bloque B: los instrumentos, sin micrófono, sin red y sin claves.

Aquí se prueba que los instrumentos miden bien y respetan la privacidad y
los topes. No hay ninguna medición real: esas las hace el responsable.
"""
import importlib.util
import io
import json
import logging
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from emotibot import depuracion, evaluacion, medicion
from emotibot.ajustes import Ajustes
from emotibot.audio import senal
from emotibot.ia import longitud
from emotibot.ia.base import Peticion, Respuesta
from emotibot.ia.openai_compat import Endpoint

RAIZ = Path(__file__).resolve().parent.parent
FREC = 16000


def _script(nombre):
    spec = importlib.util.spec_from_file_location(nombre, RAIZ / "bin" / f"{nombre}.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


# ===================================================================== B2
class DepuracionSttTest(unittest.TestCase):
    def test_apagada_al_arrancar_y_no_muestra_nada(self):
        d = depuracion.DepuracionStt()
        self.assertFalse(d.activa)
        self.assertFalse(d.mostrar("hola", es_seguridad=False))
        self.assertEqual(d.linea(), "")

    def test_activa_muestra_y_caduca(self):
        d = depuracion.DepuracionStt(segundos_visible=5)
        d.alternar()
        self.assertTrue(d.mostrar("hola  qué tal", False, ahora=100.0))
        self.assertIn("«hola qué tal»", d.linea(ahora=101.0))
        self.assertNotIn("hola", d.linea(ahora=106.0))
        self.assertIn("ACTIVA", d.linea(ahora=106.0), "el aviso sigue visible")

    def test_la_ruta_de_seguridad_no_se_muestra_y_borra_lo_anterior(self):
        d = depuracion.DepuracionStt()
        d.alternar()
        d.mostrar("frase anterior", False, ahora=0.0)
        self.assertFalse(d.mostrar("texto de crisis", True, ahora=1.0))
        linea = d.linea(ahora=1.5)
        self.assertNotIn("crisis", linea)
        self.assertNotIn("anterior", linea)

    def test_apagar_borra_al_instante(self):
        d = depuracion.DepuracionStt()
        d.alternar()
        d.mostrar("algo", False)
        d.alternar()
        self.assertEqual(d.linea(), "")
        d.alternar()
        self.assertNotIn("algo", d.linea())

    def test_nunca_escribe_en_el_registro(self):
        d = depuracion.DepuracionStt()
        with self.assertNoLogs(level=logging.DEBUG):
            d.alternar()
            d.mostrar("secreto", False)
            d.linea()

    def test_no_hay_ajuste_que_la_deje_encendida(self):
        """Solo la tecla la activa: no existe en la configuración."""
        texto = (RAIZ / "config" / "ajustes.json").read_text(encoding="utf-8")
        self.assertNotIn("depuracion", texto.lower())

    def test_la_aplicacion_no_registra_ni_encola_texto_de_seguridad(self):
        fuente = (RAIZ / "emotibot" / "app.py").read_text(encoding="utf-8")
        self.assertIn('"" if es_seguridad else transcripcion.texto', fuente)
        for linea in fuente.splitlines():
            if "log." in linea:
                self.assertNotIn("transcripcion.texto", linea)


# ===================================================================== B1
class SttTest(unittest.TestCase):
    def test_guion_de_treinta_frases(self):
        self.assertEqual(len(medicion.GUION_STT), 30)
        self.assertEqual(len(set(medicion.GUION_STT)), 30)

    def test_errores_de_palabra(self):
        self.assertEqual(medicion.errores_de_palabra("Hola, ¿cómo estás?",
                                                     "hola como estas"), (0, 3))
        self.assertEqual(medicion.errores_de_palabra("a b c d", "a x c"), (2, 4))
        self.assertEqual(medicion.errores_de_palabra("a b", ""), (2, 2))

    def test_categorias(self):
        ref = "Mañana tengo una reunión a las diez y media."
        casos = [
            (dict(hipotesis="mañana tengo una reunión a las diez y media"), "correcta"),
            (dict(hipotesis="mañana tengo una reunión"), "corte_prematuro"),
            (dict(hipotesis="mañana tengo una canción a las diez y media"),
             "error_reconocimiento"),
            (dict(hipotesis=""), "transcripcion_vacia"),
            (dict(hipotesis=None, error_motor=True), "fallo_motor"),
            (dict(hipotesis=None, error_captura=True), "fallo_captura"),
            (dict(hipotesis=None, sin_voz=True), "sin_voz"),
        ]
        for extra, esperada in casos:
            hip = extra.pop("hipotesis")
            with self.subTest(esperada=esperada):
                self.assertEqual(medicion.clasificar_stt(ref, hip, **extra), esperada)
                self.assertIn(esperada, medicion.CATEGORIAS_STT)

    def test_treinta_sin_fallos_no_es_fiabilidad_perfecta(self):
        bajo, alto = medicion.intervalo_wilson(0, 30)
        self.assertEqual(bajo, 0.0)
        self.assertGreater(alto, 0.10)

    def test_el_resumen_no_contiene_texto(self):
        medir_stt = _script("medir_stt")
        self.assertNotIn("texto", medir_stt.COLUMNAS)
        self.assertNotIn("transcripcion", medir_stt.COLUMNAS)
        filas = [{"categoria": "correcta", "errores": "0", "palabras_ref": "5",
                  "corregida": "0"},
                 {"categoria": "fallo_motor", "errores": "", "palabras_ref": "4",
                  "corregida": "1"}]
        with mock.patch.object(medir_stt.metricas, "leer_csv", lambda *_: []):
            texto = medir_stt.resumir(filas)
        self.assertIn("Fallos técnicos: 1/2", texto)


# ===================================================================== B3
class VadTest(unittest.TestCase):
    def setUp(self):
        self.audio = Ajustes().audio
        self.a = medicion.voz_sintetica(1.0, FREC, semilla=1)
        self.b = medicion.voz_sintetica(1.2, FREC, semilla=2)
        self.ruido = medicion.ruido_sintetico(1.0, FREC)

    def test_guion_de_veinte_intervenciones(self):
        self.assertEqual(len(medicion.GUION_VAD) * len(medicion.PAUSAS_B3), 20)

    def test_pausa_corta_no_corta(self):
        r = medicion.simular_pausa(self.a, self.b, self.ruido, 0.3, FREC, self.audio,
                                   silencio_final_s=0.6)
        self.assertFalse(r.corte_prematuro)
        self.assertTrue(r.intervencion_completa)
        self.assertAlmostEqual(r.cierre_desde_ultima_voz_s, 0.6, delta=0.06)

    def test_pausa_mas_larga_que_el_umbral_corta(self):
        r = medicion.simular_pausa(self.a, self.b, self.ruido, 1.2, FREC, self.audio,
                                   silencio_final_s=0.6)
        self.assertTrue(r.corte_prematuro)
        self.assertFalse(r.intervencion_completa)
        self.assertIsNone(r.cierre_desde_ultima_voz_s)

    def test_subir_el_umbral_evita_el_corte(self):
        r = medicion.simular_pausa(self.a, self.b, self.ruido, 0.8, FREC, self.audio,
                                   silencio_final_s=1.2)
        self.assertFalse(r.corte_prematuro)

    def test_sin_voz_se_distingue(self):
        silencio = medicion.ruido_sintetico(1.0, FREC, semilla=5)
        r = medicion.simular_pausa(silencio, silencio, self.ruido, 0.5, FREC, self.audio)
        self.assertTrue(r.sin_voz)

    def test_recorte_por_energia_es_independiente_del_vad(self):
        relleno = medicion.ruido_sintetico(0.5, FREC)
        voz = medicion.voz_sintetica(1.0, FREC)
        recortado = medicion.recortar_a_voz(relleno + voz + relleno, FREC,
                                            senal.rms(relleno))
        self.assertLess(abs(senal.duracion_s(recortado, FREC) - 1.0), 0.12)

    def test_tabla(self):
        resultados = [medicion.simular_pausa(self.a, self.b, self.ruido, p, FREC,
                                             self.audio, silencio_final_s=0.6)
                      for p in medicion.PAUSAS_B3]
        tabla = medicion.tabla_pausas(resultados)
        self.assertEqual([f["pausa_s"] for f in tabla], list(medicion.PAUSAS_B3))
        self.assertEqual(tabla[0]["tasa_corte"], 0.0)
        self.assertEqual(tabla[-1]["tasa_corte"], 1.0)


# ===================================================================== B5
class LongitudTest(unittest.TestCase):
    def test_el_archivo_trae_las_dos_rutas_con_los_valores_definitivos(self):
        """§13.8b, 22-11-2026: derivados de las salidas reales (ver el archivo).
        Antes eran los de la v1.7: 120 y 320."""
        tabla = longitud.cargar()
        self.assertEqual(tabla["conversacion"].max_tokens, 96)
        self.assertEqual(tabla["razonamiento"].max_tokens, 160)
        self.assertEqual(tabla["conversacion"].instruccion, "")

    def test_sin_archivo_no_hay_rutas(self):
        self.assertEqual(longitud.cargar(Path(tempfile.mkdtemp()) / "no.json"), {})

    def test_avisa_si_el_objetivo_no_cabe_en_el_tope(self):
        ruta = Path(tempfile.mkdtemp()) / "l.json"
        ruta.write_text(json.dumps({"x": {"max_tokens": 50,
                                          "palabras_objetivo": 80}}), encoding="utf-8")
        with self.assertLogs("emotibot", level="WARNING"):
            longitud.cargar(ruta)

    def test_el_tope_va_con_la_pregunta_aunque_conteste_otro(self):
        """El caso real: razonamiento atendido por el respaldo Gemini."""
        from emotibot import rutas
        from emotibot.ia.orquestador import Orquestador
        with mock.patch.object(rutas, "ARCHIVO_PRESUPUESTO",
                               Path(tempfile.mkdtemp()) / "p.json"):
            orq = Orquestador(Ajustes(), __import__("emotibot.identidad").identidad
                              .Identidad(), lambda _n: "")
        vistas = []

        class Falso:
            nombre = "remoto"
            modelo = "falso"
            ultimo_motivo = ""

            def disponible(self):
                return True

            def responder(self, peticion: Peticion):
                vistas.append(peticion.max_tokens)
                return Respuesta("Vale.", "remoto")
        orq._por_nombre = {"remoto": Falso(), "guion": orq.guion}
        import dataclasses
        orq.config = dataclasses.replace(orq.config, ia=dataclasses.replace(
            orq.config.ia, orden_proveedores=("remoto", "guion")))
        orq.responder("¿Por qué el cielo es azul? Explícamelo.")
        orq.responder("hola")
        tabla = longitud.cargar()
        self.assertEqual(vistas, [tabla["razonamiento"].max_tokens,
                                  tabla["conversacion"].max_tokens])

    def test_medidor_de_longitud(self):
        medir = _script("medir_longitud")
        filas = [{"papel": "conversacion", "proveedor": "conversacion",
                  "palabras_respuesta": str(n), "motivo_fin": m, "recortada": "",
                  "t_total": "10", "t_primer_sonido": "2"}
                 for n, m in ((30, "completa"), (60, "truncada"), (40, "completa"))]
        filas.append({"papel": "", "proveedor": "guion"})   # turno sin ruta
        r = medir.resumir(filas, longitud.cargar())[0]
        self.assertEqual((r["turnos"], r["truncadas"]), (3, 1))
        self.assertEqual(r["palabras_mediana"], 40)
        self.assertAlmostEqual(r["sobre_objetivo"], 1 / 3)
        self.assertEqual(r["hablada_mediana_s"], 8)


# ===================================================================== B4
class _Sse:
    def __init__(self, lineas):
        self._lineas = [l.encode() for l in lineas]

    def __iter__(self):
        return iter(self._lineas)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class ModelosTest(unittest.TestCase):
    def setUp(self):
        self.mod = _script("medir_modelos")

    def test_lee_ttft_usage_y_motivo_del_stream(self):
        lineas = [
            'data: {"choices":[{"delta":{"role":"assistant"}}]}',
            'data: {"choices":[{"delta":{"content":"Hola"}}]}',
            'data: {"choices":[{"delta":{"content":"."},"finish_reason":"length"}]}',
            'data: {"choices":[],"usage":{"prompt_tokens":700,"completion_tokens":120}}',
            "data: [DONE]",
        ]
        endpoint = Endpoint(nombre="m", modelo="m", temperatura=0.5,
                                   url="https://ejemplo.invalid/v1")
        with mock.patch.object(self.mod.urllib.request, "urlopen",
                               lambda *_a, **_k: _Sse(lineas)):
            r = self.mod.medir_una(endpoint, "clave", [], 120, 5)
        self.assertEqual(r["estado"], "ok")
        self.assertIsNotNone(r["ttft"])
        self.assertEqual((r["tokens_entrada"], r["tokens_salida"]), (700, 120))
        self.assertEqual(r["motivo_fin"], "truncada")

    def test_un_429_se_clasifica_como_cuota(self):
        import urllib.error

        def falla(*_a, **_k):
            raise urllib.error.HTTPError("u", 429, "x", {}, io.BytesIO(b""))
        endpoint = Endpoint(nombre="m", modelo="m", temperatura=0.5,
                                   url="https://ejemplo.invalid/v1")
        with mock.patch.object(self.mod.urllib.request, "urlopen", falla):
            self.assertEqual(self.mod.medir_una(endpoint, "c", [], 10, 5)["estado"],
                             "cuota")

    def test_topes_de_la_seccion_13_5(self):
        hosts = {"conversacion": "api.groq.com", "razonamiento": "openrouter.ai"}
        vacio = {"franjas": {}, "total": {}}
        self.assertEqual(self.mod.comprobar_topes(
            {"conversacion": 20, "razonamiento": 8}, hosts, "f1", vacio), [])
        self.assertTrue(self.mod.comprobar_topes(
            {"conversacion": 21, "razonamiento": 0}, hosts, "f1", vacio))
        self.assertTrue(self.mod.comprobar_topes(
            {"conversacion": 0, "razonamiento": 9}, hosts, "f1", vacio))
        usado = {"franjas": {"f1": {"openrouter.ai": 8}},
                 "total": {"openrouter.ai": 12}}
        problemas = self.mod.comprobar_topes(
            {"conversacion": 0, "razonamiento": 5}, hosts, "f2", usado)
        self.assertTrue(any("16" in p for p in problemas), "tope total de la fase")


# ===================================================================== B6
def _respuestas():
    return {
        conf: {"situaciones": {
            "S01": {"tipo": "charla", "turnos": ["hola"], "respuestas": [f"{conf}-1"]},
            "S02": {"tipo": "continuidad", "turnos": ["a", "b"],
                    "respuestas": [f"{conf}-2a", f"{conf}-2b"]},
        }} for conf in ("alfa", "beta")}


class EvaluacionTest(unittest.TestCase):
    def test_la_bateria_fija(self):
        from emotibot import rutas
        version, situaciones = evaluacion.cargar_bateria(
            rutas.CONFIG_REPO / "evaluacion_bateria.json")
        self.assertGreaterEqual(len(situaciones), 15)
        self.assertLessEqual(len(situaciones), 20)
        self.assertTrue(any(len(s.turnos) > 1 for s in situaciones))

    def test_hojas_anonimas_y_clave_aparte(self):
        hojas, clave = evaluacion.preparar(_respuestas(), 3, semilla=1)
        self.assertEqual(len(hojas), 3)
        self.assertEqual(len(clave), 4)
        for hoja in hojas:
            texto = json.dumps(hoja)
            self.assertNotIn("alfa\"", texto.replace("alfa-", ""))
            self.assertNotIn("configuracion", texto)
            for fila in hoja:
                self.assertRegex(fila["id"], r"^R-[0-9A-F]{6}$")
        self.assertNotEqual([f["id"] for f in hojas[0]],
                            [f["id"] for f in hojas[1]],
                            "cada evaluador ve otro orden")

    def test_el_contexto_de_varios_turnos(self):
        hojas, clave = evaluacion.preparar(_respuestas(), 1, semilla=2)
        fila = next(f for f in hojas[0] if f["pregunta"] == "b")
        self.assertIn("Persona: a", fila["contexto"])
        self.assertTrue(fila["respuesta"].endswith("-2b"))

    def test_resumen_y_aviso_de_d2(self):
        hojas, clave = evaluacion.preparar(_respuestas(), 2, semilla=3)
        rellenas = {}
        for i, hoja in enumerate(hojas):
            for fila in hoja:
                conf = clave[fila["id"]]["configuracion"]
                for c in evaluacion.CRITERIOS:
                    fila[c] = "4" if conf == "alfa" else "2"
                fila["truncada"] = "x" if conf == "beta" else ""
            self.assertEqual(evaluacion.validar_hoja(hoja), [])
            rellenas[f"e{i}"] = hoja
        r = evaluacion.resumir(rellenas, clave)
        self.assertFalse(r["valido_segun_D2"], "dos evaluadores no bastan")
        self.assertEqual(r["configuraciones"]["alfa"]["criterios"]["utilidad"]["media"], 4)
        self.assertEqual(r["configuraciones"]["beta"]["marcas"]["truncada"], 4)
        self.assertEqual(r["acuerdo_pm1"], 1.0)

    def test_rechaza_hojas_incompletas(self):
        hojas, _ = evaluacion.preparar(_respuestas(), 1, semilla=4)
        self.assertTrue(evaluacion.validar_hoja(hojas[0]), "sin puntuar")
        hojas[0][0].update({c: "7" for c in evaluacion.CRITERIOS})
        self.assertTrue(any("1-5" in p for p in evaluacion.validar_hoja(hojas[0])))

    def test_hoja_ida_y_vuelta_con_excel(self):
        hojas, _ = evaluacion.preparar(_respuestas(), 1, semilla=5)
        ruta = Path(tempfile.mkdtemp()) / "h.csv"
        evaluacion.escribir_hoja(ruta, hojas[0])
        self.assertEqual(len(evaluacion.leer_hoja(ruta)), 4)
        # Excel en español guarda con punto y coma.
        texto = ruta.read_text(encoding="utf-8-sig").replace(",", ";")
        ruta.write_text(texto, encoding="utf-8-sig")
        self.assertIn("id", evaluacion.leer_hoja(ruta)[0])


if __name__ == "__main__":
    unittest.main()
