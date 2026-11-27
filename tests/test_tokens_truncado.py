"""Fase 1, A2 y A3: respuestas truncadas y contabilidad de tokens.

Todo simulado: ni red, ni claves reales, ni el archivo de presupuesto del
usuario (cada prueba usa un directorio temporal).
"""
import csv
import dataclasses
import io
import json
import tempfile
import threading
import unittest
import urllib.error
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from emotibot import rutas
from emotibot.ajustes import Ajustes
from emotibot.identidad import Identidad
from emotibot.ia import gemini as mod_gemini
from emotibot.ia import openai_compat as mod_openai
from emotibot.ia import presupuesto as mod_presupuesto
from emotibot.ia import tokens, truncado
from emotibot.ia.base import (FIN_COMPLETA, FIN_DESCONOCIDO, FIN_FILTRADA,
                              FIN_OTRO, FIN_TRUNCADA, Clase, ErrorProveedor,
                              Peticion, Respuesta, normalizar_motivo_fin)
from emotibot.ia.guion import ProveedorGuion
from emotibot.ia.openai_compat import Endpoint, ProveedorOpenAI
from emotibot.ia.presupuesto import Presupuesto

PETICION = Peticion(texto="hola, ¿qué tal?", instrucciones="Sé breve.")


def _presupuesto(diario=100, minuto=50) -> Presupuesto:
    return Presupuesto(diario, minuto,
                       ruta=Path(tempfile.mkdtemp()) / "presupuesto.json")


# ------------------------------------------------------------------ simulación
class _Http:
    """Respuesta de `urlopen` simulada."""

    def __init__(self, cuerpo: dict):
        self._datos = json.dumps(cuerpo).encode("utf-8")
        self.status = 200

    def read(self):
        return self._datos

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def _cuerpo(texto="Hola. ¿Cómo va tu día?", motivo="stop", uso=True):
    datos = {"choices": [{"message": {"content": texto}}]}
    if motivo is not None:
        datos["choices"][0]["finish_reason"] = motivo
    if uso:
        datos["usage"] = {"prompt_tokens": 40, "completion_tokens": 12,
                          "total_tokens": 52}
    return datos


def _proveedor_openai(presupuesto=None, **extra) -> ProveedorOpenAI:
    endpoint = Endpoint(nombre="conversacion", url="https://ejemplo.invalid/v1",
                        modelo="modelo-prueba", clave="prueba", max_tokens=120,
                        **extra)
    return ProveedorOpenAI(endpoint, presupuesto or _presupuesto(),
                           lambda _nombre: "clave-de-prueba")


def _responder(prov, cuerpo=None, error=None):
    def falso(_solicitud, timeout=None):
        if error is not None:
            raise error
        return _Http(cuerpo)
    with mock.patch.object(mod_openai.urllib.request, "urlopen", falso):
        return prov.responder(PETICION)


def _http_error(codigo):
    return urllib.error.HTTPError("https://ejemplo.invalid", codigo, "x", {},
                                  io.BytesIO(b"{}"))


# ======================================================================= A2
class ContratoRespuestaTest(unittest.TestCase):
    """§13.3: los campos nuevos llevan valor por defecto."""

    def test_se_construye_con_los_cuatro_campos_de_siempre(self):
        r = Respuesta("hola", "x")
        self.assertEqual(r.motivo_fin, FIN_DESCONOCIDO)
        self.assertIsNone(r.tokens_entrada)
        self.assertFalse(r.truncada)
        self.assertFalse(r.recortada)

    def test_los_tres_proveedores_construyen_respuesta(self):
        # 1. Compatible con OpenAI
        r1 = _responder(_proveedor_openai(), _cuerpo())
        self.assertIsInstance(r1, Respuesta)
        # 2. Gemini, con el SDK simulado
        r2 = _responder_gemini(SimpleNamespace(
            text="Hola.", candidates=[SimpleNamespace(finish_reason="STOP")],
            usage_metadata=SimpleNamespace(prompt_token_count=30,
                                           candidates_token_count=5)))
        self.assertIsInstance(r2, Respuesta)
        # 3. Guion local
        r3 = ProveedorGuion(Identidad()).responder(PETICION)
        self.assertIsInstance(r3, Respuesta)
        self.assertEqual(r3.motivo_fin, FIN_COMPLETA)


