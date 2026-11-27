"""D10, tanda 3: el primer arranque y el asistente de perfil.

- El modelo del asistente (sin Tk): estándar en UNA tecla, personalizable,
  atrás, salir a medias, la muestra de voz y el rostro visible.
- Guardar: solo los cinco ejes, validado antes de escribir, entero o nada.
- §14.5 con lo que escribe el asistente: la batería del perfil malicioso,
  otra vez, sobre el archivo que ha escrito el asistente.
- Perfil corrupto o incompleto: arranca con el de por defecto y avisa.
- La aplicación de verdad (Tk real; audio, voz y reconocimiento simulados):
  primer arranque, estándar, personalizable, salir a medias, cambiar con la
  aplicación en marcha y perfil corrupto.
"""
import ast
import dataclasses
import json
import queue
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from emotibot import ajustes as mod_ajustes
from emotibot import asistente as mod
from emotibot import perfil_usuario as pu
from emotibot import rutas
from emotibot.asistente import Accion
from emotibot.rostro import perfil as mod_perfil
from tests.test_perfil_usuario import MALICIOSO, PerfilMaliciosoTest, _identidad

A = Accion


def _recorrer(asistente, *acciones):
    efectos = [asistente.actuar(a) for a in acciones]
    return efectos[-1] if efectos else None


class _PerfilTemporal:
    """ARCHIVO_USUARIO en una carpeta temporal vacía (primer arranque)."""

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ruta = Path(self.tmp.name) / "perfil.json"
        self.parche = mock.patch.object(pu, "ARCHIVO_USUARIO", self.ruta)
        self.parche.start()
        return self

    def __exit__(self, *exc):
        self.parche.stop()
        self.tmp.cleanup()

    def leer(self):
        return json.loads(self.ruta.read_text(encoding="utf-8"))


