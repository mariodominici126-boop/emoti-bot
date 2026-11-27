"""Pestaña de configuración.

- Catálogo cerrado: solo se escriben los campos de PERMITIDOS, solo con sus
  opciones; lo protegido no está en el catálogo (arquitectura, no filtro).
- Nada sube un tope; la batería del perfil malicioso corre sobre lo que
  escribe esta pestaña.
- Nunca inaccesible: si se oculta el botón ☰, queda la voz; si no queda la
  voz, el botón se ve.
- Se aplica en caliente; se ve en 800×480 sin salirse.
Sin micrófono ni red.
"""
import dataclasses
import json
import time
import unittest
from collections import deque
from unittest import mock

from emotibot import ajustes as mod_ajustes
from emotibot import configuracion as conf
from emotibot import perfil_usuario as pu
from emotibot.audio import prueba, senal
from emotibot.dialogo import Tipo
from emotibot.dialogo.intencion import Intencion, detectar
from emotibot.ia.orquestador import FACTOR_BREVE
from tests.test_activacion import _Mic, _Whisper
from tests.test_asistente import _AppSimulada, _PerfilTemporal, _Tecla
from tests.test_carcasa import _ConfigTemporal
from tests.test_perfil_usuario import MALICIOSO, PerfilMaliciosoTest, _identidad

CATALOGO = conf.secciones((("1", "Mic USB"),), ("conversacion", "candidato_gpt_oss_20b"))
AJUSTES = [f for _, filas in CATALOGO for f in filas if isinstance(f, conf.Ajuste)]
# Lo que NUNCA es configurable aquí: si aparece en el catálogo, falla.
PROTEGIDOS = {
    ("ia", c) for c in ("max_tokens_respuesta", "presupuesto_diario", "presupuesto_por_minuto",
                        "plazo_turno_ms", "timeout_remoto_ms", "timeout_gemini_ms",
                        "timeout_local_ms", "orden_proveedores", "politica_truncado",
                        "modelo_remoto", "pensamiento", "temperatura")
} | {("voz", "max_caracteres"), ("audio", "max_audio_s"), ("audio", "piso_umbral_rms"),
     ("dialogo", "guardar_transcripciones"),
     # El país decide qué números de ayuda se ofrecen: solo se muestra.
     ("region", "pais")}


def _todas_las_opciones():
    """Cada ajuste del catálogo en su valor más «extremo» (el último)."""
    valores = {"activacion": True, "boton_menu": True}
    for ajuste in AJUSTES:
        if ajuste.clave == "modelo":
            continue
        valor = ajuste.opciones[-1][0]
        valores.update(conf.guardar(ajuste, valor, valores))


