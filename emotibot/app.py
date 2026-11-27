"""Ensamblaje de EMOTI-BOT: interfaz, hilos y flujo de un turno.

Reparto de responsabilidades, que es lo que evita las carreras de datos del
prototipo:

- El hilo de Tkinter dibuja y lee el teclado. NUNCA bloquea.
- Un hilo por turno graba, reconoce y consulta. Se comunica solo por cola.
- El altavoz tiene su propio hilo y es el ÚNICO dueño del proceso `aplay`.

Flujo de un turno:

    micrófono → VAD (calibra y avisa) → recorte → STT local → guardia de
    seguridad → gestor de diálogo → proveedor → síntesis por frases → altavoz

Cada etapa se cronometra por separado y se anota en logs/latencia.csv.
"""
from __future__ import annotations

import dataclasses
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, simpledialog
from typing import Iterator

from . import activacion as mod_activacion
from . import ajustes as mod_ajustes
from . import asistente as mod_asistente
from . import configuracion as conf
from . import perfil_usuario as pu
from . import credenciales, identidad as mod_identidad, metricas, registro, rutas
from . import stt as mod_stt
from . import voz as mod_voz
from .audio.captura import ErrorCaptura, Microfono, MotivoFin
from .audio.reproduccion import Altavoz
from .audio.vad import Fase
from .depuracion import DepuracionStt
from .dialogo import Gestor, Guardia, Tipo
from .dialogo import directorio as mod_directorio
from .dialogo.seguridad import cargar_recursos
from . import disposicion_textos
from .panel_directorio import SEGUNDOS_SI_SE_PIDE_HABLANDO, PanelDirectorio
from .dialogo.actividades import OrdenarIdeas, Respiracion
from .ia import Orquestador
from .ia import disponibilidad as disp
from .rostro import crear_cara
from .rostro.perfil import cargar as cargar_perfil
from .vista_asistente import VistaAsistente
from .vista_configuracion import VistaConfiguracion

log = registro.obtener("app")

VERSION = "1.0"
# Conversación seguida: margen tras callar el altavoz antes de reabrir el
# micrófono (el VAD además calibra el ruido antes de aceptar voz) y tope de
# tiempo por conversación.
MARGEN_CONVERSACION_S = 0.6
MAX_SEGUNDOS_CONVERSACION = 180.0
FIN_CONVERSACION = "Fin de la conversación. Pulsa ESPACIO o di «Hola Emoti» para seguir."
AYUDA = (
    "ESPACIO hablar · F grabación fija · 2 respirar · 4 ordenar ideas · "
    "M micrófono · S parar voz · 0 olvidar · K clave · D diagnóstico · "
    "T depurar STT · A números de ayuda · P perfil · C carcasa · O configuración · "
    "Esc salir"
)


# Franjas (arriba, abajo) para los textos del asistente sin carcasa: las
# mismas que deja la cara con carcasa (0,15–0,81 del alto).
RESERVA_ASISTENTE = (0.15, 0.19)