# ===================================================================== modelo
class ModeloTest(unittest.TestCase):
    def test_estandar_es_una_tecla(self):
        a = mod.Asistente(primer_arranque=True)
        efecto = a.actuar(mod.accion_de_tecla("Return"))
        self.assertTrue(efecto.terminado)
        self.assertEqual(a.resultado, pu.POR_DEFECTO)

    def test_estandar_desde_un_perfil_propio_vuelve_al_defecto(self):
        propio = pu.PerfilUsuario(rostro="tele", voz="claude", personalidad="amigable",
                                  estilo="formal")
        a = mod.Asistente(propio)
        a.actuar(A.ACEPTAR)
        self.assertEqual(a.resultado, pu.POR_DEFECTO)

    def test_personalizable_elige_los_cuatro_y_conserva_el_modelo(self):
        base = pu.PerfilUsuario(modelo="candidato_gpt_oss_20b")
        a = mod.Asistente(base)
        a.actuar(A.PERSONALIZAR)
        self.assertEqual(a.paso, "rostro")
        for eje, valor in (("rostro", "tele"), ("voz", "claude"),
                           ("personalidad", "tranquila"), ("estilo", "directo")):
            while a.actual() != valor:
                a.actuar(A.SIGUIENTE)
            efecto = a.actuar(A.ACEPTAR)
        self.assertTrue(efecto.terminado)
        self.assertEqual(a.resultado, pu.PerfilUsuario(
            rostro="tele", voz="claude", personalidad="tranquila", estilo="directo",
            modelo="candidato_gpt_oss_20b"))

    def test_las_opciones_son_las_publicadas_y_dan_la_vuelta(self):
        a = mod.Asistente()
        for eje in mod.PASOS:
            self.assertEqual(a.opciones[eje], pu.opciones(eje))
        a.actuar(A.PERSONALIZAR)
        primero = a.actual()
        for _ in range(len(a.opciones["rostro"])):
            a.actuar(A.SIGUIENTE)
        self.assertEqual(a.actual(), primero)
        self.assertEqual(primero, pu.POR_DEFECTO.rostro, "empieza en el de la base")
        lista = a.opciones["rostro"]
        a.actuar(A.ANTERIOR)
        self.assertEqual(a.actual(), lista[(lista.index(primero) - 1) % len(lista)])

    def test_atras_en_cualquier_paso_y_lo_elegido_se_conserva(self):
        a = mod.Asistente()
        _recorrer(a, A.PERSONALIZAR, A.SIGUIENTE, A.ACEPTAR)
        elegido = a.elegido["rostro"]
        self.assertEqual(a.paso, "voz")
        a.actuar(A.ATRAS)
        self.assertEqual((a.paso, a.actual()), ("rostro", elegido))
        a.actuar(A.ATRAS)
        self.assertEqual(a.paso, mod.INICIO)
        a.actuar(A.ATRAS)                       # en el inicio no hace nada
        self.assertEqual(a.paso, mod.INICIO)
        self.assertFalse(a.terminado)

    def test_salir_a_medias_guarda_lo_elegido_y_el_resto_por_defecto(self):
        a = mod.Asistente(primer_arranque=True)
        _recorrer(a, A.PERSONALIZAR)
        while a.actual() != "capsula":
            a.actuar(A.SIGUIENTE)
        a.actuar(A.ACEPTAR)                      # rostro: elegido
        a.actuar(A.SIGUIENTE)                    # voz: solo mirada, no elegida
        efecto = a.actuar(A.SALIR)
        self.assertTrue(efecto.terminado)
        self.assertEqual(a.resultado, dataclasses.replace(pu.POR_DEFECTO, rostro="capsula"))

    def test_salir_en_el_inicio_no_cambia_nada(self):
        propio = pu.PerfilUsuario(rostro="tele")
        a = mod.Asistente(propio)
        a.actuar(A.SALIR)
        self.assertEqual(a.resultado, propio)
        primera = mod.Asistente(primer_arranque=True)
        primera.actuar(A.SALIR)
        self.assertEqual(primera.resultado, pu.POR_DEFECTO)

    def test_la_voz_se_oye_al_llegar_y_al_cambiar(self):
        a = mod.Asistente()
        self.assertEqual(_recorrer(a, A.PERSONALIZAR).oir, "")
        efecto = a.actuar(A.ACEPTAR)
        self.assertEqual((a.paso, efecto.oir), ("voz", a.actual()))
        efecto = a.actuar(A.SIGUIENTE)
        self.assertEqual(efecto.oir, a.actual())
        self.assertEqual(a.actuar(A.ACEPTAR).oir, "", "fuera del paso de voz, silencio")

    def test_el_rostro_se_ve_mientras_se_elige_y_vuelve_si_no_se_elige(self):
        a = mod.Asistente()
        a.actuar(A.PERSONALIZAR)
        efecto = a.actuar(A.SIGUIENTE)
        self.assertEqual(efecto.rostro, a.actual())
        self.assertNotEqual(efecto.rostro, pu.POR_DEFECTO.rostro)
        efecto = a.actuar(A.ATRAS)               # sin elegir
        self.assertEqual(efecto.rostro, pu.POR_DEFECTO.rostro)

    def test_tras_terminar_no_hace_nada_mas(self):
        a = mod.Asistente()
        a.actuar(A.ACEPTAR)
        for accion in Accion:
            self.assertTrue(a.actuar(accion).terminado)
        self.assertEqual(a.resultado, pu.POR_DEFECTO)

    def test_la_navegacion_no_depende_del_teclado(self):
        """El modelo no importa Tk ni sabe de teclas: se le añade táctil o voz
        traduciendo a `Accion`, como hace TECLAS."""
        fuente = (rutas.RAIZ / "emotibot" / "asistente.py").read_text(encoding="utf-8")
        importados = {n.names[0].name if isinstance(n, ast.Import) else n.module
                      for n in ast.walk(ast.parse(fuente))
                      if isinstance(n, (ast.Import, ast.ImportFrom))}
        self.assertFalse({m for m in importados if m and "tk" in m.lower()})
        self.assertEqual(set(mod.TECLAS.values()), set(Accion))
        self.assertIs(mod.accion_de_tecla("Escape"), A.SALIR)
        self.assertIsNone(mod.accion_de_tecla("space"))