class MotivoFinTest(unittest.TestCase):
    def test_normaliza_los_nombres_de_cada_proveedor(self):
        casos = [
            ("stop", FIN_COMPLETA), ("length", FIN_TRUNCADA),
            ("content_filter", FIN_FILTRADA), ("tool_calls", FIN_OTRO),
            (None, FIN_DESCONOCIDO), ("", FIN_DESCONOCIDO),
            ("MAX_TOKENS", FIN_TRUNCADA), ("STOP", FIN_COMPLETA),
            ("SAFETY", FIN_FILTRADA), ("FinishReason.MAX_TOKENS", FIN_TRUNCADA),
            (SimpleNamespace(name="MAX_TOKENS"), FIN_TRUNCADA),
        ]
        for crudo, esperado in casos:
            with self.subTest(crudo=crudo):
                self.assertEqual(normalizar_motivo_fin(crudo), esperado)

    def test_openai_lee_finish_reason(self):
        for crudo, esperado in (("stop", FIN_COMPLETA), ("length", FIN_TRUNCADA),
                                ("content_filter", FIN_FILTRADA),
                                (None, FIN_DESCONOCIDO)):
            with self.subTest(finish_reason=crudo):
                r = _responder(_proveedor_openai(), _cuerpo(motivo=crudo))
                self.assertEqual(r.motivo_fin, esperado)

    def test_truncada_vacia_no_es_error_sino_truncada(self):
        """Un modelo de razonamiento que agota el tope pensando."""
        r = _responder(_proveedor_openai(), _cuerpo(texto="", motivo="length"))
        self.assertTrue(r.truncada)
        self.assertEqual(r.texto, "")

    def test_vacia_sin_truncado_sigue_siendo_error(self):
        with self.assertRaises(ErrorProveedor) as ctx:
            _responder(_proveedor_openai(), _cuerpo(texto="", motivo="stop"))
        self.assertIs(ctx.exception.clase, Clase.VACIA)

    def test_gemini_lee_max_tokens(self):
        r = _responder_gemini(SimpleNamespace(
            text="Te cuento que",
            candidates=[SimpleNamespace(finish_reason=SimpleNamespace(
                name="MAX_TOKENS"))],
            usage_metadata=None))
        self.assertTrue(r.truncada)


class RecorteTest(unittest.TestCase):
    def test_recorta_a_la_ultima_frase_completa(self):
        self.assertEqual(
            truncado.recortar_a_frase_completa(
                "Hoy hace sol. ¿Quieres salir? Podríamos ir al par"),
            "Hoy hace sol. ¿Quieres salir?")

    def test_sin_frase_completa_devuelve_vacio(self):
        self.assertEqual(truncado.recortar_a_frase_completa("Te cuento que"), "")

    def test_no_corta_en_decimales_ni_versiones(self):
        self.assertEqual(
            truncado.recortar_a_frase_completa("Mide 3.5 metros y la v1.8 es"),
            "")

    def test_respeta_comillas_de_cierre(self):
        self.assertEqual(
            truncado.recortar_a_frase_completa("Dijo «hola.» Y luego"),
            "Dijo «hola.»")

    def test_aplicar_no_toca_las_completas(self):
        r = Respuesta("Texto sin punto", "x", motivo_fin=FIN_COMPLETA)
        self.assertIs(truncado.aplicar(r), r)

    def test_aplicar_marca_la_recortada(self):
        r = Respuesta("Una frase. Otra a med", "x", motivo_fin=FIN_TRUNCADA)
        tratada = truncado.aplicar(r)
        self.assertEqual(tratada.texto, "Una frase.")
        self.assertTrue(tratada.recortada)

    def test_aplicar_sin_frase_pide_respaldo(self):
        r = Respuesta("Te cuento que", "x", motivo_fin=FIN_TRUNCADA)
        self.assertIsNone(truncado.aplicar(r))

    def test_politica_ninguna_revierte_a_la_v17(self):
        r = Respuesta("Una frase. Otra a med", "x", motivo_fin=FIN_TRUNCADA)
        self.assertIs(truncado.aplicar(r, truncado.NINGUNA), r)

    def test_politica_desconocida_cae_en_la_conservadora(self):
        r = Respuesta("Una frase. Otra a med", "x", motivo_fin=FIN_TRUNCADA)
        self.assertEqual(truncado.aplicar(r, "inventada").texto, "Una frase.")