class Aplicacion:
    def __init__(self) -> None:
        # Ajustes e identidad ya llevan el perfil de usuario (D10).
        self.config = mod_ajustes.cargar()
        self.identidad = mod_identidad.cargar()
        # Un perfil corrupto o incompleto no rompe el arranque: ajustes e
        # identidad ya usan el de por defecto, y aquí se guarda el aviso.
        self.perfil, aviso_perfil = pu.cargar_con_aviso()
        log.info("Perfil de usuario: %s.", pu.resumen(self.perfil))
        # Una clave por proveedor: gemini, qwen, deepseek…
        self.claves: dict[str, str] = {}
        self.orquestador = Orquestador(
            self.config, self.identidad, self._clave_de
        )
        # §14.4.1: el orquestador anuncia PROCESANDO / ESPERANDO /
        # NO_DISPONIBLE desde el hilo del turno; aquí llegan por la cola.
        self.orquestador.al_estado = lambda estado, causa, segundos: self.eventos.put(
            ("ia", (estado, causa, segundos)))
        self._ia_turno: tuple[str, str] = (disp.DISPONIBLE, "")
        self._espera_hablada = False
        # Números de ayuda: solo de config/crisis.json y solo si son del país
        # configurado (region.pais). La ruta de crisis y el directorio los
        # leen por separado y no comparten interfaz.
        self.guardia = Guardia(cargar_recursos(pais=self.config.region.pais))
        self.directorio = mod_directorio.cargar(self.config.region.pais)
        self.gestor = Gestor(
            self.config, self.identidad, self.orquestador, self.guardia,
            directorio=self.directorio
        )

        self.voz = mod_voz.crear(self.config)
        self.voz_respaldo = None
        self.altavoz = Altavoz(self.config.audio)
        self.microfono = Microfono(self.config.audio)
        self.stt = mod_stt.crear(self.config, self.orquestador.remoto)
        self.bitacora = metricas.Bitacora()

        self.eventos: queue.Queue[tuple[str, object]] = queue.Queue()
        self.cancelar_turno = threading.Event()
        self.ocupado = False
        self.microfono_silenciado = False
        self.cerrando = False
        self.detalle = "Pulsa ESPACIO y háblame."
        self.metricas_ultimas = ""
        self.aviso_persistente = ""
        self._turno_actual: threading.Thread | None = None
        self._medicion: metricas.Medicion | None = None
        # Fase 1, B2: apagado al arrancar, siempre. Ver emotibot/depuracion.py.
        self.depuracion = DepuracionStt()

        # Asistente de perfil (D10, tanda 3).
        self.asistente: mod_asistente.Asistente | None = None
        self._nota_asistente = ""
        self._muestras: dict[str, object] = {}     # voz de muestra por nombre
        self._cargando_muestra: set[str] = set()
        self._voz_pendiente = None                 # voz nueva lista en mitad de un turno

        self._fin_habla = 0.0
        # Conversación seguida: [turnos encadenados, inicio] de la actual.
        self._cadena: list | None = None
        self._turno_continuo = False
        self._construir_interfaz()
        self.vista_asistente = VistaAsistente(self.lienzo)
        self.activacion = self._crear_activacion()
        # Configuración (pestaña completa).
        self.menu_config: conf.Menu | None = None
        self.vista_config = VistaConfiguracion(self.lienzo)
        self._abrir_config_tras_hablar = False
        self._info_cache: tuple[float, dict[str, str]] = (0.0, {})
        self._firma_boton = None
        self.lienzo.bind("<Button-1>", self._clic)
        self._avisar_arranque()
        if aviso_perfil:
            self.detalle = f"{aviso_perfil} Pulsa P para elegir otro."
            # Sin carcasa no hay textos: la cara es la que avisa.
            self.cara.fijar_estado("error")
        if pu.primer_arranque():
            # Antes de nada: nadie ha elegido todavía en esta máquina.
            self._abrir_asistente(primer_arranque=True)
        elif self.config.dialogo.saludo_inicial and not aviso_perfil:
            self.raiz.after(700, self._saludar)

    def _clave_de(self, proveedor: str) -> str:
        """Clave de un proveedor: la de esta sesión o la guardada."""
        if proveedor not in self.claves:
            self.claves[proveedor] = credenciales.cargar(proveedor)
        return self.claves[proveedor]

    # ------------------------------------------------------------------ interfaz
    def _construir_interfaz(self) -> None:
        self.raiz = tk.Tk()
        self.raiz.title(f"EMOTI-BOT {VERSION}")
        # Los colores de la interfaz son los del mismo perfil que la cara.
        self.paleta = cargar_perfil(self.config.rostro.perfil).colores
        self.raiz.configure(bg=self.paleta.fondo)
        if self.config.rostro.pantalla_completa:
            try:
                self.raiz.attributes("-fullscreen", True)
            except tk.TclError:
                self.raiz.geometry("900x600")
        else:
            self.raiz.geometry("900x600")

        self.lienzo = tk.Canvas(self.raiz, bg=self.paleta.fondo, highlightthickness=0)
        self.lienzo.pack(fill="both", expand=True)
        # La misma fábrica que usa el visor (bin/vista_previa_rostro.py).
        self.cara = crear_cara(self.lienzo, self.config.rostro)
        perfil = self.cara.perfil
        log.info("Rostro: perfil %s · carcasa %s · ojo %.3f × %.3f · cabeza ×%.2f.",
                 perfil.nombre, "sí" if self.cara.carcasa else "no",
                 perfil.rasgos.ojo_ancho, perfil.rasgos.ojo_alto, perfil.cabeza.tamano)

        self._firma_textos = None
        self._textos: dict[str, int] = {}
        for clave, ancla in (("nombre", "n"), ("creador", "n"), ("estado", "n"),
                             ("detalle", "n"), ("depuracion", "n"),
                             ("privacidad", "n"),
                             ("metricas", "n"), ("controles", "s")):
            self._textos[clave] = self.lienzo.create_text(
                0, 0, text="", fill=self.paleta.tinta, anchor=ancla, justify="center"
            )

        self.panel_directorio = PanelDirectorio(self.lienzo, self.paleta,
                                                self.directorio)
        self.raiz.bind("<Key>", self._tecla)
        self.raiz.protocol("WM_DELETE_WINDOW", self.salir)
        self.raiz.focus_force()

    def _avisar_arranque(self) -> None:
        avisos = self.guardia.advertencias_arranque()
        if avisos:
            self.aviso_persistente = "Revisa config/crisis.json"
        log.info(
            "Motor de audio: %s · Voz: %s · Reconocimiento: %s · "
            "Inteligencia: %s", self.microfono.motor(), self.voz.nombre,
            self.stt.nombre, self.orquestador.estado_corto(),
        )
        if not self.microfono.disponible():
            self.detalle = self._consejo_sin_audio()
        elif not self.stt.disponible():
            self.detalle = ("Sin reconocimiento de voz. Las actividades y las "
                            "teclas funcionan igual.")

    def _crear_activacion(self):
        """«Hola Emoti», si está activada y se puede hacer en LOCAL."""
        if not self.config.dialogo.activacion_por_voz:
            return None
        if not self.microfono.disponible():
            return None
        # Su propio Whisper LOCAL: base con la pista del nombre. Si no se
        # puede cargar, no hay despertar (el audio no sale antes de activar).
        transcriptor = self._transcriptor_activacion()
        if not mod_activacion.EscuchaActivacion.admite(transcriptor):
            log.warning("Activación por voz pedida, pero sin Whisper local: no la "
                        "activo (el audio no sale del equipo antes de activar).")
            return None
        escucha = mod_activacion.EscuchaActivacion(
            self.microfono, transcriptor, self._puede_escuchar_activacion,
            lambda saludo: self.eventos.put(("activacion", saludo)))
        escucha.iniciar()
        log.info("Activación por voz encendida.")
        return escucha

    def _transcriptor_activacion(self):
        from .stt.whisper_local import PISTA_NOMBRE, WhisperLocal
        from .stt.base import ErrorStt
        try:
            return WhisperLocal(self.config.stt, modelo=self.config.stt.modelo_activacion,
                                pista=PISTA_NOMBRE)
        except ErrorStt as exc:
            log.warning("Sin Whisper para el despertar: %s", exc)
            return None

    def _puede_escuchar_activacion(self) -> bool:
        """Desde el hilo de activación: nunca durante un turno, mientras habla
        el robot (ni justo después) o con el micrófono silenciado."""
        return not (self.ocupado or self.cerrando or self.asistente is not None
                    or self.microfono_silenciado or self.altavoz.hablando()
                    or time.monotonic() - self._fin_habla
                    < mod_activacion.MARGEN_TRAS_HABLAR_S)

    def _consejo_sin_audio(self) -> str:
        """Mensaje que dice qué instalar en ESTE sistema, no en otro."""
        if self.microfono.motor() == "alsa":
            return "Falta arecord: instala alsa-utils para poder hablarme."
        return ("Falta el motor de audio: instala sounddevice "
                "(pip install sounddevice) para poder hablarme.")

    # ------------------------------------------------------------------- teclado
    def _tecla(self, evento: tk.Event) -> None:
        nombre = (evento.keysym or "").lower()
        caracter = (evento.char or "").lower()

        if self.menu_config is not None:
            accion_config = conf.TECLAS.get(nombre)
            if accion_config is not None:
                self._efecto_config(self.menu_config.actuar(accion_config))
            return
        if self.asistente is not None:
            # Con el asistente abierto, las teclas son SUYAS (y solo las que
            # traduce a acciones): ni turnos ni actividades por debajo.
            accion = mod_asistente.accion_de_tecla(nombre)
            if accion is not None:
                self._actuar_asistente(accion)
            return
        if nombre == "escape":
            self.salir()
        elif nombre == "space" or caracter == "5":
            self._pedir_turno(fijo=False)
        elif caracter == "f":
            self._pedir_turno(fijo=True)
        elif caracter == "s":
            self._cadena = None            # S también corta la conversación seguida
            self._parar_voz()
        elif caracter == "0":
            self.gestor.limpiar_memoria()
            self.detalle = "Olvidé lo que hablamos en esta sesión."
        elif caracter == "1":
            self._cancelar_actividad()
        elif caracter == "2":
            self._lanzar_actividad(Respiracion.nombre)
        elif caracter == "4":
            self._lanzar_actividad(OrdenarIdeas.nombre)
        elif caracter == "m":
            self.microfono_silenciado = not self.microfono_silenciado
            self.detalle = ("Micrófono silenciado. Pulsa M para reactivarlo."
                            if self.microfono_silenciado
                            else "Micrófono disponible.")
        elif caracter == "k":
            self._configurar_clave()
        elif caracter == "d":
            self._mostrar_diagnostico()
        elif caracter == "t":
            if self.depuracion.alternar():
                self.detalle = ("Depuración de transcripción activada. El texto "
                                "solo se ve aquí: no se guarda ni se envía.")
            else:
                self.detalle = "Depuración de transcripción desactivada."
        elif caracter == "a":
            # Directorio de ayuda: consulta. Abre y cierra la barra lateral.
            self.panel_directorio.alternar()
        elif caracter == "p":
            self._abrir_asistente()
        elif caracter == "o":
            self._abrir_configuracion()
        elif caracter == "c":
            self._alternar_carcasa()
        elif caracter == "l":
            self.orquestador.liberar_remoto()
            self.detalle = "Reintentaré el proveedor remoto en el próximo turno."

    # ------------------------------------------------------------------ carcasa
    def _alternar_carcasa(self) -> None:
        """Con o sin carcasa, en caliente y guardado en los ajustes de esta
        máquina (no en el perfil: es cómo está montado el robot)."""
        carcasa = not self.cara.carcasa
        self.cara.reconfigurar(carcasa=carcasa)
        self.config = dataclasses.replace(
            self.config, rostro=dataclasses.replace(self.config.rostro, carcasa=carcasa))
        self._firma_textos = None
        estado = "con carcasa" if carcasa else "sin carcasa"
        try:
            mod_ajustes.guardar_carcasa(carcasa)
            self.detalle = f"Rostro {estado}. Guardado para el próximo arranque."
        except (OSError, ValueError) as exc:
            log.error("No pude guardar la carcasa: %s", exc)
            self.detalle = f"Rostro {estado}, solo en esta sesión: no pude guardarlo."
        log.info("Carcasa: %s.", "sí" if carcasa else "no")

    # ------------------------------------------------------------ configuración
    def _boton_menu_visible(self) -> bool:
        """NUNCA inaccesible: oculto solo si de verdad queda la voz (la
        activación por voz en marcha). Si no, se ve aunque el ajuste diga
        que no."""
        return bool(self.config.rostro.mostrar_boton_menu or self.activacion is None)

    def _zona_boton_menu(self) -> tuple[float, float, float, float]:
        ancho = max(self.lienzo.winfo_width(), 320)
        lado = max(40.0, min(ancho, max(self.lienzo.winfo_height(), 240)) * 0.09)
        return ancho - lado - 6, 6, ancho - 6, 6 + lado

    def _colocar_boton_menu(self) -> None:
        visible = (self._boton_menu_visible() and self.menu_config is None
                   and self.asistente is None)
        zona = self._zona_boton_menu()
        firma = (visible, zona, self.paleta.tenue)
        if firma == self._firma_boton:
            return
        self._firma_boton = firma
        self.lienzo.delete("boton_menu")
        if not visible:
            return
        x0, y0, x1, y1 = zona
        for i in range(3):                         # ☰: tres líneas
            y = y0 + (y1 - y0) * (0.3 + 0.2 * i)
            self.lienzo.create_line(x0 + (x1 - x0) * 0.22, y, x1 - (x1 - x0) * 0.22, y,
                                    fill=self.paleta.tenue, width=max(2, int((y1 - y0) * 0.08)),
                                    capstyle="round", tags=("boton_menu",))

    def _clic(self, evento) -> None:
        if self.menu_config is not None:
            objetivo = self.vista_config.objetivo_en(evento.x, evento.y)
            if objetivo is not None:
                self._efecto_config(self.menu_config.tocar(objetivo))
            return
        if self.asistente is not None or not self._boton_menu_visible():
            return
        x0, y0, x1, y1 = self._zona_boton_menu()
        if x0 <= evento.x <= x1 and y0 <= evento.y <= y1:
            self._abrir_configuracion()

    def _abrir_configuracion(self) -> None:
        if self.asistente is not None or self.menu_config is not None:
            return
        if self.ocupado:
            self.detalle = "Espera a que termine el turno para abrir la configuración."
            return
        catalogo = conf.secciones(self._microfonos(),
                                  tuple(pu.opciones("modelo")))
        self.menu_config = conf.Menu(catalogo, conf.valores_de(self.config, self.perfil))
        self._info_cache = (0.0, {})
        self.panel_directorio.ocultar()
        for item in self._textos.values():
            self.lienzo.itemconfigure(item, text="")
        self._firma_textos = None

    def _cerrar_configuracion(self) -> None:
        self.menu_config = None
        self.vista_config.ocultar()
        self._firma_textos = None
        self._firma_boton = None
        self.cara.reconfigurar()                    # se redibuja entera

    def _microfonos(self) -> tuple[tuple[str, str], ...]:
        try:
            from .audio import dispositivos
            inventario = dispositivos.inventariar(self.config.audio.motor
                                                  if self.config.audio.motor != "auto" else "")
            lista = [(t.identificador, t.descripcion) for t in inventario.captura]
        except Exception as exc:                    # sin inventario, el predeterminado
            log.info("Sin inventario de micrófonos: %s", exc)
            lista = []
        actual = self.config.audio.dispositivo_captura
        if actual and actual not in [i for i, _ in lista]:
            lista.append((actual, actual))
        return tuple(lista)

    def _efecto_config(self, efecto: conf.Efecto) -> None:
        menu = self.menu_config
        if menu is None:
            return
        if efecto.cerrar:
            self._cerrar_configuracion()
            return
        if efecto.cambio is not None:
            self._cambiar_ajuste(*efecto.cambio)
        if efecto.accion:
            self._accion_config(efecto.accion)
        if efecto.ver:
            titulo = next(f.etiqueta for _, filas in menu.catalogo for f in filas
                          if f.clave == efecto.ver)
            menu.mostrar_texto(titulo, self._textos_config(efecto.ver))

    def _cambiar_ajuste(self, ajuste: conf.Ajuste, valor) -> None:
        menu = self.menu_config
        try:
            cambios = conf.guardar(ajuste, valor, menu.valores)
        except (conf.ErrorConfiguracion, pu.ErrorPerfilUsuario, OSError, ValueError) as exc:
            menu.nota = str(exc)
            return
        menu.valores.update(cambios)
        for clave, nuevo in cambios.items():
            self._aplicar_ajuste(clave, nuevo)
        if ajuste.reinicio:
            menu.nota = "Guardado. Se aplica al reiniciar."

    def _reemplazar(self, seccion: str, campo: str, valor) -> None:
        self.config = dataclasses.replace(self.config, **{seccion: dataclasses.replace(
            getattr(self.config, seccion), **{campo: valor})})

    def _aplicar_ajuste(self, clave: str, valor) -> None:
        """En caliente, salvo país y modelo (al reiniciar, y se dice)."""
        destino = next((f for _, filas in conf.secciones((), ()) for f in filas
                        if isinstance(f, conf.Ajuste) and f.clave == clave and f.seccion), None)
        if destino is None:
            return
        self._reemplazar(destino.seccion, destino.campo, valor)
        if clave == "pantalla_completa":
            try:
                self.raiz.attributes("-fullscreen", bool(valor))
            except tk.TclError:
                pass
        elif clave in ("boton_menu", "fila_teclas"):
            self._firma_textos = self._firma_boton = None
        elif clave == "volumen":
            self.altavoz.volumen = float(valor)
        elif clave == "ritmo":
            threading.Thread(target=lambda: self.eventos.put(
                ("voz_nueva", mod_voz.crear(self.config))), name="voz-ritmo",
                daemon=True).start()
        elif clave in ("microfono", "sensibilidad", "silencio"):
            self.microfono = Microfono(self.config.audio)
            if self.activacion is not None:
                self.activacion.pausar()
                self.activacion.microfono = self.microfono
        elif clave == "activacion":
            if valor and self.activacion is None:
                self.activacion = self._crear_activacion()
                if self.activacion is None and self.menu_config is not None:
                    self.menu_config.nota = ("Guardado, pero ahora no puede escuchar: "
                                             "hace falta Whisper local y micrófono.")
            elif not valor and self.activacion is not None:
                self.activacion.detener()
                self.activacion = None
            self._firma_boton = None
        elif clave == "memoria":
            from collections import deque
            self.gestor.memoria = deque(self.gestor.memoria, maxlen=int(valor))
            self.gestor.config = self.config
        elif clave == "longitud":
            orq = self.orquestador
            orq.config = dataclasses.replace(orq.config, ia=dataclasses.replace(
                orq.config.ia, longitud_respuesta=valor))
        elif clave in ("actividades", "respiracion_ritmo"):
            self.gestor.config = self.config
        elif clave == "carcasa":
            self.cara.reconfigurar(carcasa=bool(valor))
            self._firma_textos = None
        elif clave in ("tamano", "animaciones", "parpadeo"):
            from .rostro.cara import aplicar_ajustes
            aplicar_ajustes(self.cara, self.config.rostro)

    def _accion_config(self, clave: str) -> None:
        menu = self.menu_config
        if clave == "depuracion":
            activa = self.depuracion.alternar()
            menu.nota = ("La transcripción se verá en pantalla (no se guarda)."
                         if activa else "Transcripción en pantalla: apagada.")
        elif clave == "borrar":
            self.gestor.limpiar_memoria()
            menu.nota = "Conversación borrada."
        elif clave == "asistente":
            self._cerrar_configuracion()
            self._abrir_asistente()
        elif clave == "prueba_audio":
            self._prueba_audio()

    def _info_config(self, clave: str) -> str:
        """Textos de solo lectura. Se calculan como mucho cada 2 s: alguno
        (la conexión) pregunta al servidor local."""
        marca, cache = self._info_cache
        if time.monotonic() - marca > 2.0:
            estado, causa, _ = self.orquestador.disponibilidad()
            cache = {
                "idioma": "Español (el único con voz y guion)",
                "pais": self.config.region.pais,
                "frases": conf.FRASES_ACTIVACION,
                "estado_ia": {disp.DISPONIBLE: "Disponible",
                              disp.ESPERANDO: "Esperando: límite por minuto",
                              }.get(estado, disp.TEXTOS_PANTALLA.get(causa, estado)),
                "version": f"EMOTI-BOT {VERSION}",
                "conexion": self.orquestador.estado_corto(),
            }
            self._info_cache = (time.monotonic(), cache)
        return cache.get(clave, "")

    def _textos_config(self, clave: str) -> list[str]:
        if clave == "que_se_guarda":
            remoto = ("El audio no sale: se reconoce en el equipo."
                      if self.stt.nombre == "whisper-local" else
                      "Sin Whisper local, el reconocimiento remoto envía también el "
                      "audio de cada turno.")
            return [linea.format(remoto=remoto) for linea in conf.QUE_SE_GUARDA]
        if clave == "cuota":
            lineas = []
            for nombre in self.config.ia.orden_proveedores:
                proveedor = self.orquestador._por_nombre.get(nombre)
                modelo = getattr(proveedor, "modelo", "")
                if nombre in ("guion", "local") or not modelo or \
                        self.orquestador._desactivado(nombre):
                    continue
                lineas.append(f"{nombre} ({modelo}): "
                              f"{self.orquestador.presupuesto.resumen(modelo)}")
            return lineas or ["Sin proveedores remotos configurados."]
        if clave == "diagnostico":
            return self._lineas_diagnostico()
        return []

    def _prueba_audio(self) -> None:
        """bin/diagnostico_audio.py en pantalla: suena la voz, mide el ruido
        3 s y la voz 3 s, y da el mismo veredicto."""
        menu = self.menu_config
        lineas: list[str] = ["Escucha: hablo con el volumen elegido…"]
        menu.mostrar_texto("Prueba de audio", lineas)
        self.ocupado = True
        if self.activacion is not None:
            self.activacion.pausar()

        def avisar(texto: str) -> None:
            lineas.append(texto)
            self.eventos.put(("prueba_audio", list(lineas)))

        def trabajar() -> None:
            from .audio import prueba, senal
            from .audio.captura import ErrorCaptura
            try:
                self.altavoz.hablar(self._frases_de("Esta es mi voz con el volumen elegido.",
                                                    None), self.voz.frecuencia)
                fin = time.monotonic() + 8
                time.sleep(0.3)
                while self.altavoz.hablando() and time.monotonic() < fin:
                    time.sleep(0.1)
                if not self.microfono.disponible():
                    avisar(self._consejo_sin_audio())
                    return
                fijo = Microfono(dataclasses.replace(self.config.audio,
                                                     segundos_grabacion_fija=3))
                avisar("Silencio, por favor: mido el ruido (3 s)…")
                ruido = senal.rms(fijo.grabar_fijo(threading.Event()).pcm)
                avisar("Ahora habla normal, a tu distancia de siempre (3 s)…")
                voz = senal.rms(fijo.grabar_fijo(threading.Event()).pcm)
                avisar("")
                for linea in prueba.veredicto(ruido, voz,
                                              float(self.config.audio.piso_umbral_rms)):
                    avisar(linea)
            except (ErrorCaptura, OSError) as exc:
                avisar(f"No pude usar el micrófono: {exc}")
            finally:
                self.eventos.put(("fin_prueba_audio", None))

        threading.Thread(target=trabajar, name="prueba-audio", daemon=True).start()

    def _saludar_y_escuchar(self, saludo: str) -> None:
        """«Hola Emoti»: responde al saludo (texto local, variado) y, al
        terminar de decirlo, abre el turno."""
        frase = mod_activacion.respuesta_saludo(saludo, getattr(self, "_ultimo_saludo", ""))
        self._ultimo_saludo = frase
        self.ocupado = True                 # ni activación ni turnos mientras saluda
        self.cara.fijar(funcional="reposo", expresion="feliz")
        self.detalle = frase
        self.altavoz.hablar(
            self._frases_de(frase, None), self.voz.frecuencia,
            al_primer_sonido=lambda: self.eventos.put(("sonando", "feliz")),
            al_terminar=lambda completo: self.eventos.put(("fin_saludo", None)))

    def _saludar(self) -> None:
        if self.ocupado or self.asistente is not None or self.cerrando:
            return
        frase = f"Hola, soy {self.identidad.nombre}. Pulsa espacio para hablar conmigo"
        frase += ", o dime hola Emoti." if self.activacion is not None else "."
        self.altavoz.hablar(self._frases_de(frase, None), self.voz.frecuencia)

    # ---------------------------------------------------------------- asistente
    def _abrir_asistente(self, primer_arranque: bool = False) -> None:
        if self.ocupado:
            self.detalle = "Espera a que termine el turno para cambiar el perfil."
            return
        self.asistente = mod_asistente.Asistente(self.perfil,
                                                 primer_arranque=primer_arranque)
        self._nota_asistente = ""
        # El rostro se elige en el modo en que se va a usar. Sin carcasa, la
        # cara deja libres las mismas franjas que con ella para los textos.
        if not self.cara.carcasa:
            self.cara.reconfigurar(reserva=RESERVA_ASISTENTE)
        self.cara.fijar_estado("reposo")
        self.panel_directorio.ocultar()
        for item in self._textos.values():
            self.lienzo.itemconfigure(item, text="")
        self._firma_textos = None

    def _actuar_asistente(self, accion: mod_asistente.Accion) -> None:
        asistente = self.asistente
        if asistente is None:
            return
        estaba_en_voz = asistente.paso == "voz"
        efecto = asistente.actuar(accion)
        if efecto.terminado:
            self._cerrar_asistente()
            return
        if efecto.rostro and efecto.rostro != self.cara.perfil.nombre:
            self._mostrar_rostro(efecto.rostro)
        if efecto.oir:
            self._oir_voz(efecto.oir)
        elif estaba_en_voz:
            self.altavoz.detener()
            self.cara.fijar_estado("reposo")

    def _mostrar_rostro(self, nombre: str) -> None:
        perfil = cargar_perfil(nombre)
        self.cara.reconfigurar(perfil=perfil)
        self.paleta = perfil.colores
        self.raiz.configure(bg=self.paleta.fondo)
        self.lienzo.configure(bg=self.paleta.fondo)
        self.panel_directorio.paleta = self.paleta
        self.panel_directorio._firma = None

    def _crear_voz(self, nombre: str):
        """Un sintetizador con la voz `nombre` (carga el modelo de Piper)."""
        config = pu.aplicar(self.config, dataclasses.replace(self.perfil, voz=nombre))
        return mod_voz.crear(config)

    def _oir_voz(self, nombre: str) -> None:
        """La frase de muestra con esa voz. El modelo se carga en un hilo (no
        congela la cara) y se guarda: volver a ella ya no espera."""
        self.altavoz.detener()
        if nombre in self._muestras:
            self._decir_muestra(nombre)
            return
        self._nota_asistente = "Cargando la voz…"
        if nombre in self._cargando_muestra:
            return
        self._cargando_muestra.add(nombre)

        def cargar() -> None:
            try:
                voz = self._crear_voz(nombre)
            except Exception as exc:            # nunca tumba la interfaz
                log.warning("No pude cargar la voz %s: %s", nombre, exc)
                voz = mod_voz.VozSilenciosa()
            self.eventos.put(("voz_muestra", (nombre, voz)))

        threading.Thread(target=cargar, name="voz-muestra", daemon=True).start()

    def _decir_muestra(self, nombre: str) -> None:
        asistente = self.asistente
        if asistente is None or asistente.paso != "voz" or asistente.actual() != nombre:
            return                                 # ya se movió a otra
        voz = self._muestras[nombre]
        if voz.nombre == "silenciosa" or not self.altavoz.disponible():
            self._nota_asistente = ("Aquí no puedo hacerla sonar: falta el motor de voz "
                                    "o el altavoz.")
            return
        self._nota_asistente = ("" if voz.nombre == "piper" else
                                "Falta el modelo de Piper de esta voz: oyes la de respaldo.")
        frase = f"Hola, soy {self.identidad.nombre}. Así sonaría mi voz."
        self.altavoz.hablar(
            (b"".join(voz.sintetizar(f)) for f in (frase,)), voz.frecuencia,
            al_primer_sonido=lambda: self.eventos.put(("sonando", "feliz")),
            al_terminar=lambda completo: self.eventos.put(("fin_muestra", None)),
        )

    def _cerrar_asistente(self) -> None:
        asistente, self.asistente = self.asistente, None
        self.altavoz.detener()
        self.vista_asistente.ocultar()
        self._nota_asistente = ""
        perfil = asistente.resultado if asistente else None
        guardado = False
        if perfil is not None:
            try:
                pu.guardar(perfil)
                guardado = True
            except (OSError, ValueError) as exc:
                log.error("No pude guardar el perfil: %s", exc)
                self.detalle = "No pude guardar el perfil: solo vale para esta sesión."
            self._aplicar_perfil(perfil, guardado)
        else:
            self._mostrar_rostro(self.config.rostro.perfil)
        if self.cara.reserva_vertical is not None:
            self.cara.reconfigurar(reserva=None)
        self.cara.fijar_estado("reposo")
        self._firma_textos = None

    def _aplicar_perfil(self, perfil: pu.PerfilUsuario, guardado: bool) -> None:
        """El perfil nuevo, SIN reiniciar.

        - rostro: la cara se recrea con su perfil y la interfaz toma su paleta;
        - voz: el modelo de Piper se carga en un hilo (o se reutiliza el de la
          muestra) y se cambia cuando no se está hablando;
        - personalidad y estilo: solo texto; la identidad nueva va al gestor y
          al orquestador y vale desde el turno siguiente;
        - modelo de conversación: NO en caliente (el orquestador ya tiene su
          orden de proveedores); se dice y vale al reiniciar.
        """
        # Con el perfil ya en disco, lo mismo que leería un arranque nuevo
        # (variables EMOTI_* incluidas); si no se pudo guardar, en memoria.
        nuevo = mod_ajustes.cargar() if guardado else pu.aplicar(self.config, perfil)
        identidad = pu.aplicar_identidad(
            mod_identidad.cargar(rutas.CONFIG_REPO / "identidad.json"), perfil)
        anterior, self.perfil = self.perfil, perfil

        self._mostrar_rostro(nuevo.rostro.perfil)
        voz_cambia = nuevo.voz != self.config.voz
        self.config = dataclasses.replace(self.config, rostro=nuevo.rostro, voz=nuevo.voz)

        self.identidad = identidad
        self.orquestador.identidad = identidad
        self.orquestador.guion.identidad = identidad
        self.gestor.identidad = identidad

        avisos = []
        if perfil.modelo != anterior.modelo:
            avisos.append("El modelo de conversación cambia al reiniciar.")
        if voz_cambia:
            voz = self._muestras.pop(perfil.voz, None)
            if voz is not None:
                self._cambiar_voz(voz)
            else:
                avisos.append("Cargando la voz nueva…")
                threading.Thread(target=lambda: self.eventos.put(
                    ("voz_nueva", self._crear_voz(perfil.voz))),
                    name="voz-nueva", daemon=True).start()
        for voz in self._muestras.values():
            self._cerrar_componente(voz)
        self._muestras.clear()
        if not self.detalle.startswith("No pude guardar"):
            self.detalle = " ".join(["Perfil listo." if guardado else "", *avisos]).strip()

    def _cambiar_voz(self, voz) -> None:
        if self.ocupado:
            # Nunca a mitad de una frase: se cambia al terminar el turno.
            self._voz_pendiente = voz
            return
        anterior, self.voz = self.voz, voz
        self._cerrar_componente(anterior)
        if self.voz_respaldo:
            self._cerrar_componente(self.voz_respaldo)
        self.voz_respaldo = None
        log.info("Voz cambiada en caliente: %s.", getattr(voz, "nombre", "?"))

    @staticmethod
    def _cerrar_componente(componente) -> None:
        if componente and hasattr(componente, "cerrar"):
            try:
                componente.cerrar()
            except Exception:
                pass

    # -------------------------------------------------------------------- clave
    def _configurar_clave(self) -> None:
        """Pide la clave del proveedor que haga falta.

        Con varios modelos hay varias claves. Se propone primero la que
        bloquea al proveedor preferido, para no tener que recordar cuál era.
        """
        if self.ocupado:
            self.detalle = "Espera a que termine el turno."
            return

        pendientes = self.orquestador.claves_pendientes()
        sugerida = pendientes[0] if pendientes else "gemini"
        proveedor = simpledialog.askstring(
            "¿Clave de qué proveedor?",
            "Nombre del proveedor (por ejemplo: qwen, deepseek, gemini).\n"
            + (f"Pendientes ahora mismo: {', '.join(pendientes)}"
               if pendientes else "Todos los configurados ya tienen clave."),
            initialvalue=sugerida, parent=self.raiz,
        )
        self.raiz.focus_force()
        if not proveedor or not proveedor.strip():
            return
        proveedor = proveedor.strip().lower()

        nueva = simpledialog.askstring(
            f"Clave de {proveedor}",
            "Pega la clave. No se muestra en pantalla ni en los registros:",
            show="*", parent=self.raiz,
        )
        self.raiz.focus_force()
        if not nueva or not nueva.strip():
            return
        self.claves[proveedor] = nueva.strip()
        registro.proteger(self.claves[proveedor])
        from .ia import gemini as mod_gemini
        mod_gemini.olvidar_clientes()

        guardar = messagebox.askyesno(
            "Guardar la clave",
            f"¿Guardar la clave de {proveedor} en "
            f"{rutas.ARCHIVO_CREDENCIALES}?\n\n"
            "Se escribe con permisos restringidos y fuera del repositorio, "
            "así no hace falta reescribirla en cada arranque.\n"
            "Si eliges No, se usará solo durante esta ejecución.",
            parent=self.raiz,
        )
        self.raiz.focus_force()
        if guardar and credenciales.guardar(self.claves[proveedor], proveedor):
            self.detalle = f"Clave de {proveedor} guardada en esta máquina."
        else:
            self.detalle = f"Clave de {proveedor} solo para esta ejecución."
        self.aviso_persistente = ""

    def _mostrar_diagnostico(self) -> None:
        messagebox.showinfo("Diagnóstico", "\n".join(self._lineas_diagnostico()),
                            parent=self.raiz)
        self.raiz.focus_force()

    def _lineas_diagnostico(self) -> list[str]:
        """Huellas de las claves, nunca las claves completas."""
        return [
            f"Voz: {self.voz.nombre} ({self.voz.frecuencia} Hz)",
            f"Reconocimiento: {self.stt.nombre}",
            f"Inteligencia: {self.orquestador.estado_corto()}",
            "Claves: " + (", ".join(
                f"{n}={credenciales.huella(self._clave_de(n))}"
                for n in sorted({"gemini", *(
                    e.clave for e in self.orquestador.endpoints.values()
                    if e.clave)})
            ) or "ninguna"),
            "Pendientes: " + (", ".join(self.orquestador.claves_pendientes())
                              or "ninguna"),
            f"Motor de audio: {self.microfono.motor()}",
            f"Micrófono: {'sí' if self.microfono.disponible() else 'no'}",
            f"Altavoz: {'sí' if self.altavoz.disponible() else 'no'}",
            f"Memoria de sesión: {len(self.gestor.memoria)} turnos",
            f"Recursos de crisis verificados: "
            f"{'sí' if self.guardia.recursos.verificado else 'NO'}",
        ]

    # ------------------------------------------------------------------- turnos
    def _pedir_turno(self, fijo: bool, continuo: bool = False) -> None:
        if self.ocupado:
            return
        if self.microfono_silenciado:
            self.detalle = "El micrófono está silenciado. Pulsa M."
            return
        if not self.microfono.disponible():
            self.cara.fijar_estado("error")
            self.detalle = self._consejo_sin_audio()
            return
        if not self.stt.disponible():
            self.cara.fijar_estado("sin_conexion")
            self.detalle = ("No puedo entender voz ahora mismo. Prueba las "
                            "actividades con 2 o 4.")
            return

        self._parar_voz()
        self.cancelar_turno.clear()
        self.ocupado = True
        if continuo and self._cadena is not None:
            self._cadena[0] += 1
        else:
            self._cadena = [0, time.monotonic()]
        self._turno_continuo = continuo
        if self.activacion is not None:
            self.activacion.pausar()       # el micrófono, para el turno
        self._ia_turno = (disp.DISPONIBLE, "")
        self._espera_hablada = False
        self.cara.fijar_estado("calibrando")
        self.detalle = "Preparando el micrófono…"
        self._turno_actual = threading.Thread(
            target=self._trabajar_turno, args=(fijo,),
            name="emotibot-turno", daemon=True,
        )
        self._turno_actual.start()

    def _trabajar_turno(self, fijo: bool) -> None:
        """Hilo de trabajo. Solo se comunica por la cola de eventos."""
        medicion = metricas.Medicion(
            modo_captura="fija" if fijo else "automatica"
        )
        try:
            if fijo:
                captura = self.microfono.grabar_fijo(self.cancelar_turno)
            else:
                captura = self.microfono.escuchar(
                    self.cancelar_turno,
                    al_cambiar_fase=lambda fase, texto: self.eventos.put(
                        ("fase", (fase, texto))
                    ),
                    al_nivel=lambda nivel: self.eventos.put(("nivel", nivel)),
                )

            medicion.t_captura = captura.duracion_bruta_s
            medicion.t_primera_voz = captura.t_primera_voz
            medicion.t_voz_util = captura.duracion_util_s
            medicion.bytes_audio = len(captura.pcm)
            medicion.marcar_ultima_voz(captura.instante_ultima_voz)

            if captura.motivo is MotivoFin.CANCELADO:
                medicion.resultado = "cancelado"
                self.eventos.put(("fin_turno", None))
                return
            if not captura.hay_voz or not captura.pcm:
                medicion.resultado = "sin_voz"
                self.eventos.put(("sin_voz", captura.detector))
                self.bitacora.anotar(medicion)
                return

            self.eventos.put(("estado", ("pensando", "Entendiendo lo que dijiste…")))
            transcripcion = self.stt.transcribir(captura.pcm, captura.frecuencia)
            medicion.t_stt = transcripcion.segundos

            if transcripcion.vacia:
                if self.depuracion.activa:
                    self.eventos.put(("depuracion_stt", ("", False)))
                medicion.resultado = "transcripcion_vacia"
                self.eventos.put(("sin_voz", captura.detector))
                self.bitacora.anotar(medicion)
                return

            # §14.4.1: «pensando la respuesta» NO se anuncia aquí. Lo anuncia el
            # orquestador justo antes de consultar a un modelo de verdad; con
            # la cuota agotada o el plazo vencido no llega a anunciarse.
            resultado = self.gestor.procesar(transcripcion.texto)
            medicion.proveedor = resultado.proveedor
            medicion.modelo = resultado.modelo or (
                self.orquestador.remoto.modelo
                if resultado.proveedor == "remoto" else resultado.proveedor)
            # A2/A3: motivo de fin y tokens; números y etiquetas, sin texto.
            medicion.motivo_fin = resultado.motivo_fin
            medicion.recortada = resultado.recortada
            medicion.tokens_entrada = resultado.tokens_entrada
            medicion.tokens_salida = resultado.tokens_salida
            medicion.papel = resultado.papel
            medicion.palabras_respuesta = resultado.palabras
            # Medido por el proveedor, no estimado restando tramos.
            medicion.t_ia = resultado.segundos_proveedor
            # B2: el texto viaja por la cola solo si la depuración está activa,
            # y nunca se registra. La pantalla decide si lo muestra.
            if self.depuracion.activa:
                es_seguridad = resultado.tipo is Tipo.SEGURIDAD
                # En la ruta de seguridad el texto ni siquiera entra en la
                # cola: solo la orden de borrar la pantalla.
                self.eventos.put(("depuracion_stt", (
                    "" if es_seguridad else transcripcion.texto, es_seguridad)))
            self.eventos.put(("respuesta", (resultado, medicion)))

        except ErrorCaptura as exc:
            medicion.resultado = "error_audio"
            self.bitacora.anotar(medicion)
            self.eventos.put(("error", str(exc)))
        except mod_stt.ErrorStt as exc:
            medicion.resultado = "error_stt"
            self.bitacora.anotar(medicion)
            self.eventos.put(("error", f"No pude entender el audio: {exc}"))
        except Exception as exc:  # nunca debe tumbar la interfaz
            log.error("Fallo inesperado en el turno: %s",
                      registro.resumen_excepcion(exc), exc_info=True)
            medicion.resultado = "error"
            self.bitacora.anotar(medicion)
            self.eventos.put(("error", "Algo falló por dentro. Mira la terminal."))

    # ------------------------------------------------------------------ hablar
    def _frases_de(self, texto: str, medicion: metricas.Medicion | None) -> Iterator[bytes]:
        """Genera PCM frase a frase, midiendo el tiempo hasta la primera.

        Se consume en el hilo del altavoz: la frase 1 suena mientras la 2 se
        sintetiza. Si el motor falla en una frase concreta, se cambia al
        respaldo solo para esa frase, sin repetir lo ya dicho.
        """
        inicio = time.monotonic()
        primera = True
        for frase in mod_voz.partir_en_frases(texto):
            pcm = self._sintetizar_frase(frase)
            if not pcm:
                continue
            if primera:
                primera = False
                if medicion is not None:
                    medicion.t_sintesis = time.monotonic() - inicio
            yield pcm

    def _sintetizar_frase(self, frase: str) -> bytes:
        try:
            return b"".join(self.voz.sintetizar(frase))
        except Exception as exc:
            log.warning("El motor de voz %s falló: %s", self.voz.nombre, exc)
            respaldo = self._obtener_respaldo()
            if respaldo is None:
                return b""
            try:
                datos = b"".join(respaldo.sintetizar(frase))
            except Exception as exc2:
                log.error("El respaldo de voz también falló: %s", exc2)
                return b""
            # A partir de aquí se usa el respaldo para no repetir el fallo.
            self.voz = respaldo
            # Solo el aviso: la cara que corresponde a lo que se dice se
            # conserva (antes esto la cambiaba a «hablando» y borraba la
            # emoción a mitad de frase).
            self.eventos.put(("detalle", "Uso la voz de respaldo."))
            return datos

    def _obtener_respaldo(self):
        if self.voz_respaldo is None:
            from .voz.espeak import ErrorEspeak, VozEspeak
            try:
                self.voz_respaldo = VozEspeak(
                    self.config.voz.velocidad_espeak,
                    self.config.voz.max_caracteres,
                )
            except ErrorEspeak:
                self.voz_respaldo = False
        return self.voz_respaldo or None

    def _decir_resultado(self, resultado) -> None:
        """Pronuncia un resultado del gestor y encadena lo que corresponda."""
        if resultado is None or not resultado.texto:
            self._liberar()
            return

        # §14.4.1: si solo quedó lo local, se DICE antes de la respuesta, con
        # una frase fija, y se habla con la cara de no disponible. Nunca en la
        # ruta de seguridad, que no pasa por los modelos.
        estado_ia, causa_ia = self._ia_turno
        if (estado_ia == disp.NO_DISPONIBLE and resultado.proveedor == "guion"
                and resultado.tipo is not Tipo.SEGURIDAD):
            resultado = dataclasses.replace(
                resultado, estado_rostro="no_disponible",
                texto=f"{disp.FRASES_HABLADAS[causa_ia]} {resultado.texto}")

        # Fase 1, A1: se habla CON la expresión del resultado. El estado
        # funcional «hablando» deja que la envolvente real del audio abra la
        # boca; la expresión (feliz, preocupada, respirando…) pone el resto.
        self.cara.fijar(funcional="hablando", expresion=resultado.estado_rostro)
        if getattr(resultado, "abrir_configuracion", False):
            # «Abre configuración», por voz: se abre al terminar de decirlo.
            self._abrir_config_tras_hablar = True
        if getattr(resultado, "mostrar_directorio", False):
            self.panel_directorio.mostrar(SEGUNDOS_SI_SE_PIDE_HABLANDO, time.monotonic())
        if self.detalle in (disp.TEXTO_PROCESANDO, disp.TEXTO_ESPERANDO):
            # PROCESANDO/ESPERANDO acabaron: su texto no se queda debajo de
            # «HABLANDO» (§14.4.1, nunca dos estados a la vez).
            self.detalle = ""
        self.detalle = resultado.aviso or self.detalle
        if resultado.aviso:
            self.aviso_persistente = resultado.aviso

        medicion = self._medicion
        es_actividad = resultado.tipo is Tipo.ACTIVIDAD
        espera = resultado.espera_s
        escuchar = resultado.escuchar_despues

        def al_primer_sonido() -> None:
            if medicion is not None:
                medicion.registrar_primer_sonido()
            self.eventos.put(("sonando", resultado.estado_rostro))

        def al_terminar(completo: bool) -> None:
            if medicion is not None and completo:
                medicion.cerrar()
                self.eventos.put(("anotar", medicion))
            self.eventos.put((
                "fin_habla",
                {"actividad": es_actividad, "espera": espera,
                 "escuchar": escuchar, "completo": completo,
                 "seguridad": resultado.tipo is Tipo.SEGURIDAD,
                 "fin": getattr(resultado, "fin_conversacion", False)},
            ))

        self.ocupado = True
        self.altavoz.hablar(
            self._frases_de(resultado.texto, medicion),
            self.voz.frecuencia,
            al_primer_sonido=al_primer_sonido,
            al_terminar=al_terminar,
        )

    def _parar_voz(self) -> None:
        self.altavoz.detener()
        self.cancelar_turno.set()
        self._liberar()

    def _liberar(self) -> None:
        self._fin_habla = time.monotonic()
        self.ocupado = False
        if self._abrir_config_tras_hablar:
            self._abrir_config_tras_hablar = False
            self.raiz.after(10, self._abrir_configuracion)
        if self._voz_pendiente is not None:
            voz, self._voz_pendiente = self._voz_pendiente, None
            self._cambiar_voz(voz)
        self._medicion = None
        if (self.cara.funcional, self.cara.estado) != ("sin_conexion",
                                                       "sin_conexion"):
            if self.gestor.en_malestar:
                self.cara.fijar(funcional="reposo", expresion="acompanando")
            else:
                self.cara.fijar_estado("reposo")
        self.cara.fijar_nivel_voz(0.0)
        self.cara.fijar_nivel_escucha(0.0)
        self._reflejar_disponibilidad()

    # ------------------------------------------------- estados honestos §14.4.1
    def _estado_ia(self, estado: str, causa: str, segundos: float) -> None:
        """Lo que anuncia el orquestador, en la cara (con y sin carcasa) y,
        con carcasa, en un texto fijo."""
        self._ia_turno = (estado, causa)
        if estado == disp.PROCESANDO:
            self.cara.fijar_estado("pensando")
            self.detalle = disp.TEXTO_PROCESANDO
        elif estado == disp.ESPERANDO:
            self.cara.fijar_estado("esperando")
            self.detalle = disp.TEXTO_ESPERANDO
            if segundos > disp.SEGUNDOS_PARA_HABLAR_ESPERA:
                # Solo visual, salvo que se alargue.
                self.raiz.after(int(disp.SEGUNDOS_PARA_HABLAR_ESPERA * 1000),
                                self._hablar_espera)
        elif estado == disp.NO_DISPONIBLE:
            self.cara.fijar_estado("no_disponible")
            self.detalle = disp.TEXTOS_PANTALLA[causa]

    def _hablar_espera(self) -> None:
        """La espera se alarga: se dice UNA vez por turno."""
        if self._ia_turno[0] != disp.ESPERANDO or self._espera_hablada or self.cerrando:
            return
        self._espera_hablada = True
        self.altavoz.hablar(self._frases_de(disp.FRASE_ESPERA, None), self.voz.frecuencia)

    def _reflejar_disponibilidad(self) -> None:
        """En reposo, la cara dice cómo está la inteligencia: sin cuota no se
        queda en «pensando» ni en reposo como si nada. La red y el plazo solo
        se saben probando: su aviso dura hasta el turno siguiente."""
        if self.ocupado or self.asistente is not None or self.cerrando:
            return
        estado_turno, causa_turno = self._ia_turno
        if estado_turno == disp.NO_DISPONIBLE and causa_turno in (disp.PLAZO,
                                                                  disp.CONEXION):
            estado, causa = estado_turno, causa_turno
        else:
            estado, causa, _ = self.orquestador.disponibilidad()
        if estado == disp.ESPERANDO:
            self.cara.fijar_estado("esperando")
            self.detalle = disp.TEXTO_ESPERANDO
        elif estado == disp.NO_DISPONIBLE:
            self.cara.fijar_estado("no_disponible")
            self.detalle = disp.TEXTOS_PANTALLA[causa]
        elif self.cara.funcional in ("esperando", "no_disponible"):
            self.cara.fijar_estado("reposo")
            self.detalle = "Pulsa ESPACIO y háblame."

    def _vigilar_disponibilidad(self) -> None:
        """Cada 2 s, en reposo: si volvió (el límite por minuto pasa solo), la
        cara deja de decir que espera."""
        if self.cerrando:
            return
        if self.cara.funcional in ("esperando", "no_disponible"):
            self._reflejar_disponibilidad()
        self.raiz.after(2000, self._vigilar_disponibilidad)

    # -------------------------------------------------------------- actividades
    def _lanzar_actividad(self, nombre: str) -> None:
        if self.ocupado:
            return
        self._medicion = None
        self._decir_resultado(self.gestor.iniciar_actividad(nombre))

    def _cancelar_actividad(self) -> None:
        resultado = self.gestor.cancelar_actividad()
        if resultado is not None:
            self._medicion = None
            self._decir_resultado(resultado)
        else:
            self.detalle = "Pulsa ESPACIO y háblame."
            self.cara.fijar_estado("reposo")

    def _continuar_actividad(self) -> None:
        resultado = self.gestor.continuar_actividad()
        if resultado is None:
            self._liberar()
            self.detalle = "Pulsa ESPACIO y háblame."
            return
        self._medicion = None
        self._decir_resultado(resultado)

    # ------------------------------------------------------------------ eventos
    def _bombear_eventos(self) -> None:
        if self.cerrando:
            return
        while True:
            try:
                tipo, valor = self.eventos.get_nowait()
            except queue.Empty:
                break
            self._atender(tipo, valor)
        self.raiz.after(40, self._bombear_eventos)

    def _atender(self, tipo: str, valor: object) -> None:
        if tipo == "fase":
            fase, texto = valor  # type: ignore[misc]
            self.detalle = texto
            if fase in (Fase.ASENTANDO, Fase.CALIBRANDO):
                self.cara.fijar_estado("calibrando")
            elif self.gestor.en_malestar:
                # Sigue contando algo que le pesa: escucha sin sonreír.
                self.cara.fijar(funcional="escuchando", expresion="escucha_atenta")
            else:
                self.cara.fijar_estado("escuchando")
        elif tipo == "nivel":
            self.cara.fijar_nivel_escucha(float(valor))  # type: ignore[arg-type]
        elif tipo == "estado":
            estado, texto = valor  # type: ignore[misc]
            self.cara.fijar_estado(estado)
            self.detalle = texto
        elif tipo == "sonando":
            self.cara.fijar(funcional="hablando", expresion=str(valor))
        elif tipo == "detalle":
            self.detalle = str(valor)
        elif tipo == "depuracion_stt":
            texto, es_seguridad = valor  # type: ignore[misc]
            self.depuracion.mostrar(texto, es_seguridad)
        elif tipo == "respuesta":
            resultado, medicion = valor  # type: ignore[misc]
            self._medicion = medicion
            self._decir_resultado(resultado)
        elif tipo == "sin_voz":
            if self._turno_continuo:
                # Nadie siguió hablando: a reposo, y ahora sí hace falta la
                # frase de activación (o ESPACIO).
                self._cadena, self._turno_continuo = None, False
                self._liberar()
                self.detalle = FIN_CONVERSACION
            else:
                self._explicar_sin_voz(valor)
        elif tipo == "error":
            self.cara.fijar_estado("error")
            self.detalle = str(valor)
            self.ocupado = False
        elif tipo == "anotar":
            self.bitacora.anotar(valor)  # type: ignore[arg-type]
            self.metricas_ultimas = valor.resumen_corto()  # type: ignore[union-attr]
        elif tipo == "fin_habla":
            self._tras_hablar(valor)  # type: ignore[arg-type]
        elif tipo == "fin_turno":
            self._liberar()
        elif tipo == "ia":
            self._estado_ia(*valor)  # type: ignore[misc]
        elif tipo == "prueba_audio":
            if self.menu_config is not None and self.menu_config.pagina == conf.TEXTO:
                self.menu_config.texto = ("Prueba de audio", tuple(valor))  # type: ignore[arg-type]
        elif tipo == "fin_prueba_audio":
            self.ocupado = False
            self._fin_habla = time.monotonic()
        elif tipo == "activacion":
            if self._puede_escuchar_activacion():
                self._saludar_y_escuchar(str(valor or "hola"))
        elif tipo == "fin_saludo":
            # Calló el saludo: a escuchar, con margen para no oírse (eco).
            self.ocupado = False
            self._fin_habla = time.monotonic()
            self.raiz.after(int(MARGEN_CONVERSACION_S * 1000),
                            lambda: self._pedir_turno(fijo=False))
        elif tipo == "voz_muestra":
            nombre, voz = valor  # type: ignore[misc]
            self._cargando_muestra.discard(nombre)
            if self.asistente is None:
                self._cerrar_componente(voz)        # llegó tarde: ya no hace falta
            else:
                self._muestras[nombre] = voz
                self._decir_muestra(nombre)
        elif tipo == "fin_muestra":
            if self.asistente is not None:
                self.cara.fijar_estado("reposo")
        elif tipo == "voz_nueva":
            self._cambiar_voz(valor)
            if self.detalle.endswith("Cargando la voz nueva…"):
                self.detalle = "Perfil listo. Voz nueva cargada."

    def _explicar_sin_voz(self, detector) -> None:
        """Mensaje honesto: distingue 'no te oí' de 'el umbral quedó raro'."""
        # El micrófono ya se cerró: el piloto se apaga. La cara dice «no te
        # oí» con un «?»: sin carcasa no hay texto y es la única señal.
        self.cara.fijar(funcional="reposo", expresion="sin_entender")
        self.ocupado = False
        base = "No llegué a oírte."
        if detector is not None and getattr(detector, "diagnostico", None):
            diag = detector.diagnostico
            if diag.calibracion_contaminada:
                base = ("Creo que empezaste a hablar mientras medía el ruido. "
                        "Espera a que te avise y prueba otra vez.")
            elif diag.rms_maximo_observado < diag.umbral_inicio * 0.6:
                base = ("Te oigo muy bajo. Prueba acercarte, o revisa la "
                        "ganancia con el diagnóstico de audio.")
        self.detalle = f"{base} También puedes usar F para grabación fija."

    def _tras_hablar(self, datos: dict) -> None:
        self.cara.fijar_nivel_voz(0.0)
        # Terminó de sonar: deja de hablar, pero conserva la expresión (la
        # pausa de una respiración se ve con su cara, no con la de reposo).
        self.cara.fijar_funcional("reposo")
        if datos.get("seguridad"):
            # Tras la ruta de seguridad no se encadena nada: ni actividad, ni
            # nueva escucha automática. La persona decide el siguiente paso.
            self.ocupado = False
            self.cara.fijar(funcional="reposo", expresion="preocupado")
            self.detalle = "Estoy aquí. Pulsa ESPACIO si quieres hablar."
            return
        if not datos.get("completo"):
            self._liberar()
            return
        if datos.get("escuchar"):
            self.ocupado = False
            self.raiz.after(250, lambda: self._pedir_turno(fijo=False))
            return
        if datos.get("actividad") and self.gestor.actividad is not None:
            # La escala de la respiración (crecer, mantener, menguar) se mide
            # desde aquí: coincide con la pausa contada, no con la frase.
            self.cara.reiniciar_rampa()
            espera = max(0.0, float(datos.get("espera", 0.0)))
            self.raiz.after(int(espera * 1000) + 60, self._continuar_actividad)
            return
        seguir = self._seguir_conversacion(datos)
        self._liberar()
        if seguir:
            # Conversación seguida: el micrófono se reabre solo, con margen
            # para que el altavoz haya callado del todo (sin eco).
            self.detalle = "Te sigo escuchando…"
            self.raiz.after(int(MARGEN_CONVERSACION_S * 1000), self._escuchar_de_nuevo)
            return
        self._cadena = None
        self.detalle = "Pulsa ESPACIO y háblame."

    def _seguir_conversacion(self, datos: dict) -> bool:
        """¿Se reabre el micrófono solo? Nunca tras la ruta de seguridad (sale
        antes), tras una despedida, sin inteligencia disponible ni pasado el
        tope de turnos o de tiempo: así una conversación de fondo no se come
        la cuota del día."""
        dialogo = self.config.dialogo
        if not dialogo.conversacion_continua or datos.get("fin") or self._cadena is None:
            return False
        if self._ia_turno[0] == disp.NO_DISPONIBLE:
            return False
        turnos, inicio = self._cadena
        return (turnos + 1 < dialogo.turnos_seguidos_max
                and time.monotonic() - inicio < MAX_SEGUNDOS_CONVERSACION)

    def _escuchar_de_nuevo(self) -> None:
        if (self.ocupado or self.cerrando or self.asistente is not None
                or self.menu_config is not None or self.microfono_silenciado
                or self.altavoz.hablando() or self._cadena is None):
            self._cadena = None
            return
        self._pedir_turno(fijo=False, continuo=True)

    # ------------------------------------------------------------------ pintado
    def _pintar(self) -> None:
        if self.cerrando:
            return
        self.cara.fijar_nivel_voz(self.altavoz.nivel())
        if self.menu_config is not None:
            # La pantalla de configuración tapa la cara: no se anima debajo.
            self.vista_config.dibujar(self.menu_config, max(self.lienzo.winfo_width(), 320),
                                      max(self.lienzo.winfo_height(), 240), self.paleta,
                                      self._info_config)
        else:
            self.cara.dibujar()
            if self.asistente is not None:
                self._pintar_asistente()
            else:
                self._pintar_textos()
        self._colocar_boton_menu()
        alto = max(self.lienzo.winfo_height(), 240)
        # La barra ocupa la franja del rostro: así nunca pisa los textos.
        self.panel_directorio.actualizar(
            max(self.lienzo.winfo_width(), 320), alto, time.monotonic(),
            franja=self.cara.limites_verticales() or (alto * 0.03, alto * 0.97))
        self.raiz.after(max(16, int(1000 / max(10, self.config.rostro.fps))),
                        self._pintar)

    def _pintar_asistente(self) -> None:
        ancho = max(self.lienzo.winfo_width(), 320)
        alto = max(self.lienzo.winfo_height(), 240)
        arriba, abajo = self.cara.reserva_vertical or RESERVA_ASISTENTE
        franja = self.cara.limites_verticales() or (alto * arriba, alto * (1 - abajo))
        self.vista_asistente.dibujar(self.asistente, ancho, alto, franja, self.paleta,
                                     self.identidad.nombre, self._nota_asistente)

    def _pintar_textos(self) -> None:
        lienzo = self.lienzo
        ancho = max(lienzo.winfo_width(), 320)
        alto = max(lienzo.winfo_height(), 240)

        # El aviso de micrófono abierto sale del estado funcional, nunca de
        # la expresión: así no se enciende mientras el robot habla.
        escuchando = self.cara.microfono_abierto
        rostro = self.config.rostro
        visibles = textos_visibles(rostro.carcasa, self.depuracion.activa,
                                   rostro.mostrar_metricas,
                                   rostro.mostrar_controles)
        privacidad = ""
        if escuchando:
            privacidad = "● micrófono abierto"
        elif self.microfono_silenciado:
            privacidad = "○ micrófono silenciado"
        elif self.activacion is not None and not self.ocupado:
            privacidad = "◌ micrófono abierto solo para «Hola Emoti» (no sale del equipo)"
        p = self.paleta
        todos = {
            "nombre": (self.identidad.nombre, p.tinta),
            "creador": (f"creado por {self.identidad.creador}", p.tenue),
            "estado": (self.cara.etiqueta(), p.ojos_atento if escuchando else p.tenue),
            "detalle": (self.detalle[:160], p.tinta),
            "depuracion": (self.depuracion.linea(), p.ojos_atento),
            "privacidad": (privacidad, p.ojos_atento if escuchando else p.tenue),
            "metricas": (" · ".join(x for x in (self.metricas_ultimas,
                                                 self.aviso_persistente) if x)[:150],
                         p.tenue),
            "controles": (AYUDA, p.tenue),
        }
        contenidos = {k: v for k, v in todos.items() if k in visibles}
        # Solo se recoloca cuando cambia algo: medir cuesta más que dibujar.
        firma = (ancho, alto, rostro.carcasa, tuple(sorted(contenidos.items())))
        if firma == self._firma_textos:
            return
        self._firma_textos = firma
        disposicion_textos.colocar(lienzo, self._textos, contenidos, ancho, alto,
                                   self.cara.limites_verticales())

    # -------------------------------------------------------------------- vida
    def ejecutar(self) -> None:
        self._bombear_eventos()
        self._pintar()
        self._vigilar_disponibilidad()
        try:
            self.raiz.mainloop()
        finally:
            self._apagar()

    def salir(self) -> None:
        if self.cerrando:
            return
        self.cerrando = True
        self.cancelar_turno.set()
        try:
            self.raiz.destroy()
        except tk.TclError:
            pass

    def _apagar(self) -> None:
        """Cierre ordenado: nada de procesos de audio huérfanos."""
        self.cancelar_turno.set()
        if self.activacion is not None:
            self.activacion.detener()
        try:
            self.altavoz.cerrar()
        except Exception:
            pass
        for componente in (self.voz, self.voz_respaldo, self.stt):
            if componente and hasattr(componente, "cerrar"):
                try:
                    componente.cerrar()
                except Exception:
                    pass
        self.gestor.cerrar()
        self.claves.clear()
        registro.olvidar_secretos()
        log.info("EMOTI-BOT cerrado. Memoria de sesión y clave borradas.")