class CatalogoTest(unittest.TestCase):
    def test_solo_escribe_lo_permitido(self):
        campos = {(a.seccion, a.campo) for a in AJUSTES if a.seccion}
        self.assertEqual(campos, set(conf.PERMITIDOS))
        self.assertFalse(campos & PROTEGIDOS)
        self.assertFalse({s for s, _ in campos} - {"dialogo", "rostro", "audio", "voz", "ia"})
        pais = next(f for _, filas in CATALOGO for f in filas if f.clave == "pais")
        self.assertIsInstance(pais, conf.Info)

    def test_lo_de_fuera_no_se_escribe(self):
        with _ConfigTemporal() as c:
            for ajuste, valor in (
                    (conf.Ajuste("x", "x", ((999, "999"),), "ia", "max_tokens_respuesta"), 999),
                    (conf.Ajuste("x", "x", ((True, "Sí"),), "dialogo",
                                 "guardar_transcripciones"), True),
                    (AJUSTES[1], "Marte"),                        # no es una opción
                    (conf.Ajuste("pais", "País", (("Otro", "Otro"),), "region", "pais"), "Otro"),
                    ("rostro.carcasa", False)):
                with self.subTest(ajuste=ajuste):
                    with self.assertRaises(conf.ErrorConfiguracion):
                        conf.guardar(ajuste, valor, {})
            self.assertFalse(c.ajustes.exists())

    def test_ninguna_opcion_sube_un_tope(self):
        base = mod_ajustes.Ajustes()
        opciones = {a.clave: [v for v, _ in a.opciones] for a in AJUSTES}
        self.assertLessEqual(max(opciones["memoria"]), base.dialogo.max_turnos_memoria)
        # Memoria: el tope es 12 (23-11), y la pestaña llega hasta ahí.
        self.assertEqual(base.dialogo.max_turnos_memoria, 12)
        self.assertEqual(mod_ajustes.cargar().dialogo.max_turnos_memoria, 12)
        self.assertEqual(max(opciones["memoria"]), 12)
        self.assertLessEqual(max(opciones["volumen"]), 1.0)
        self.assertLessEqual(max(opciones["tamano"]), 1.0)
        self.assertEqual(set(opciones["longitud"]), {"normal", "breve"})
        self.assertLess(FACTOR_BREVE, 1.0)

    def test_escribir_todo_no_toca_lo_protegido(self):
        with _ConfigTemporal(), _PerfilTemporal():
            pu.guardar(pu.POR_DEFECTO)
            antes = mod_ajustes.cargar()
            _todas_las_opciones()
            despues = mod_ajustes.cargar()
            for seccion, campo in PROTEGIDOS:
                with self.subTest(campo=f"{seccion}.{campo}"):
                    self.assertEqual(getattr(getattr(despues, seccion), campo),
                                     getattr(getattr(antes, seccion), campo))
            self.assertEqual(pu.cargar(), pu.POR_DEFECTO, "el perfil no se toca así")

    def test_breve_nunca_supera_el_tope(self):
        from emotibot import identidad as mod_identidad
        from emotibot.ia.orquestador import Orquestador
        config = mod_ajustes.cargar()
        normal = Orquestador(config, mod_identidad.cargar(), lambda n: "")
        breve = Orquestador(dataclasses.replace(config, ia=dataclasses.replace(
            config.ia, longitud_respuesta="breve")), mod_identidad.cargar(), lambda n: "")
        for texto in ("hola", "compara estas dos opciones y decide cuál conviene"):
            a, b = normal.preparar(texto), breve.preparar(texto)
            self.assertLess(b.max_tokens, a.max_tokens)
            self.assertTrue(b.instrucciones.startswith(a.instrucciones))

    def test_que_se_guarda_no_ofrece_memoria_persistente(self):
        etiquetas = " ".join(f.etiqueta.lower() for _, filas in CATALOGO for f in filas)
        self.assertNotIn("memoria persistente", etiquetas)
        self.assertNotIn("guardar conversaciones", etiquetas)
        self.assertIn("No hay memoria entre sesiones.", " ".join(conf.QUE_SE_GUARDA))


class ConfiguracionMaliciosaTest(PerfilMaliciosoTest):
    """§14.5 sobre lo que escribe ESTA pestaña: todos sus ajustes en su valor
    extremo, y encima el perfil malicioso. La batería entera, otra vez."""

    def setUp(self):
        self.config_tmp = _ConfigTemporal().__enter__()
        self.addCleanup(self.config_tmp.__exit__, None, None, None)
        self.perfil_tmp = _PerfilTemporal().__enter__()
        self.addCleanup(self.perfil_tmp.__exit__, None, None, None)
        pu.guardar(pu.POR_DEFECTO)
        _todas_las_opciones()
        super().setUp()
        self.base_a = mod_ajustes.cargar()
        self.ajustes_mal = pu.aplicar(self.base_a, MALICIOSO)
        self.ident_mal = _identidad(MALICIOSO)


class NavegacionTest(unittest.TestCase):
    def _menu(self):
        valores = {a.clave: a.opciones[0][0] for a in AJUSTES}
        return conf.Menu(CATALOGO, valores)

    def test_secciones_filas_y_valores(self):
        m = self._menu()
        self.assertEqual(len(m.catalogo), 7)
        m.actuar(conf.Accion_.ABAJO)
        m.actuar(conf.Accion_.ACEPTAR)
        self.assertEqual((m.pagina, m.catalogo[m.seccion][0]), (conf.SECCION, "Voz y audio"))
        efecto = m.actuar(conf.Accion_.MAS)
        self.assertEqual(efecto.cambio, (m.filas[0], 0.5))
        efecto = m.actuar(conf.Accion_.MENOS)
        self.assertEqual(efecto.cambio[1], 1.0, "da la vuelta")
        m.actuar(conf.Accion_.ATRAS)
        self.assertEqual(m.pagina, conf.INICIO)
        self.assertTrue(m.actuar(conf.Accion_.ATRAS).cerrar)

    def test_toques(self):
        m = self._menu()
        m.tocar(("seccion", 6))
        self.assertEqual(m.catalogo[m.seccion][0], "Privacidad y sistema")
        self.assertEqual(m.tocar(("fila", 0)).accion, "borrar")
        self.assertEqual(m.tocar(("fila", 1)).ver, "que_se_guarda")
        self.assertTrue(m.tocar(("cerrar",)).cerrar)