# ===================================================================== guardar
class GuardarTest(unittest.TestCase):
    def test_escribe_solo_los_cinco_ejes_y_se_vuelve_a_cargar(self):
        with _PerfilTemporal() as d:
            self.assertTrue(pu.primer_arranque())
            perfil = pu.PerfilUsuario(rostro="capsula", voz="claude")
            pu.guardar(perfil)
            self.assertEqual(set(d.leer()), set(pu.EJES))
            self.assertEqual(pu.cargar(), perfil)
            self.assertFalse(pu.primer_arranque())
            self.assertEqual(list(d.ruta.parent.iterdir()), [d.ruta], "sin temporales")

    def test_no_escribe_lo_que_no_se_podria_cargar(self):
        with _PerfilTemporal() as d:
            pu.guardar(pu.POR_DEFECTO)
            antes = d.ruta.read_text(encoding="utf-8")
            for malo in (pu.PerfilUsuario(rostro="no_existe"),
                         pu.PerfilUsuario(voz="../../etc"),
                         {"rostro": "tele", "seguridad": "off"}):
                with self.subTest(malo=malo):
                    with self.assertRaises(pu.ErrorPerfilUsuario):
                        pu.guardar(malo)
                    self.assertEqual(d.ruta.read_text(encoding="utf-8"), antes)


class AsistenteMaliciosoTest(PerfilMaliciosoTest):
    """§14.5 sobre lo que ESCRIBE el asistente: se eligen la personalidad y
    el estilo maliciosos con el asistente, se guardan, se vuelven a leer del
    disco y toda la batería del perfil malicioso corre sobre ESE perfil."""

    def setUp(self):
        super().setUp()                    # opciones maliciosas en su sitio
        self.temporal = _PerfilTemporal().__enter__()
        self.addCleanup(self.temporal.__exit__, None, None, None)
        a = mod.Asistente()
        a.actuar(A.PERSONALIZAR)
        for eje, valor in (("rostro", "hybrid_balanced"), ("voz", "daniela"),
                           ("personalidad", "malvada"), ("estilo", "malvado")):
            while a.actual() != valor:
                a.actuar(A.SIGUIENTE)
            a.actuar(A.ACEPTAR)
        pu.guardar(a.resultado)
        self.assertEqual(set(self.temporal.leer()), set(pu.EJES))
        escrito = pu.cargar()
        self.assertEqual(escrito, MALICIOSO)
        self.ajustes_mal = pu.aplicar(self.base_a, escrito)
        self.ident_mal = _identidad(escrito)


# ============================================================ perfil corrupto
class PerfilCorruptoTest(unittest.TestCase):
    CASOS = {
        "no es JSON": "{rostro: tele",
        "incompleto": json.dumps({"rostro": "tele"}),
        "clave ajena": json.dumps({**dataclasses.asdict(pu.POR_DEFECTO),
                                   "seguridad": "desactivada"}),
        "opción que no existe": json.dumps({**dataclasses.asdict(pu.POR_DEFECTO),
                                            "voz": "no_existe"}),
        "no es un objeto": "[1, 2, 3]",
    }

    def test_arranca_con_el_defecto_y_avisa(self):
        defecto = mod_ajustes.cargar()
        for nombre, contenido in self.CASOS.items():
            with self.subTest(caso=nombre), _PerfilTemporal() as d:
                d.ruta.write_text(contenido, encoding="utf-8")
                perfil, aviso = pu.cargar_con_aviso()
                self.assertEqual(perfil, pu.POR_DEFECTO)
                self.assertTrue(aviso)
                self.assertFalse(pu.primer_arranque(), "no se reabre el asistente solo")
                self.assertEqual(mod_ajustes.cargar(), defecto)


# ================================================================ aplicación
class _Voz:
    nombre = "piper"
    frecuencia = 22050

    def __init__(self, config):
        self.modelo = config.voz.modelo_piper
        self.velocidad = config.voz.velocidad
        self.cerrada = False

    def sintetizar(self, texto):
        return iter((b"\x00\x00",))

    def cerrar(self):
        self.cerrada = True