class OrquestadorTruncadoTest(unittest.TestCase):
    """La política se aplica en un solo punto y nunca vuelve a llamar."""

    def setUp(self):
        directorio = Path(tempfile.mkdtemp())
        parche = mock.patch.object(rutas, "ARCHIVO_PRESUPUESTO",
                                   directorio / "presupuesto.json")
        parche.start()
        self.addCleanup(parche.stop)
        from emotibot.ia.orquestador import Orquestador
        self.orq = Orquestador(Ajustes(), Identidad(), lambda _n: "")

    def _con_proveedor(self, respuesta):
        llamadas = []

        class Falso:
            nombre = "conversacion"
            modelo = "modelo-prueba"
            ultimo_motivo = ""

            def disponible(self):
                return True

            def responder(self, peticion):
                llamadas.append(1)
                return respuesta

        self.orq._por_nombre = {"conversacion": Falso(),
                                "guion": self.orq.guion}
        base = Ajustes()
        self.orq.config = dataclasses.replace(
            base, ia=dataclasses.replace(
                base.ia, orden_proveedores=("conversacion", "guion")))
        return llamadas

    def test_truncada_con_frase_se_recorta(self):
        llamadas = self._con_proveedor(Respuesta(
            "Claro que sí. Mira, lo que pas", "conversacion",
            modelo="modelo-prueba", motivo_fin=FIN_TRUNCADA))
        r = self.orq.responder("cuéntame")
        self.assertEqual(r.texto, "Claro que sí.")
        self.assertTrue(r.recortada)
        self.assertEqual(llamadas, [1], "ni reintento ni segunda llamada")
        self.assertEqual(
            self.orq.presupuesto._estado("modelo-prueba").truncadas, 1)

    def test_truncada_sin_frase_va_al_respaldo_local(self):
        llamadas = self._con_proveedor(Respuesta(
            "Lo que pasa es que", "conversacion", modelo="modelo-prueba",
            motivo_fin=FIN_TRUNCADA))
        r = self.orq.responder("cuéntame")
        self.assertEqual(r.proveedor, "guion")
        self.assertIn("cortó", r.texto)
        self.assertNotIn("Lo que pasa", r.texto)
        self.assertEqual(llamadas, [1])
        self.assertIs(self.orq.ultimo_aviso.clase, Clase.TRUNCADA)

    def test_el_registro_no_contiene_el_texto(self):
        secreto = "Mi secreto personal es que"
        self._con_proveedor(Respuesta(secreto, "conversacion",
                                      modelo="modelo-prueba",
                                      motivo_fin=FIN_TRUNCADA))
        with self.assertLogs("emotibot", level="INFO") as capturado:
            self.orq.responder("cuéntame")
        self.assertFalse(any("secreto" in linea for linea in capturado.output))

    def test_una_completa_pasa_sin_tocar(self):
        self._con_proveedor(Respuesta("Sin punto final", "conversacion",
                                      motivo_fin=FIN_COMPLETA))
        self.assertEqual(self.orq.responder("hola").texto, "Sin punto final")