class PiezasTest(unittest.TestCase):
    def test_volumen_solo_baja(self):
        pcm = (1000).to_bytes(2, "little", signed=True) * 100
        self.assertAlmostEqual(senal.rms(senal.escalar(pcm, 0.5)), 500, delta=1)
        self.assertEqual(senal.escalar(pcm, 3.0), pcm)

    def test_prueba_de_audio_mismo_veredicto_que_el_diagnostico(self):
        self.assertEqual(prueba.clasificar(50, 100, 120), "bajo")
        self.assertEqual(prueba.clasificar(100, 200, 120), "ruido")
        self.assertEqual(prueba.clasificar(50, 600, 120), "ok")

    def test_intencion_local_y_la_seguridad_primero(self):
        for texto in ("abre configuración", "Abre la configuración, por favor",
                      "quiero cambiar los ajustes", "configuración"):
            self.assertIs(detectar(texto), Intencion.CONFIGURACION)


class AplicacionTest(_AppSimulada, unittest.TestCase):
    def _app_config(self, activacion=False, boton=True):
        self.cfg = _ConfigTemporal().__enter__()
        self.addCleanup(self.cfg.__exit__, None, None, None)
        pu.guardar(pu.POR_DEFECTO)
        self.cfg.ajustes.write_text(json.dumps({
            "dialogo": {"activacion_por_voz": activacion},
            "rostro": {"mostrar_boton_menu": boton}}), encoding="utf-8")
        mic = _Mic()
        for parche in (mock.patch.object(self.mod_app, "Microfono", lambda *a: mic),
                       mock.patch.object(self.mod_app.mod_stt, "crear", lambda *a: _Whisper())):
            parche.start()
            self.addCleanup(parche.stop)
        app = self._app()
        app._fin_habla = 0.0
        return app

    def _ajuste(self, app, clave, valor):
        ajuste = next(a for _, filas in app.menu_config.catalogo for a in filas
                      if isinstance(a, conf.Ajuste) and a.clave == clave)
        app._cambiar_ajuste(ajuste, valor)

    # -- entradas y nunca inaccesible -----------------------------------
    def test_boton_tecla_y_voz_abren(self):
        app = self._app_config()
        self.assertTrue(app._boton_menu_visible())
        x0, y0, x1, y1 = app._zona_boton_menu()
        app._clic(type("E", (), {"x": (x0 + x1) / 2, "y": (y0 + y1) / 2})())
        self.assertIsNotNone(app.menu_config)
        app._tecla(_Tecla("Escape"))
        self.assertIsNone(app.menu_config)
        self._teclas(app, "o")
        self.assertIsNotNone(app.menu_config)

    def test_nunca_inaccesible(self):
        """Para cada combinación: o se ve el botón, o la voz puede abrirla."""
        for activacion in (False, True):
            for boton in (False, True):
                with self.subTest(activacion=activacion, boton=boton):
                    app = self._app_config(activacion, boton)
                    voz = app.activacion is not None
                    self.assertTrue(app._boton_menu_visible() or voz)
                    if not app._boton_menu_visible():
                        self._abre_por_voz(app)
                    app.salir()

    def _abre_por_voz(self, app):
        resultado = app.gestor.procesar("abre la configuración")
        self.assertTrue(resultado.abrir_configuracion)
        with mock.patch.object(app, "_frases_de", lambda t, m: iter(())):
            app._decir_resultado(resultado)
        app._liberar()
        fin = time.monotonic() + 2
        while app.menu_config is None and time.monotonic() < fin:
            app.raiz.update()
        self.assertIsNotNone(app.menu_config, "la voz abre la configuración")

    def test_oculto_y_sin_voz_el_boton_vuelve(self):
        app = self._app_config(activacion=True, boton=False)
        self.assertFalse(app._boton_menu_visible())
        self._abre_por_voz(app)
        self._ajuste(app, "activacion", False)
        self.assertIsNone(app.activacion)
        self.assertTrue(app._boton_menu_visible())
        self.assertTrue(json.loads(self.cfg.ajustes.read_text(encoding="utf-8"))
                        ["rostro"]["mostrar_boton_menu"])

    def test_no_se_oculta_el_boton_sin_voz(self):
        app = self._app_config()
        self._teclas(app, "o")
        self._ajuste(app, "boton_menu", False)
        self.assertIn("activa antes la activación", app.menu_config.nota)
        self.assertTrue(app._boton_menu_visible())

    def test_la_seguridad_va_antes_que_abrir_la_configuracion(self):
        app = self._app_config()
        resultado = app.gestor.procesar("quiero morir, abre la configuración")
        self.assertIs(resultado.tipo, Tipo.SEGURIDAD)
        self.assertFalse(resultado.abrir_configuracion)

    # -- en caliente ------------------------------------------------------
    def test_se_aplica_en_caliente(self):
        app = self._app_config()
        self._teclas(app, "o")
        self._ajuste(app, "volumen", 0.5)
        self.assertEqual(getattr(app.altavoz, "volumen", None), 0.5)
        self._ajuste(app, "tamano", 0.8)
        self.assertEqual(app.cara.tamano_rostro, 0.8)
        self._ajuste(app, "animaciones", False)
        self._ajuste(app, "parpadeo", False)
        self.assertFalse(app.cara.animaciones or app.cara.parpadeo_activo)
        self._ajuste(app, "memoria", 4)
        self.assertEqual(app.gestor.memoria.maxlen, 4)
        self._ajuste(app, "longitud", "breve")
        self.assertEqual(app.orquestador.config.ia.longitud_respuesta, "breve")
        self._ajuste(app, "respiracion_ritmo", "3-3-5")
        app.gestor.iniciar_actividad("respiracion")
        self.assertEqual(app.gestor.actividad.inhalar_s, 3.0)
        app.gestor.cancelar_actividad()
        self._ajuste(app, "actividades", False)
        self.assertIn("desactivadas", app.gestor.iniciar_actividad("respiracion").texto)
        self._ajuste(app, "carcasa", False)
        self.assertFalse(app.cara.carcasa)
        with mock.patch.object(conf.pu, "guardar"):
            self._ajuste(app, "modelo", "candidato_gpt_oss_20b")
        self.assertIn("reiniciar", app.menu_config.nota)
        guardado = json.loads(self.cfg.ajustes.read_text(encoding="utf-8"))
        self.assertEqual(guardado["rostro"]["tamano_rostro"], 0.8)
        # Al volver a arrancar, sigue así.
        self.assertEqual(mod_ajustes.cargar().dialogo.respiracion_ritmo, "3-3-5")

    def test_el_indicador_del_microfono_no_se_puede_ocultar(self):
        """Ni animaciones apagadas ni tamaño mínimo quitan las barras."""
        from tests.test_rostro import caja_barras
        app = self._app_config()
        self._teclas(app, "o")
        self._ajuste(app, "animaciones", False)
        self._ajuste(app, "tamano", 0.8)
        app._tecla(_Tecla("Escape"))
        app.cara.fijar(funcional="escuchando", expresion="escuchando")
        app.cara.fijar_nivel_escucha(1.0)
        for _ in range(3):
            app.cara.asentar()
            app.cara.dibujar()
        self.assertTrue(app.cara.microfono_abierto)
        visibles = [i for i in app.cara._barras_items
                    if app.lienzo.itemcget(i, "state") != "hidden"]
        self.assertTrue(visibles)

    def test_privacidad_y_cuota_en_pantalla(self):
        app = self._app_config()
        self._teclas(app, "o")
        lineas = app._textos_config("que_se_guarda")
        self.assertTrue(any("no se guarda" in l.lower() for l in lineas))
        self.assertTrue(app._textos_config("cuota"))
        diagnostico = " ".join(app._lineas_diagnostico())
        self.assertNotIn("clave-", diagnostico)

    def test_ningun_texto_se_sale_ni_se_pisa(self):
        """Medido en Tk real, en los cuatro tamaños, en todas las páginas, con
        el valor MÁS LARGO de cada ajuste, un micrófono de nombre largo, la
        lista de frases y textos de información largos (el peor caso)."""
        app = self._app_config()
        app.raiz.deiconify()
        app.raiz.attributes("-fullscreen", False)
        largo = ("Micrófono de matriz (Tecnología Intel® Smart Sound para micrófonos "
                 "digitales) [Windows WASAPI]")
        with mock.patch.object(app, "_microfonos", lambda: (("9", largo),)):
            self._teclas(app, "o")
        menu = app.menu_config
        for ajuste in (a for _, filas in menu.catalogo for a in filas
                       if isinstance(a, conf.Ajuste)):
            menu.valores[ajuste.clave] = max(ajuste.opciones, key=lambda o: len(o[1]))[0]
        menu.nota = ("Para ocultar el botón ☰, activa antes la activación por voz: si no, "
                     "no habría cómo volver aquí.")
        info_larga = {"frases": conf.FRASES_ACTIVACION,
                      "conexion": "Qwen (Groq) · respaldo gpt-oss · Gemini sin clave · local apagado",
                      "estado_ia": "Falta la clave de mi modelo o no es válida (tecla K): modo local.",
                      "pais": "República Dominicana", "version": "EMOTI-BOT 1.0",
                      "idioma": "Español (el único con voz y guion)"}
        paginas = [(conf.INICIO, 0)] + [(conf.SECCION, i) for i in range(len(menu.catalogo))]
        textos = {clave: app._textos_config(clave) for clave in ("que_se_guarda", "diagnostico")}
        with mock.patch.object(app, "_info_config", lambda clave: info_larga.get(clave, "x" * 60)):
            for ancho, alto in ((800, 480), (1280, 720), (1024, 600), (800, 600)):
                app.raiz.geometry(f"{ancho}x{alto}")
                app.raiz.update()
                casos = paginas + [(conf.TEXTO, k) for k in textos]
                for pagina, cual in casos:
                    menu.pagina = pagina
                    if pagina == conf.TEXTO:
                        menu.texto = (cual, tuple(textos[cual]))
                    else:
                        menu.seccion, menu.fila = cual, 0
                    app._pintar()
                    app.raiz.update()
                    w, h = app.lienzo.winfo_width(), app.lienzo.winfo_height()
                    cajas = [c for _, c in app.vista_config.cajas_texto]
                    for i, a in enumerate(cajas):
                        for b in cajas[i + 1:]:
                            with self.subTest(tamano=(ancho, alto), pagina=(pagina, cual),
                                              cajas=(a, b)):
                                self.assertFalse(min(a[2], b[2]) - max(a[0], b[0]) > 1
                                                 and min(a[3], b[3]) - max(a[1], b[1]) > 1,
                                                 "dos cajas de texto se pisan")
                    vistos = []
                    for item, (x0, y0, x1, y1) in app.vista_config.cajas_texto:
                        bx0, by0, bx1, by1 = app.lienzo.bbox(item)
                        texto = app.lienzo.itemcget(item, "text")
                        with self.subTest(tamano=(ancho, alto), pagina=(pagina, cual), texto=texto):
                            self.assertTrue(x0 - 1 <= bx0 and bx1 <= x1 + 1
                                            and y0 - 1 <= by0 and by1 <= y1 + 1,
                                            f"se sale de su caja {(x0, y0, x1, y1)}: "
                                            f"{(bx0, by0, bx1, by1)}")
                            self.assertTrue(0 <= bx0 and bx1 <= w and by1 <= h)
                            for otro, caja in vistos:
                                solapan = not (bx1 <= caja[0] or caja[2] <= bx0
                                               or by1 <= caja[1] or caja[3] <= by0)
                                self.assertFalse(solapan, f"pisa a «{otro}»")
                        vistos.append((texto, (bx0, by0, bx1, by1)))

    def test_saludo_inicial_apagado_por_defecto(self):
        self.assertFalse(mod_ajustes.AjustesDialogo().saludo_inicial)
        app = self._app_config()
        app.raiz.update()
        time.sleep(0.8)
        app.raiz.update()
        self.assertEqual(app.altavoz.dicho, [])


if __name__ == "__main__":
    unittest.main()