class _Altavoz:
    def __init__(self, *_):
        self.dicho = []

    def hablar(self, fuente, frecuencia, al_primer_sonido=None, al_terminar=None):
        self.dicho.append(b"".join(fuente))
        return len(self.dicho)

    def detener(self):
        pass

    def nivel(self):
        return 0.0

    def hablando(self):
        return False

    def disponible(self):
        return True

    def cerrar(self):
        pass


class _Sordo:
    nombre = "simulado"

    def __init__(self, *_):
        pass

    def disponible(self):
        return False

    def motor(self):
        return "simulado"

    def cerrar(self):
        pass


class _Tecla:
    def __init__(self, keysym, char=""):
        self.keysym, self.char = keysym, char


class _AppSimulada:
    """La aplicación real (Tk) con el audio simulado y sin red."""

    def setUp(self):
        try:
            from emotibot import app as mod_app
        except ImportError as error:
            self.skipTest(f"no se puede importar la aplicación: {error}")
        self.mod_app = mod_app
        self.perfil = _PerfilTemporal().__enter__()
        self.addCleanup(self.perfil.__exit__, None, None, None)
        self.voces: list[_Voz] = []

        def crear_voz(config):
            voz = _Voz(config)
            self.voces.append(voz)
            return voz

        def sin_red(*_a, **_k):
            raise AssertionError("una prueba ordinaria no sale a la red")

        class _WhisperDespertar:          # el Whisper del despertar, simulado
            nombre = "whisper-local"

            def transcribir(self, pcm, frecuencia):
                from emotibot.stt.base import Transcripcion
                return Transcripcion("", self.nombre)

            def cerrar(self):
                pass

        for parche in (mock.patch("urllib.request.urlopen", sin_red),
                       mock.patch.object(mod_app.Aplicacion, "_transcriptor_activacion",
                                         lambda self: _WhisperDespertar()),
                       mock.patch.object(mod_app.Orquestador, "estado_corto",
                                         lambda self: "simulado"),
                       mock.patch.object(mod_app.mod_voz, "crear", crear_voz),
                       mock.patch.object(mod_app, "Altavoz", _Altavoz),
                       mock.patch.object(mod_app, "Microfono", _Sordo),
                       mock.patch.object(mod_app.mod_stt, "crear", lambda *a: _Sordo())):
            parche.start()
            self.addCleanup(parche.stop)

    def _app(self, carcasa=None):
        import tkinter as tk
        try:
            app = self.mod_app.Aplicacion()
        except tk.TclError as error:
            self.skipTest(f"sin entorno gráfico: {error}")
        app.raiz.withdraw()
        if carcasa is not None:
            app.cara.reconfigurar(carcasa=carcasa)
        self.addCleanup(lambda: (app.salir(), app._apagar()))
        app.cara.dibujar()
        return app

    def _teclas(self, app, *teclas):
        for tecla in teclas:
            app._tecla(_Tecla(tecla, tecla if len(tecla) == 1 else ""))
            app._pintar_asistente() if app.asistente else None

    def _esperar_eventos(self, app, segundos=5.0):
        """Atiende los eventos de los hilos (carga de voces) hasta que callen."""
        fin = time.monotonic() + segundos
        quieto = 0
        while time.monotonic() < fin and quieto < 5:
            try:
                tipo, valor = app.eventos.get(timeout=0.05)
            except queue.Empty:
                quieto += 1
                continue
            quieto = 0
            app._atender(tipo, valor)

    def _elegir(self, app, valor):
        while app.asistente.actual() != valor:
            self._teclas(app, "Right")
        self._teclas(app, "Return")