# ======================================================================= A3
class EstimacionTest(unittest.TestCase):
    def test_sobreestima_las_instrucciones_reales(self):
        """§13.4: el error va hacia arriba, pero sin frenar al robot de más.

        Medido con Qwen el 22-11-2026 (logs/latencia.csv): la primera vuelta
        con las instrucciones de hoy costó 783 tokens de entrada; quitando el
        saludo y la plantilla del chat (~12), unos 771 para las instrucciones.
        Antes se suponían 3,6 caracteres por token y se estimaba con 3,0: un
        42 % por encima de lo real.
        """
        from emotibot import identidad as mod_identidad
        instrucciones = mod_identidad.cargar().instrucciones()
        # 26-11-2026, con las normas de acompañamiento: 1.096 de entrada con
        # «hola»; quitando el saludo y la plantilla (~12), 1.084.
        reales_medidos = 1084
        estimados = tokens.estimar_entrada([instrucciones])
        self.assertGreater(estimados, reales_medidos * 1.05, "siempre por encima")
        self.assertLess(estimados, reales_medidos * 1.30, "pero no frena de más")

    def test_crece_con_cada_mensaje(self):
        self.assertGreater(tokens.estimar_entrada(["", ""]),
                           tokens.estimar_entrada([""]))


class ReservaTest(unittest.TestCase):
    def test_con_usage_reconcilia_al_consumo_real(self):
        p = _presupuesto()
        prov = _proveedor_openai(p)
        r = _responder(prov, _cuerpo(uso=True))
        estado = p._estado("modelo-prueba")
        self.assertEqual((r.tokens_entrada, r.tokens_salida), (40, 12))
        self.assertEqual(estado.tokens, 52)
        self.assertEqual(estado.tokens_reservados, 0)
        self.assertEqual((estado.intentos, estado.consultas), (1, 1))
        self.assertEqual(estado.sin_uso, 0)

    def test_sin_usage_cuenta_la_reserva_entera(self):
        p = _presupuesto()
        _responder(_proveedor_openai(p), _cuerpo(uso=False))
        estado = p._estado("modelo-prueba")
        esperado = tokens.estimar_entrada(
            ["Sé breve.", "hola, ¿qué tal?"]) + 120
        self.assertEqual(estado.tokens, esperado)
        self.assertEqual(estado.sin_uso, 1)
        self.assertEqual(estado.tokens_reservados, 0)

    def test_limite_diario_de_tokens_frena_antes_de_llamar(self):
        p = _presupuesto()
        prov = _proveedor_openai(p, max_tokens_dia=300)
        llamadas = []

        def falso(_s, timeout=None):
            llamadas.append(1)
            return _Http(_cuerpo())
        with mock.patch.object(mod_openai.urllib.request, "urlopen", falso):
            prov.responder(PETICION)                 # cabe (reserva < 300)
            for _ in range(10):
                try:
                    prov.responder(PETICION)
                except ErrorProveedor as exc:
                    self.assertIs(exc.clase, Clase.SIN_PRESUPUESTO)
                    break
            else:
                self.fail("debió frenar por tokens diarios")
        estado = p._estado("modelo-prueba")
        self.assertLessEqual(estado.tokens, 300)
        self.assertEqual(len(llamadas), estado.intentos)

    def test_limite_por_minuto_de_tokens_y_se_libera_al_minuto(self):
        p = _presupuesto()
        p.fijar_limites("m", 100, 50, tokens_dia=0, tokens_minuto=1000)
        reloj = [1000.0]
        with mock.patch.object(mod_presupuesto.time, "monotonic",
                               lambda: reloj[0]):
            r1, _ = p.reservar("m", 600)
            self.assertIsNotNone(r1)
            r2, motivo = p.reservar("m", 600)
            self.assertIsNone(r2)
            self.assertIn("minuto", motivo)
            # El consumo real fue menor: al reconciliar, cabe otra.
            p.confirmar(r1, 200, 50)
            r3, _ = p.reservar("m", 600)
            self.assertIsNotNone(r3)
            p.confirmar(r3, 300, 300)
            self.assertIsNone(p.reservar("m", 600)[0])
            reloj[0] += 61.0
            self.assertIsNotNone(p.reservar("m", 600)[0])

    def test_solicitud_fallida_cuenta_el_intento(self):
        """Los fallidos también cuentan en varios servicios."""
        p = _presupuesto()
        prov = _proveedor_openai(p)
        with self.assertRaises(ErrorProveedor):
            _responder(prov, error=_http_error(500))
        estado = p._estado("modelo-prueba")
        self.assertEqual((estado.intentos, estado.consultas), (1, 0))
        self.assertGreater(estado.tokens, 0, "un 500 pudo procesar la entrada")
        self.assertEqual(estado.tokens_reservados, 0)

    def test_un_429_cuenta_intento_bloquea_y_no_reintenta(self):
        p = _presupuesto()
        prov = _proveedor_openai(p)
        llamadas = []

        def falso(_s, timeout=None):
            llamadas.append(1)
            raise _http_error(429)
        with mock.patch.object(mod_openai.urllib.request, "urlopen", falso):
            with self.assertRaises(ErrorProveedor) as ctx:
                prov.responder(PETICION)
        self.assertIs(ctx.exception.clase, Clase.CUOTA)
        self.assertEqual(len(llamadas), 1)
        estado = p._estado("modelo-prueba")
        self.assertEqual(estado.intentos, 1)
        self.assertEqual(estado.tokens, 0)
        self.assertFalse(p.puede_consultar("modelo-prueba")[0])

    def test_tiempo_agotado_cuenta_la_reserva_entera(self):
        p = _presupuesto()
        prov = _proveedor_openai(p)
        with self.assertRaises(ErrorProveedor):
            _responder(prov, error=TimeoutError("timed out"))
        estado = p._estado("modelo-prueba")
        self.assertGreaterEqual(estado.tokens, 120)

    def test_el_limite_diario_de_solicitudes_cuenta_los_intentos(self):
        p = _presupuesto()
        p.fijar_limites("m", diario=3, por_minuto=50)
        for _ in range(3):
            reserva, _ = p.reservar("m", 10)
            p.anular(reserva, 0)                       # tres fallos
        self.assertFalse(p.puede_consultar("m")[0])

    def test_cambio_de_dia_reinicia_y_no_pierde_la_reserva_en_vuelo(self):
        p = _presupuesto()
        p.fijar_limites("m", 100, 50, tokens_dia=1000)
        reserva, _ = p.reservar("m", 500)
        manana = date(2099, 1, 2)
        with mock.patch.object(mod_presupuesto, "date",
                               SimpleNamespace(today=lambda: manana)):
            p.confirmar(reserva, 300, 100)
            estado = p._estado("m")
            self.assertEqual(p.dia, "2099-01-02")
            self.assertEqual(estado.tokens, 400, "se apunta al día nuevo")
            self.assertEqual(estado.tokens_reservados, 0)

    def test_confirmar_dos_veces_no_cuenta_doble(self):
        p = _presupuesto()
        reserva, _ = p.reservar("m", 100)
        p.confirmar(reserva, 10, 10)
        p.confirmar(reserva, 10, 10)
        p.anular(reserva, 999)
        self.assertEqual(p._estado("m").tokens, 20)

    def test_concurrencia_no_sobrepasa_el_tope(self):
        p = _presupuesto(diario=1000, minuto=1000)
        p.fijar_limites("m", 1000, 1000, tokens_dia=10_000)
        concedidas = []
        barrera = threading.Barrier(16)

        def pedir():
            barrera.wait()
            for _ in range(20):
                reserva, _ = p.reservar("m", 300)
                if reserva is not None:
                    concedidas.append(reserva)
        hilos = [threading.Thread(target=pedir) for _ in range(16)]
        for hilo in hilos:
            hilo.start()
        for hilo in hilos:
            hilo.join()
        self.assertEqual(len(concedidas), 10_000 // 300)
        estado = p._estado("m")
        self.assertLessEqual(estado.tokens_reservados, 10_000)

    def test_lee_el_archivo_de_la_v17(self):
        ruta = Path(tempfile.mkdtemp()) / "presupuesto.json"
        ruta.write_text(json.dumps({
            "dia": date.today().isoformat(),
            "modelos": {"m": {"consultas": 7, "rechazos_cuota": 1,
                              "bloqueado_todo_el_dia": False}},
        }), encoding="utf-8")
        p = Presupuesto(100, 10, ruta=ruta)
        estado = p._estado("m")
        self.assertEqual((estado.consultas, estado.intentos, estado.tokens),
                         (7, 0, 0))
        reserva, _ = p.reservar("m", 50)
        p.confirmar(reserva, 20, 5)
        guardado = json.loads(ruta.read_text(encoding="utf-8"))["modelos"]["m"]
        self.assertEqual(guardado["consultas"], 8)
        self.assertEqual(guardado["tokens"], 25)
        self.assertNotIn("texto", json.dumps(guardado))

    def test_disponible_se_niega_si_no_cabe_ni_la_salida(self):
        p = _presupuesto()
        prov = _proveedor_openai(p, max_tokens_dia=100)
        self.assertFalse(prov.disponible())
        self.assertIn("tokens", prov.ultimo_motivo)


class MetricasTest(unittest.TestCase):
    def test_migra_el_csv_de_la_v17_sin_perder_filas(self):
        from emotibot import metricas
        ruta = Path(tempfile.mkdtemp()) / "latencia.csv"
        viejas = list(metricas.COLUMNAS[:14])
        with ruta.open("w", newline="", encoding="utf-8") as f:
            escritor = csv.DictWriter(f, fieldnames=viejas)
            escritor.writeheader()
            escritor.writerow({c: "" for c in viejas} | {"t_ia": "0.71",
                                                        "resultado": "ok"})
        bitacora = metricas.Bitacora(ruta)
        bitacora.anotar(metricas.Medicion(motivo_fin=FIN_TRUNCADA,
                                          recortada=True, tokens_entrada=40,
                                          tokens_salida=12))
        filas = metricas.leer_csv(ruta)
        self.assertEqual(len(filas), 2)
        self.assertEqual(filas[0]["t_ia"], "0.71")
        self.assertEqual(filas[0]["motivo_fin"], "")
        self.assertEqual(filas[1]["motivo_fin"], FIN_TRUNCADA)
        self.assertEqual(filas[1]["tokens_salida"], "12")
        self.assertIn("Truncadas: 1", metricas.resumir(filas))

    def test_la_fila_no_lleva_texto(self):
        from emotibot import metricas
        fila = metricas.Medicion().como_fila()
        self.assertFalse({"texto", "transcripcion", "respuesta"} & set(fila))


# ================================================================== Gemini
def _responder_gemini(resultado):
    class Modelos:
        def generate_content(self, model, contents, config):
            return resultado

    cliente = SimpleNamespace(models=Modelos())
    tipos = SimpleNamespace(GenerateContentConfig=lambda **kw: kw,
                            ThinkingConfig=None)
    prov = mod_gemini.ProveedorGemini(Ajustes().ia, _presupuesto(),
                                      lambda _n: "clave-de-prueba")
    with mock.patch.object(mod_gemini, "_cargar_sdk", lambda: (None, tipos)), \
            mock.patch.object(mod_gemini, "_cliente", lambda *_a: cliente):
        respuesta = prov.responder(PETICION)
    respuesta._presupuesto = prov.presupuesto
    return respuesta


class GeminiTokensTest(unittest.TestCase):
    def test_lee_usage_metadata_y_reconcilia(self):
        r = _responder_gemini(SimpleNamespace(
            text="Hola.", candidates=[SimpleNamespace(finish_reason="STOP")],
            usage_metadata=SimpleNamespace(prompt_token_count=30,
                                           candidates_token_count=5,
                                           thoughts_token_count=None)))
        self.assertEqual((r.tokens_entrada, r.tokens_salida), (30, 5))
        estado = r._presupuesto._estado(Ajustes().ia.modelo_remoto)
        self.assertEqual(estado.tokens, 35)
        self.assertEqual(estado.intentos, 1)


if __name__ == "__main__":
    unittest.main()