TEXTOS = ("nombre", "creador", "estado", "detalle", "depuracion",
          "privacidad", "metricas", "controles")

def textos_visibles(carcasa: bool, depuracion_activa: bool,
                    mostrar_metricas: bool, mostrar_controles: bool) -> set[str]:
    """Qué textos de la aplicación se ven.

    Sin carcasa la cara ocupa la ventana entera y no se escribe nada encima:
    el estado lo dicen la expresión y las barras del micrófono, que son el
    indicador de captura y aparecen siempre que se escucha. La
    única excepción es la depuración de la transcripción (tecla T): mientras
    está activa tiene que VERSE que lo está.
    """
    if not carcasa:
        return {"depuracion"} if depuracion_activa else set()
    visibles = {"nombre", "creador", "estado", "detalle", "depuracion",
                "privacidad"}
    if mostrar_metricas:
        visibles.add("metricas")
    if mostrar_controles:
        visibles.add("controles")
    return visibles


def main() -> int:
    registro.configurar()
    try:
        Aplicacion().ejecutar()
    except tk.TclError as exc:
        log.error("No pude abrir la interfaz gráfica: %s", exc)
        log.error("¿Hay entorno gráfico disponible? Prueba con DISPLAY=:0")
        return 2
    except KeyboardInterrupt:
        log.info("Interrumpido por el usuario.")
    return 0