class AplicacionTest(_AppSimulada, unittest.TestCase):
    def test_primer_arranque_y_estandar_con_una_tecla(self):
        app = self._app()
        self.assertIsNotNone(app.asistente, "sin perfil, el asistente va antes de nada")
        self.assertTrue(app.asistente.primer_arranque)
        # Por debajo del asistente no hay aplicación: ni turnos, ni
        # actividades, ni la barra de ayuda.
        # (Los diálogos de K y D, simulados: uno de verdad bloquearía la prueba.)
        with mock.patch.object(app, "_pedir_turno") as turno, \
                mock.patch.object(app, "_lanzar_actividad") as actividad, \
                mock.patch.object(app, "_configurar_clave") as clave, \
                mock.patch.object(app, "_mostrar_diagnostico") as diagnostico:
            self._teclas(app, "space", "f", "2", "4", "a", "k", "d")
        for llamada in (turno, actividad, clave, diagnostico):
            llamada.assert_not_called()
        self.assertFalse(app.panel_directorio.visible)
        self.assertIsNotNone(app.asistente)
        self._teclas(app, "Return")
        self.assertIsNone(app.asistente)
        self.assertEqual(self.perfil.leer(), dataclasses.asdict(pu.POR_DEFECTO))
        self.assertEqual(app.perfil, pu.POR_DEFECTO)

    def test_personalizable_se_aplica_sin_reiniciar(self):
        app = self._app()
        voz_inicial = app.voz
        self._teclas(app, "p")
        self._elegir(app, "tele")
        self.assertEqual(app.cara.perfil.nombre, "tele", "el rostro se ve al elegirlo")
        self._esperar_eventos(app)
        self.assertTrue(app.altavoz.dicho, "la voz dice su frase al llegar")
        while app.asistente.actual() != "claude":
            self._teclas(app, "Right")
        self._esperar_eventos(app)
        muestra = app._muestras["claude"]
        self.assertIn("claude", muestra.modelo)
        self._teclas(app, "Return")
        self._elegir(app, "amigable")
        self._elegir(app, "formal")
        self._esperar_eventos(app)
        self.assertIsNone(app.asistente)
        esperado = pu.PerfilUsuario(rostro="tele", voz="claude", personalidad="amigable",
                                    estilo="formal")
        self.assertEqual(self.perfil.leer(), dataclasses.asdict(esperado))
        # Rostro: el de la tele y su paleta, en la misma ventana.
        self.assertEqual(app.cara.perfil.nombre, "tele")
        self.assertEqual(app.paleta, mod_perfil.cargar("tele").colores)
        # Voz: la de claude, con su velocidad; la anterior, cerrada.
        self.assertIs(app.voz, muestra, "la voz ya cargada para la muestra, sin recargar")
        self.assertEqual(app.config.voz.velocidad, 0.71)
        self.assertTrue(voz_inicial.cerrada)
        self.assertTrue(all(v.cerrada for v in self.voces if v is not muestra),
                        "las demás muestras se cierran")
        # Personalidad y estilo: en la identidad que usan gestor y orquestador.
        esperada = _identidad(esperado)
        for identidad in (app.identidad, app.gestor.identidad, app.orquestador.identidad,
                          app.orquestador.guion.identidad):
            self.assertEqual(identidad.instrucciones(), esperada.instrucciones())
        self.assertEqual(app.orquestador.identidad.tono, pu.leer_lineas("personalidad",
                                                                        "amigable"))
        # Lo mismo que leería un arranque nuevo.
        self.assertEqual(mod_ajustes.cargar().voz, app.config.voz)
        self.assertEqual(mod_ajustes.cargar().rostro, app.config.rostro)

    def test_salir_a_medias(self):
        app = self._app()
        self._teclas(app, "p")
        self._elegir(app, "capsula")
        self._teclas(app, "Right", "Escape")       # mira otra voz y sale
        self._esperar_eventos(app)
        self.assertIsNone(app.asistente)
        self.assertEqual(self.perfil.leer(),
                         dataclasses.asdict(dataclasses.replace(pu.POR_DEFECTO,
                                                                rostro="capsula")))
        self.assertEqual(app.cara.perfil.nombre, "capsula")
        self.assertEqual(app.config.voz, mod_ajustes.cargar().voz)

    def test_la_voz_elegida_sin_muestra_se_carga_aparte(self):
        """Si se elige antes de que la muestra termine de cargar, la voz
        nueva se carga en su hilo y entra al llegar."""
        app = self._app()
        self._teclas(app, "p", "Return")          # rostro tal cual → paso de voz
        app._muestras.clear()
        app.asistente.elegido.clear()
        while app.asistente.actual() != "claude":
            app.asistente.actuar(A.SIGUIENTE)
        app._muestras.clear()
        self._teclas(app, "Return", "Escape")     # elige claude y sale
        self._esperar_eventos(app)
        self.assertIn("claude", app.voz.modelo)
        self.assertEqual(self.perfil.leer()["voz"], "claude")
        self.assertIn("Voz nueva cargada", app.detalle)

    def test_cambiar_con_la_aplicacion_en_marcha(self):
        pu.guardar(pu.PerfilUsuario(rostro="capsula"))
        app = self._app(carcasa=False)
        self.assertIsNone(app.asistente, "con perfil no se abre solo")
        self.assertEqual(app.cara.perfil.nombre, "capsula")
        self._teclas(app, "p")
        self.assertIsNotNone(app.asistente)
        self.assertFalse(app.asistente.primer_arranque)
        # Se elige en el modo en que se usa: sin carcasa, con las franjas de
        # los textos libres.
        self.assertFalse(app.cara.carcasa)
        self.assertEqual(app.cara.reserva_vertical, self.mod_app.RESERVA_ASISTENTE)
        self._teclas(app, "p")
        for rostro in pu.opciones("rostro"):
            while app.asistente.actual() != rostro:
                self._teclas(app, "Right")
            # «feliz» es la cara con la que suena la muestra de voz: estrellas
            # y cejas altas, lo más extendido que se ve en el asistente.
            app.cara.fijar_estado("feliz")
            app.cara.asentar()
            app.cara.dibujar()
            alto = app.cara._geo.alto
            arriba, abajo = (f * alto for f in self.mod_app.RESERVA_ASISTENTE)
            area = app.cara.area_de_rostro()
            self.assertGreaterEqual(area[1], arriba - 1)
            self.assertLessEqual(area[3], alto - abajo + 1)
            for item in [app.cara._items[k] for k in ("ojo_izq", "boca", "ceja_izq",
                                                      "arco_izq")] + app.cara._destellos_items:
                if app.lienzo.itemcget(item, "state") == "hidden":
                    continue
                ys = app.lienzo.coords(item)[1::2]
                with self.subTest(rostro=rostro, item=item):
                    self.assertGreaterEqual(min(ys), arriba - 1)
                    self.assertLessEqual(max(ys), alto - abajo + 1)
            self.assertEqual(app.lienzo.find_withtag("mueble"), (), "sin mueble")
        self._elegir(app, "tele")
        self._teclas(app, "BackSpace", "BackSpace", "Escape")
        self._esperar_eventos(app)
        self.assertIsNone(app.asistente)
        self.assertFalse(app.cara.carcasa)
        self.assertIsNone(app.cara.reserva_vertical, "fuera del asistente, ventana entera")
        self.assertEqual(self.perfil.leer()["rostro"], "tele")
        self.assertEqual(app.cara.perfil.nombre, "tele")
        app.cara.dibujar()                       # se recrea sin fallar

    def test_no_se_abre_en_mitad_de_un_turno(self):
        pu.guardar(pu.POR_DEFECTO)
        app = self._app()
        app.ocupado = True
        self._teclas(app, "p")
        self.assertIsNone(app.asistente)

    def test_perfil_corrupto_arranca_y_avisa(self):
        self.perfil.ruta.write_text("{esto no es json", encoding="utf-8")
        app = self._app()
        self.assertIsNone(app.asistente)
        self.assertEqual(app.perfil, pu.POR_DEFECTO)
        self.assertEqual(app.cara.perfil.nombre, pu.POR_DEFECTO.rostro)
        self.assertIn("no es válido", app.detalle)
        self.assertEqual(app.cara.estado, "error", "sin carcasa avisa la cara")


if __name__ == "__main__":
    unittest.main()
