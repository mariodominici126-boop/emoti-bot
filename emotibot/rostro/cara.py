"""El rostro de EMOTI-BOT: rasgos sobre una pantalla, con o sin cabeza.

Con CARCASA (por defecto, para desarrollar en el portátil): una cabeza de
robot —rectángulo redondeado claro— con una pantalla oscura dentro, dos
orejas en cápsula y los rasgos en la pantalla.

SIN CARCASA (`rostro.carcasa = false`): solo ojos, cejas, boca y las barras
del micrófono sobre el fondo. En el robot físico la pantalla va montada
dentro del cuerpo, y dibujar una cabeza en ella sería una cabeza dentro de
otra.

Área de rostro
--------------
Los rasgos no se calculan sobre la cabeza sino sobre un ÁREA DE ROSTRO:

- con carcasa, el rectángulo de la pantalla;
- sin carcasa, la ventana entera (la aplicación oculta entonces sus textos:
  un robot físico no necesita su nombre escrito en la cara, y su estado ya lo
  dicen las barras del micrófono y la expresión).

Sobre esa área se define una «cabeza equivalente» y de ella salen las
proporciones (las del prototipo Hybrid Balanced). Con carcasa coincide con
la cabeza real. Sin carcasa la cara ocupa la pantalla: crece en vertical
hasta llenar el alto y, en horizontal, los ojos se separan hasta llenar el
ancho y crecen también a lo ancho (como mucho ×1,15 más que en vertical,
para que no se deformen).

Qué hace que se vea vivo
------------------------
- Parpadeo con curva de aceleración, no un salto, y parpadeos dobles de vez
  en cuando, como los de verdad.
- Pupilas con micro-movimientos y deriva suave hacia un punto de atención
  distinto en cada estado.
- Ojos en arco «^ ^» para las expresiones alegres: un ojo aplastado solo
  parece un ojo medio cerrado.
- La cara entera se inclina y respira, y en la respiración guiada crece y
  mengua con dirección (ver estados.py).
- Destellos dibujados cuando está contento.

Qué hace que diga la verdad
---------------------------
- La boca se mueve con la ENVOLVENTE REAL del audio que está sonando, tomada
  del altavoz, no con un seno. Cuando la voz calla, la boca se cierra.
- Hay un estado propio CALIBRANDO, visualmente distinto, porque el error más
  dañino del prototipo era pedir "habla ahora" mientras aún medía el ruido.
- Las BARRAS DEL MICRÓFONO son el indicador de captación, un elemento propio
  bajo la cabeza (sin carcasa, abajo del todo). Tres casos, y solo tres:
    · micrófono cerrado          → no se dibuja nada;
    · micrófono abierto, silencio → todas a una altura MÍNIMA visible: se
      lee «estoy escuchando», no «apagado»;
    · micrófono abierto, voz      → la altura crece con el NIVEL REAL.
  La presencia significa micrófono abierto (estado funcional «escuchando»,
  A1); la altura, sonido real. Nada se inventa. Cuando el robot habla, lo
  que se mueve con el audio es la boca.

Sin reflejo en la pantalla
--------------------------
La banda de reflejo del prototipo Pillow funciona porque allí es un degradado
que se lee como luz. En Canvas era un rectángulo de borde duro que se leía
como una línea en la frente, en todos los estados. No hay forma de
suavizarlo sin degradados, así que el motor Tkinter no la dibuja.

Perfil
------
Ninguna proporción ni color está escrito aquí: todo sale de un perfil de
rostro (`config/rostro/<nombre>.json`, ver perfil.py). Una variante de diseño
es otro archivo de datos, no código.

Rendimiento
-----------
Las figuras se crean UNA vez y luego se actualizan con `coords()` e
`itemconfigure()`. Todo son polígonos, líneas y óvalos de Tkinter: nada
necesita suavizado de bordes, degradados ni transparencia (eso es el
prototipo Pillow, pendiente de medir en la Pi).
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field

from .estados import ESTADO_POR_DEFECTO, FUNCIONALES, Expresion, componer
from . import muebles
from .formas import arco, rectangulo_redondeado, rotar
from .paleta import Paleta, mezclar
from .perfil import PerfilRostro, cargar as cargar_perfil

_SUAVIZADO = 7.0
_PERIODO_BARRIDO = 2.6
_PERIODO_RESPIRACION = 4.6



# Grosor de boca de la GRAMÁTICA (el de hybrid_balanced): fija el umbral a
# partir del cual la boca se dibuja abierta, igual en todos los rostros.
_GROSOR_BOCA_GRAMATICA = 0.014


def _interpolar(actual: float, objetivo: float, delta: float) -> float:
    """Aproximación exponencial: suave y estable con fotogramas irregulares."""
    factor = 1.0 - math.exp(-_SUAVIZADO * max(0.0, delta))
    return actual + (objetivo - actual) * factor


@dataclass
class _Geometria:
    ancho: int = 0
    alto: int = 0
    escala: float = 1.0
    carcasa: bool = True
    # Cabeza real (solo con carcasa).
    centro_x: float = 0.0
    centro_y: float = 0.0
    cabeza_ancho: float = 0.0
    cabeza_alto: float = 0.0
    radio_cabeza: float = 0.0
    marco: float = 0.0
    oreja_ancho: float = 0.0
    # Mueble estático (tele, cápsula): no gira ni respira; `pie` es lo que
    # baja su zócalo por debajo del mueble (las barras van debajo).
    estatico: bool = False
    pie: float = 0.0
    # Área de rostro (x0, y0, x1, y1) y cabeza equivalente de los rasgos.
    area: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    rasgos_x: float = 0.0
    rasgos_y: float = 0.0
    ref_ancho: float = 0.0      # posiciones horizontales (separación)
    ref_alto: float = 0.0
    ref_rasgo: float = 0.0      # tamaños horizontales (ojos, boca)
    unidad: float = 1.0
    # Rasgos, ya en píxeles.
    sep_ojos: float = 0.0
    ojo_ancho: float = 0.0
    ojo_alto: float = 0.0
    y_ojos: float = 0.0
    y_ceja: float = 0.0
    y_boca: float = 0.0
    boca_ancho: float = 0.0


@dataclass
class _Animacion:
    apertura_ojos: float = 1.0
    curva_boca: float = 0.4
    apertura_boca: float = 0.0
    ceja_alto: float = 0.0
    ceja_angulo: float = 0.0
    vaiven: float = 0.0
    inclinacion: float = 0.0
    mirada_x: float = 0.0
    mirada_y: float = 0.0
    respira: float = 1.0
    parpadeo: float = 1.0
    nivel_voz: float = 0.0
    nivel_escucha: float = 0.0
    escala: float = 1.0
    color: str = ""
    destellos: float = 0.0
    anillo: float = 0.0
    deriva: tuple[float, float] = field(default=(0.0, 0.0))


class Cara:
    """Dibuja y anima el rostro sobre un `tkinter.Canvas`."""

    def __init__(self, lienzo, paleta: Paleta | None = None,
                 carcasa: bool = True, perfil: PerfilRostro | None = None) -> None:
        self.lienzo = lienzo
        # Proporciones y colores: del perfil. Una paleta explícita (código
        # anterior, prototipo) sustituye solo a los colores.
        self.perfil = perfil or cargar_perfil()
        self.paleta = paleta or self.perfil.colores
        self.carcasa = bool(carcasa)
        # Sin carcasa, franjas (arriba, abajo; fracciones del alto) que el
        # rostro deja libres para textos: solo el asistente de perfil las usa.
        self.reserva_vertical: tuple[float, float] | None = None
        # De la configuración: tamaño (1 = el de siempre; solo más pequeño),
        # animaciones (respiración, deriva y barrido de la mirada) y
        # parpadeo. Las barras del micrófono NO son animación: siempre están.
        self.tamano_rostro = 1.0
        self.animaciones = True
        self.parpadeo_activo = True
        # Dos ejes (Fase 1, A1): `funcional` es lo que el robot HACE —el que
        # decide la boca y el piloto del micrófono— y `estado` es la cara
        # que PONE. Se llama `estado` por compatibilidad con el código previo.
        self.funcional = ESTADO_POR_DEFECTO
        self.estado = ESTADO_POR_DEFECTO
        self._expresion: Expresion = componer(self.funcional, self.estado)
        self._anim = _Animacion(color=self.paleta.ojos)
        self._geo = _Geometria()
        self._items: dict[str, int] = {}
        self._destellos_items: list[int] = []
        self._barras_items: list[int] = []
        self._creado = False
        self._ultimo_t = time.monotonic()
        self._inicio = self._ultimo_t
        self._azar = random.Random()
        self._proximo_parpadeo = self._ultimo_t + self._azar.uniform(2.5, 5.0)
        self._fin_parpadeo = 0.0
        self._parpadeos_seguidos = 0
        self._proxima_saccada = self._ultimo_t + 1.0
        self._deriva_objetivo = (0.0, 0.0)
        # Rampa de escala: (valor inicial, objetivo, instante inicial, s).
        self._rampa = (1.0, 1.0, self._ultimo_t, 0.0)
        self._factor = 1.0
        self._centro_escala = (0.0, 0.0)
        self._barrido = 0.0
        # Niveles reales del micrófono de los últimos fotogramas, solo
        # mientras se escucha; se vacía al dejar de escuchar. Lo más
        # reciente va en la barra central y se desplaza hacia los lados.
        self._historial_escucha: list[float] = []

    # ------------------------------------------------------------------ entradas
    def reconfigurar(self, perfil: PerfilRostro | None = None,
                     carcasa: bool | None = None, reserva=False) -> None:
        """Cambia de perfil o de carcasa EN CALIENTE: en el siguiente
        fotograma se borra todo lo dibujado (mueble incluido) y se vuelve a
        crear. La expresión, el estado y la animación siguen donde estaban."""
        if perfil is not None:
            self.perfil = perfil
            self.paleta = perfil.colores
            self._anim.color = self.paleta.color_estado(self._expresion.color)
        if carcasa is not None:
            self.carcasa = bool(carcasa)
        if reserva is not False:              # None la quita
            self.reserva_vertical = reserva
        self._geo = _Geometria()
        self._limites_cache = None
        self._creado = False

    def fijar_estado(self, nombre: str) -> None:
        """Atajo compatible con el código anterior.

        Un nombre funcional («escuchando», «pensando», «reposo»…) fija los dos
        ejes a la vez, porque cada estado funcional trae su propia cara. Un
        nombre emocional («feliz», «preocupado»…) cambia solo la expresión y
        conserva lo que el robot está haciendo.
        """
        if nombre in FUNCIONALES:
            self.fijar(funcional=nombre, expresion=nombre)
        else:
            self.fijar(expresion=nombre)

    def fijar(self, funcional: str | None = None,
              expresion: str | None = None) -> None:
        """Fija el estado funcional, la expresión, o ambos."""
        nuevo_funcional = funcional if funcional is not None else self.funcional
        nueva_expresion = expresion if expresion is not None else self.estado
        if (nuevo_funcional == self.funcional
                and nueva_expresion == self.estado):
            return
        self.funcional = nuevo_funcional
        self.estado = nueva_expresion
        self._expresion = componer(nuevo_funcional, nueva_expresion)
        if self._rampa[1] != self._expresion.escala:
            self.reiniciar_rampa()

    def reiniciar_rampa(self, ahora: float | None = None) -> None:
        """Arranca (o vuelve a arrancar) la escala hacia su objetivo.

        La aplicación la reinicia al terminar de hablar un paso de actividad,
        para que los 4 s de inhalar o los 6 s de exhalar coincidan con la
        pausa contada y no con lo que tarda la frase.
        """
        ahora = time.monotonic() if ahora is None else ahora
        self._rampa = (self._anim.escala, self._expresion.escala, ahora,
                       max(0.0, self._expresion.segundos_escala))

    def fijar_funcional(self, nombre: str) -> None:
        self.fijar(funcional=nombre)

    @property
    def microfono_abierto(self) -> bool:
        """El indicador de captación, y solo él: estado funcional real."""
        from .estados import MICROFONO_ABIERTO
        return self.funcional in MICROFONO_ABIERTO

    def fijar_nivel_voz(self, nivel: float) -> None:
        self._anim.nivel_voz = max(0.0, min(1.0, nivel))

    def fijar_nivel_escucha(self, nivel: float) -> None:
        self._anim.nivel_escucha = max(0.0, min(1.0, nivel))

    def etiqueta(self) -> str:
        return self._expresion.etiqueta

    def asentar(self) -> None:
        """Lleva la animación a su destino sin esperar la interpolación.

        Para la vista previa y las pruebas: allí los fotogramas se generan en
        microsegundos, así que el suavizado —que depende del tiempo real
        transcurrido— apenas avanzaría y todos los estados se verían iguales.
        """
        objetivo, anim = self._expresion, self._anim
        anim.apertura_ojos = objetivo.apertura_ojos
        anim.curva_boca = objetivo.curva_boca
        anim.ceja_alto = objetivo.ceja_alto
        anim.ceja_angulo = objetivo.ceja_angulo
        anim.vaiven = objetivo.vaiven
        anim.inclinacion = objetivo.inclinacion
        anim.mirada_x, anim.mirada_y = objetivo.mirada
        anim.respira = objetivo.respira
        anim.destellos = 1.0 if objetivo.destellos else 0.0
        anim.anillo = 1.0 if objetivo.anillo_escucha else 0.0
        anim.color = self.paleta.color_estado(objetivo.color)
        anim.apertura_boca = max(objetivo.apertura_boca * anim.nivel_voz,
                                 objetivo.boca_reposo)
        anim.escala = objetivo.escala
        self._rampa = (anim.escala, anim.escala, time.monotonic(), 0.0)

    # ----------------------------------------------------------------- geometría
    def limites_verticales(self) -> tuple[float, float] | None:
        """(arriba, abajo): la franja vertical que puede llegar a ocupar el
        rostro con carcasa, en el peor caso de TODAS las expresiones.

        Cuenta la cabeza y las orejas con la inclinación máxima (más el
        vaivén de la respiración), el pulso y la escala de la respiración
        guiada, y las barras del micrófono a su altura máxima. Es fija para
        un tamaño de ventana, así que los textos de la aplicación no saltan
        cuando la cabeza se inclina o cuando aparecen las barras. Sin
        carcasa devuelve None: la cara ocupa la ventana entera.
        """
        from .estados import EXPRESIONES
        self._recalcular()
        if not self.carcasa:
            return None
        clave = (self._geo.ancho, self._geo.alto, id(self.perfil))
        cache = getattr(self, "_limites_cache", None)
        if cache and cache[0] == clave:
            return cache[1]
        geo, c, pb = self._geo, self.perfil.cabeza, self.perfil.barras
        if geo.estatico:
            # Mueble estático: no gira ni respira; su caja es la de sus
            # figuras (antenas y zócalo incluidos). Los rasgos van dentro.
            caja = muebles.extension(self._figuras_mueble())
            barras = (geo.centro_y + geo.cabeza_alto / 2 + geo.pie
                      + geo.unidad * pb.hueco + geo.unidad * pb.alto_maximo)
            limites = (caja.y0, max(caja.y1, barras))
            self._limites_cache = (clave, limites)
            return limites

        def mitad_de(expresion) -> float:
            theta = math.radians(abs(expresion.inclinacion) + 0.45)
            seno, coseno = abs(math.sin(theta)), math.cos(theta)
            pulso = 1.0 + 0.008 * expresion.respira

            def extension(dx, a, b, r):
                # Rectángulo redondeado de semilados (a, b) y radio r,
                # desplazado dx del centro de giro y girado theta.
                return dx * seno + (a - r) * seno + (b - r) * coseno + r

            hw, hh = geo.cabeza_ancho / 2 * pulso, geo.cabeza_alto / 2 * pulso
            cabeza = extension(0.0, hw, hh, geo.radio_cabeza * pulso)
            ow, oh = geo.oreja_ancho, geo.cabeza_alto * c.oreja_alto
            solape = c.oreja_solape
            oreja = extension(hw + ow * (1 - solape) / 2, ow * (1 + solape) / 2,
                              oh / 2, ow * 0.5)
            dy = geo.unidad * 0.007 * expresion.respira
            return max(cabeza, oreja) * max(1.0, expresion.escala) + dy

        mitad = max(mitad_de(e) for e in EXPRESIONES.values())
        maximo = geo.unidad * pb.alto_maximo
        barras = geo.centro_y + geo.cabeza_alto / 2 + geo.unidad * pb.hueco + maximo
        limites = (geo.centro_y - mitad, max(geo.centro_y + mitad, barras))
        self._limites_cache = (clave, limites)
        return limites

    def area_de_rostro(self) -> tuple[float, float, float, float]:
        """El rectángulo sobre el que se calculan los rasgos (x0, y0, x1, y1)."""
        return self._geo.area

    def _recalcular(self) -> bool:
        ancho = max(self.lienzo.winfo_width(), 320)
        alto = max(self.lienzo.winfo_height(), 240)
        if (ancho == self._geo.ancho and alto == self._geo.alto
                and self.carcasa == self._geo.carcasa):
            return False
        c, sc, r = self.perfil.cabeza, self.perfil.sin_carcasa, self.perfil.rasgos
        escala = min(ancho, alto)
        # Toda la cabeza (marco y orejas incluidos) a `tamano`; los rasgos
        # salen de ella y se reducen igual.
        tamano = c.tamano * self.tamano_rostro
        tam = escala * tamano
        cabeza_ancho = min(ancho * c.ancho_max_ventana,
                           escala * c.ancho_max_escala) * tamano
        cabeza_alto = min(alto * c.alto_max_ventana,
                          escala * c.alto_max_escala) * tamano
        # Cabeza y barras del micrófono forman UN bloque centrado en la
        # ventana (`centro_bloque_y`): la cabeza va por encima del centro lo
        # que ocupan el hueco y las barras, no colgando de arriba.
        pb = self.perfil.barras
        unidad_cabeza = cabeza_alto / c.alto_sobre_unidad
        centro_y = (alto * c.centro_bloque_y
                    - (pb.hueco + pb.alto_maximo) * unidad_cabeza / 2)
        marco = tam * c.marco

        m = self.perfil.mueble
        if self.carcasa and m.tipo != "cabeza":
            return self._recalcular_estatico(ancho, alto, escala, cabeza_alto)
        if self.carcasa:
            # Área de rostro = la pantalla dentro de la cabeza.
            area = (ancho / 2 - cabeza_ancho / 2 + marco, centro_y - cabeza_alto / 2 + marco,
                    ancho / 2 + cabeza_ancho / 2 - marco, centro_y + cabeza_alto / 2 - marco)
            area_w, area_h = area[2] - area[0], area[3] - area[1]
            ref_ancho = area_w / c.pantalla_sobre_cabeza_ancho
            ref_alto = area_h / c.pantalla_sobre_cabeza_alto
            ref_rasgo = ref_ancho
            rasgos_y = (area[1] + area[3]) / 2
        else:
            # Área de rostro = la ventana entera (la aplicación oculta sus
            # textos en este modo). En vertical, los rasgos llenan el alto;
            # en horizontal, los ojos se separan hasta llenar el ancho y
            # crecen a lo ancho, como mucho ×anisotropia.
            m = sc.margen
            arriba, abajo = self.reserva_vertical or (m, m)
            area = (ancho * m, alto * max(m, arriba), ancho * (1 - m),
                    alto * (1 - max(m, abajo)))
            if self.tamano_rostro < 1.0:
                # Más pequeño alrededor del centro del área.
                f, (x0, y0, x1, y1) = self.tamano_rostro, area
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                area = (cx - (cx - x0) * f, cy - (cy - y0) * f,
                        cx + (x1 - cx) * f, cy + (y1 - cy) * f)
            area_w, area_h = area[2] - area[0], area[3] - area[1]
            mitad = area_w / 2 / sc.escala_max
            ref_alto = area_h / sc.extension_v
            ref_rasgo = ref_alto * c.aspecto * sc.anisotropia
            ref_ancho = (mitad - sc.lado_rasgo * ref_rasgo) / r.separacion_ojos
            if ref_ancho < ref_rasgo:
                # Ventana estrecha: no sobra ancho para separar los ojos.
                ref_rasgo = ref_ancho = mitad / (r.separacion_ojos + sc.lado_rasgo)
                ref_alto = min(ref_alto, ref_rasgo / c.aspecto)
            rasgos_y = (area[1] + area[3]) / 2 - sc.centro_v * ref_alto
        rasgos_x = ancho / 2

        self._geo = _Geometria(
            ancho=ancho,
            alto=alto,
            escala=escala,
            carcasa=self.carcasa,
            centro_x=ancho / 2,
            centro_y=centro_y,
            cabeza_ancho=cabeza_ancho,
            cabeza_alto=cabeza_alto,
            radio_cabeza=cabeza_alto * c.radio,
            marco=marco,
            oreja_ancho=tam * c.oreja_ancho,
            area=area,
            rasgos_x=rasgos_x,
            rasgos_y=rasgos_y,
            ref_ancho=ref_ancho,
            ref_alto=ref_alto,
            ref_rasgo=ref_rasgo,
            unidad=ref_alto / c.alto_sobre_unidad,
            # Proporciones del perfil, sobre la cabeza equivalente del área.
            sep_ojos=ref_ancho * r.separacion_ojos,
            ojo_ancho=ref_rasgo * r.ojo_ancho,
            ojo_alto=ref_alto * r.ojo_alto,
            y_ojos=rasgos_y + ref_alto * r.y_ojos,
            y_ceja=rasgos_y + ref_alto * r.y_ceja,
            y_boca=rasgos_y + ref_alto * r.y_boca,
            boca_ancho=ref_rasgo * r.boca_ancho,
        )
        return True

    def _recalcular_estatico(self, ancho: int, alto: int, escala: float,
                             cabeza_alto: float) -> bool:
        """Mueble estático: la pantalla es la de la tele o la cápsula.

        Los rasgos se calculan sobre la pantalla con las MISMAS proporciones
        de rasgo que hybrid_balanced (cabeza equivalente isótropa), así la
        gramática no cambia con la forma de la pantalla. El bloque mueble +
        antenas + zócalo + barras se centra en la ventana.
        """
        c, r, m, pb = (self.perfil.cabeza, self.perfil.rasgos, self.perfil.mueble,
                       self.perfil.barras)
        alto_mueble = min(cabeza_alto, ancho * c.ancho_max_ventana / m.proporcion)
        ancho_mueble = alto_mueble * m.proporcion
        pant_w = (m.pantalla_x1 - m.pantalla_x0) * ancho_mueble
        pant_h = (m.pantalla_y1 - m.pantalla_y0) * alto_mueble
        ref_alto = pant_h / c.pantalla_sobre_cabeza_alto
        ref_rasgo = ref_alto * c.aspecto
        ref_ancho = pant_w / c.pantalla_sobre_cabeza_ancho
        unidad = ref_alto / c.alto_sobre_unidad
        centro_y = alto * c.centro_bloque_y - (
            m.zocalo * alto_mueble + (pb.hueco + pb.alto_maximo) * unidad
            - m.antena * alto_mueble) / 2
        caja = muebles.caja_mueble(ancho / 2, centro_y, alto_mueble, m)
        pant = muebles.caja_pantalla(caja, m)
        self._geo = _Geometria(
            ancho=ancho, alto=alto, escala=escala, carcasa=True,
            centro_x=ancho / 2, centro_y=centro_y,
            cabeza_ancho=ancho_mueble, cabeza_alto=alto_mueble,
            radio_cabeza=alto_mueble * m.radio, marco=0.0, oreja_ancho=0.0,
            estatico=True, pie=m.zocalo * alto_mueble,
            area=(pant.x0, pant.y0, pant.x1, pant.y1),
            rasgos_x=pant.cx, rasgos_y=pant.cy,
            ref_ancho=ref_ancho, ref_alto=ref_alto, ref_rasgo=ref_rasgo, unidad=unidad,
            sep_ojos=ref_ancho * r.separacion_ojos,
            ojo_ancho=ref_rasgo * r.ojo_ancho,
            ojo_alto=ref_alto * r.ojo_alto,
            y_ojos=pant.cy + ref_alto * r.y_ojos,
            y_ceja=pant.cy + ref_alto * r.y_ceja,
            y_boca=pant.cy + ref_alto * r.y_boca,
            boca_ancho=ref_rasgo * r.boca_ancho,
        )
        return True

    def _figuras_mueble(self) -> list[dict]:
        geo, m = self._geo, self.perfil.mueble
        caja = muebles.caja_mueble(geo.centro_x, geo.centro_y, geo.cabeza_alto, m)
        return muebles.figuras(m.tipo, caja, m, self.paleta)

    @property
    def _fondo_rasgos(self) -> str:
        """Color sobre el que van los rasgos: la pantalla o el fondo."""
        return self.paleta.pantalla if self.carcasa else self.paleta.fondo

    # --------------------------------------------------------------- construcción
    def _crear_items(self) -> None:
        lienzo, p = self.lienzo, self.paleta
        lienzo.delete("rostro")
        self._items.clear()
        self._destellos_items.clear()
        self._barras_items.clear()
        estatico = self._geo.estatico
        cabeza = "normal" if self.carcasa and not estatico else "hidden"
        pixeles = self.perfil.trazo.estilo == "pixeles"
        # El mueble estático, PRIMERO (detrás de todo) y UNA sola vez.
        self._mueble_items = (muebles.dibujar(lienzo, self._figuras_mueble())
                              if estatico else [])

        def nuevo(clave: str, item: int) -> None:
            self._items[clave] = item

        def poligono(**extra) -> int:
            return lienzo.create_polygon(
                [0, 0, 0, 0, 0, 0], tags="rostro", **extra
            )

        # Orejas primero: quedan detrás de la carcasa.
        for lado in ("izq", "der"):
            nuevo(f"oreja_{lado}", poligono(
                fill=p.carcasa_sombra, outline="", state=cabeza))

        nuevo("carcasa", poligono(fill=p.carcasa, outline="", state=cabeza))
        nuevo("pantalla", poligono(fill=p.pantalla, outline="", state=cabeza))

        # Cejas: cápsulas (polígonos), no líneas. Un rostro sin cejas las
        # tiene ocultas siempre (canal ausente, ver perfil.SinCejas).
        sin_cejas = {} if self.perfil.cejas is not None else {"state": "hidden"}
        for lado in ("izq", "der"):
            nuevo(f"ceja_{lado}", poligono(fill=p.ojos, outline="", **sin_cejas))

        for lado in ("izq", "der"):
            nuevo(f"ojo_{lado}", poligono(
                fill=self._fondo_rasgos, outline=p.ojos, width=4))
            if pixeles:
                # Píxeles: el brillo es un cuadrado; sin punto (como la tele).
                nuevo(f"brillo_{lado}", poligono(outline="", fill=p.brillo))
                nuevo(f"punto_{lado}", poligono(outline="", fill=p.ojos,
                                                 state="hidden"))
                nuevo(f"arco_{lado}", lienzo.create_line(
                    [0, 0, 0, 0, 0, 0], fill=p.ojos, width=6, capstyle="projecting",
                    joinstyle="miter", smooth=False, state="hidden", tags="rostro"))
                continue
            nuevo(f"brillo_{lado}", lienzo.create_oval(
                0, 0, 0, 0, outline="", fill=p.brillo, tags="rostro"))
            nuevo(f"punto_{lado}", lienzo.create_oval(
                0, 0, 0, 0, outline="", fill=p.ojos, tags="rostro"))
            nuevo(f"arco_{lado}", lienzo.create_line(
                [0, 0, 0, 0, 0, 0], fill=p.ojos, width=6, capstyle="round",
                joinstyle="round", smooth=True, state="hidden", tags="rostro"))
            if self.perfil.sin_cejas is not None:
                # El párpado de la preocupación sin ceja: encima del ojo.
                nuevo(f"parpado_{lado}", poligono(
                    fill=self._fondo_rasgos, outline="", state="hidden"))

        nuevo("boca", poligono(fill=p.ojos, outline=""))

        # Signo «!» / «?» (Expresion.signo): un trazo y un punto, dibujados.
        nuevo("signo_trazo", poligono(fill=p.ojos, outline="", state="hidden"))
        nuevo("signo_punto", poligono(fill=p.ojos, outline="", state="hidden"))
        # En rejilla de píxeles, el signo es un mapa de bits de celdas.
        self._celdas_signo = [lienzo.create_polygon(
            [0, 0, 0, 0, 0, 0], fill=p.ojos, outline="", state="hidden", tags="rostro")
            for _ in range(max("".join(m).count("#") for m in _SIGNOS_PIXELES.values()))]

        # Destellos dibujados (estrellas de cuatro puntas), no el carácter ✦.
        for _ in range(6):
            self._destellos_items.append(lienzo.create_polygon(
                [0, 0, 0, 0, 0, 0], fill=p.destello, outline="",
                state="hidden", tags="rostro"))

        # Barras del micrófono: ocultas salvo al escuchar de verdad. Cada
        # una es una línea vertical con extremos redondos —una cápsula con
        # 4 coordenadas, no un polígono de 40—, y su color (el degradado,
        # fijo para la paleta) se pone aquí una sola vez.
        pb = self.perfil.barras
        mitad = pb.numero // 2
        for i in range(pb.numero):
            self._barras_items.append(lienzo.create_line(
                0, 0, 0, 0, capstyle="round", state="hidden", tags="rostro",
                fill=mezclar(getattr(p, pb.color_centro), getattr(p, pb.color_extremos),
                             abs(i - mitad) / max(1, mitad))))
        self._barras_estado: tuple[bool, float] | None = None

        self._creado = True

    # ------------------------------------------------------------------- animar
    def _actualizar_parpadeo(self, ahora: float) -> None:
        if not self.parpadeo_activo:
            self._anim.parpadeo = 1.0
            self._fin_parpadeo = 0.0
            return
        if not self._expresion.parpadea:
            self._anim.parpadeo = _interpolar(self._anim.parpadeo, 1.0, 0.08)
            self._proximo_parpadeo = ahora + self._azar.uniform(2.0, 4.0)
            return

        if self._fin_parpadeo and ahora < self._fin_parpadeo:
            avance = 1.0 - max(0.0, (self._fin_parpadeo - ahora) / 0.13)
            self._anim.parpadeo = max(0.06, abs(math.cos(math.pi * avance)))
            return

        if self._fin_parpadeo:
            self._fin_parpadeo = 0.0
            self._anim.parpadeo = 1.0
            if self._parpadeos_seguidos > 0:
                self._parpadeos_seguidos -= 1
                self._proximo_parpadeo = ahora + 0.12
            else:
                self._proximo_parpadeo = ahora + self._azar.uniform(2.6, 6.0)
            return

        if ahora >= self._proximo_parpadeo:
            self._fin_parpadeo = ahora + 0.13
            if self._parpadeos_seguidos == 0 and self._azar.random() < 0.22:
                self._parpadeos_seguidos = 1   # parpadeo doble ocasional

    def _actualizar_mirada(self, ahora: float, delta: float) -> None:
        if not self.animaciones:
            self._anim.deriva = (0.0, 0.0)
            return
        if ahora >= self._proxima_saccada:
            self._proxima_saccada = ahora + self._azar.uniform(0.9, 2.8)
            self._deriva_objetivo = (self._azar.uniform(-0.12, 0.12),
                                     self._azar.uniform(-0.09, 0.09))
        dx = _interpolar(self._anim.deriva[0], self._deriva_objetivo[0], delta)
        dy = _interpolar(self._anim.deriva[1], self._deriva_objetivo[1], delta)
        self._anim.deriva = (dx, dy)

    def _acercar_a_expresion(self, delta: float) -> None:
        objetivo, anim = self._expresion, self._anim
        anim.apertura_ojos = _interpolar(anim.apertura_ojos,
                                         objetivo.apertura_ojos, delta)
        anim.curva_boca = _interpolar(anim.curva_boca, objetivo.curva_boca, delta)
        anim.ceja_alto = _interpolar(anim.ceja_alto, objetivo.ceja_alto, delta)
        anim.vaiven = _interpolar(anim.vaiven, objetivo.vaiven, delta)
        anim.ceja_angulo = _interpolar(anim.ceja_angulo, objetivo.ceja_angulo,
                                       delta)
        anim.inclinacion = _interpolar(anim.inclinacion, objetivo.inclinacion,
                                       delta)
        anim.mirada_x = _interpolar(anim.mirada_x, objetivo.mirada[0], delta)
        anim.mirada_y = _interpolar(anim.mirada_y, objetivo.mirada[1], delta)
        anim.respira = _interpolar(anim.respira, objetivo.respira, delta)
        anim.destellos = _interpolar(anim.destellos,
                                     1.0 if objetivo.destellos else 0.0, delta)
        anim.anillo = _interpolar(anim.anillo,
                                  1.0 if objetivo.anillo_escucha else 0.0, delta)
        anim.color = self.paleta.color_estado(objetivo.color)

        deseada = objetivo.apertura_boca * max(anim.nivel_voz, 0.0)
        if objetivo.apertura_boca > 0 and anim.nivel_voz <= 0.01:
            deseada = 0.0
        # Excepción justificada (solo fuera de «hablando», ver componer()).
        deseada = max(deseada, objetivo.boca_reposo)
        anim.apertura_boca = _interpolar(anim.apertura_boca, deseada, delta * 2.2)

    # ------------------------------------------------------------------ dibujar
    def dibujar(self) -> None:
        ahora = time.monotonic()
        delta = min(0.25, max(0.001, ahora - self._ultimo_t))
        self._ultimo_t = ahora

        if self._recalcular() or not self._creado:
            self._crear_items()

        self._actualizar_parpadeo(ahora)
        self._actualizar_mirada(ahora, delta)
        self._acercar_a_expresion(delta)
        self._actualizar_escala(ahora)

        geo, anim = self._geo, self._anim
        t = ahora - self._inicio
        respiracion = (math.sin(2 * math.pi * t / _PERIODO_RESPIRACION)
                       if self.animaciones else 0.0)
        dy = respiracion * geo.unidad * 0.007 * anim.respira
        pulso = 1.0 + respiracion * 0.008 * anim.respira
        inclinacion = anim.inclinacion + respiracion * 0.45
        # «Esperando»: la mirada barre de lado a lado, despacio (periodo
        # _PERIODO_BARRIDO). Con vaiven 0 es exactamente 0.
        self._barrido = (anim.vaiven * math.sin(2 * math.pi * t / _PERIODO_BARRIDO)
                         if anim.vaiven and self.animaciones else 0.0)
        centro = (geo.rasgos_x, geo.rasgos_y + dy)
        # Toda la cara se escala alrededor de su centro (ver _coords).
        self._factor = anim.escala
        self._centro_escala = centro

        if self.carcasa and not geo.estatico:
            self._dibujar_cabeza(geo, anim, (geo.centro_x, geo.centro_y + dy),
                                 inclinacion, pulso, dy)
        self._dibujar_ceja(geo, anim, centro, inclinacion, dy)
        self._dibujar_ojos(geo, anim, centro, inclinacion, dy)
        self._dibujar_boca(geo, anim, centro, inclinacion, dy)
        self._dibujar_signo(geo, anim, centro, inclinacion, dy)
        self._dibujar_destellos(geo, anim, centro, t)
        self._dibujar_barras(geo, anim)

    def _actualizar_escala(self, ahora: float) -> None:
        inicio, objetivo, t0, duracion = self._rampa
        if duracion <= 0:
            self._anim.escala = objetivo
            return
        avance = min(1.0, max(0.0, (ahora - t0) / duracion))
        suave = avance * avance * (3 - 2 * avance)     # entrada y salida suaves
        self._anim.escala = inicio + (objetivo - inicio) * suave

    # ---------------------------------------------------------------- píxeles
    def _escalar(self, planas) -> list[float]:
        """La escala de la cara (respiración guiada) sobre unas coordenadas."""
        factor = self._factor
        if abs(factor - 1.0) <= 1e-6:
            return list(planas)
        cx, cy = self._centro_escala
        return [(v - cx) * factor + cx if i % 2 == 0 else (v - cy) * factor + cy
                for i, v in enumerate(planas)]

    def _rejilla(self) -> tuple[float, float, float]:
        """(lado del píxel, origen x, origen y): la rejilla de la pantalla."""
        geo = self._geo
        lado = max(2.0, round(geo.ref_alto * self.perfil.trazo.pixel))
        return lado, geo.area[0], geo.area[1]

    def _coords_pixeles(self, item, planas, forma: str, celdas: int = 1,
                        curva: float = 0.0) -> None:
        """Coordenadas ya en la rejilla: `forma` es «contorno» (polígono
        cerrado en escalera), «trazo» (línea en escalera) o «banda» (una
        tira de `celdas` píxeles de grueso que sigue la curva)."""
        lado, ox, oy = self._rejilla()
        planas = self._escalar(planas)
        if forma == "banda":
            puntos = _banda_pixeles(planas, lado, ox, oy, celdas, curva)
        else:
            puntos = _escalera(planas, lado, ox, oy, cerrado=(forma == "contorno"))
        self.lienzo.coords(item, *puntos)

    def _coords(self, item, *valores) -> None:
        """`coords()` con la escala de la cara aplicada alrededor del centro.

        Un solo punto para todas las piezas: así funciona igual con Tkinter,
        con el lienzo de las pruebas y con la vista previa en SVG.
        """
        planas = valores[0] if len(valores) == 1 and isinstance(
            valores[0], (list, tuple)) else valores
        factor = self._factor
        if abs(factor - 1.0) > 1e-6:
            cx, cy = self._centro_escala
            planas = [(v - cx) * factor + cx if i % 2 == 0 else (v - cy) * factor + cy
                      for i, v in enumerate(planas)]
        self.lienzo.coords(item, *planas)

    # ------------------------------------------------------------------- piezas
    def _dibujar_cabeza(self, geo: _Geometria, anim: _Animacion,
                        centro: tuple[float, float], inclinacion: float,
                        pulso: float, dy: float) -> None:
        cx, cy = centro
        mitad_w = geo.cabeza_ancho / 2 * pulso
        mitad_h = geo.cabeza_alto / 2 * pulso

        # Orejas: cápsulas (radio = medio ancho) que asoman por los lados,
        # detrás de la carcasa.
        c = self.perfil.cabeza
        oreja_w = geo.oreja_ancho
        oreja_h = geo.cabeza_alto * c.oreja_alto
        for lado, signo in (("izq", -1), ("der", 1)):
            borde = cx + signo * mitad_w
            self._coords(self._items[f"oreja_{lado}"], *rectangulo_redondeado(
                borde - oreja_w * (c.oreja_solape if signo > 0 else 1.0),
                cy - oreja_h / 2,
                borde + oreja_w * (1.0 if signo > 0 else c.oreja_solape),
                cy + oreja_h / 2,
                oreja_w * 0.5, centro=(cx, cy), inclinacion=inclinacion,
            ))

        self._coords(self._items["carcasa"], *rectangulo_redondeado(
            cx - mitad_w, cy - mitad_h, cx + mitad_w, cy + mitad_h,
            geo.radio_cabeza * pulso, centro=(cx, cy), inclinacion=inclinacion,
        ))

        margen = geo.marco
        radio_pantalla = max(0.0, (geo.radio_cabeza - margen * 0.5)) * pulso
        self._coords(self._items["pantalla"], *rectangulo_redondeado(
            cx - mitad_w + margen, cy - mitad_h + margen,
            cx + mitad_w - margen, cy + mitad_h - margen,
            radio_pantalla, centro=(cx, cy), inclinacion=inclinacion,
        ))

        # Sin banda de reflejo: ver «Sin reflejo en la pantalla» arriba.

    def _dibujar_ceja(self, geo: _Geometria, anim: _Animacion,
                      centro: tuple[float, float], inclinacion: float,
                      dy: float) -> None:
        """Dos cejas en cápsula gruesa CON arco.

        Al portar la geometría del prototipo pasaron de arco fino a barra
        recta: se ganó grosor y se perdió forma, y en los estados neutros
        parecían dos guiones sueltos. Ahora son una cápsula que sigue la
        curva de `arco()` —el arco de antes, con su sesgo para la
        preocupación y la curiosidad— con el grosor nuevo y extremos
        redondos.
        """
        pc = self.perfil.cejas
        if pc is None:
            return
        cy = geo.y_ceja + dy - anim.ceja_alto * geo.ref_alto * pc.subida
        largo = geo.ojo_ancho * pc.largo
        grosor = max(3.0, geo.unidad * pc.grosor)
        altura = geo.ref_alto * pc.curva            # la curva del arco

        for lado, signo in (("izq", -1), ("der", 1)):
            ox = geo.rasgos_x + signo * geo.sep_ojos
            # El extremo interior sube o baja según el ángulo: hacia dentro y
            # arriba lee como preocupación; hacia dentro y abajo, curiosidad.
            angulo = anim.ceja_angulo * (pc.ceno if anim.ceja_angulo < 0 else 1.0)
            sesgo = math.tan(math.radians(angulo)) * largo * pc.giro * signo
            linea = arco(ox, cy, largo, altura, centro=centro,
                         inclinacion=inclinacion, sesgo=sesgo, puntos=10)
            if self.perfil.trazo.estilo == "pixeles":
                celdas = max(1, round(grosor / self._rejilla()[0]))
                self._coords_pixeles(self._items[f"ceja_{lado}"], linea, "banda", celdas)
            else:
                self._coords(self._items[f"ceja_{lado}"], *_capsula(linea, grosor))
            self.lienzo.itemconfigure(
                self._items[f"ceja_{lado}"],
                fill=mezclar(self._fondo_rasgos, anim.color, pc.intensidad),
            )

    def _dibujar_ojos(self, geo: _Geometria, anim: _Animacion,
                      centro: tuple[float, float], inclinacion: float,
                      dy: float) -> None:
        lienzo, po = self.lienzo, self.perfil.ojos
        cy = geo.y_ojos + dy
        alto = max(geo.unidad * po.alto_minimo,
                   geo.ojo_alto * anim.apertura_ojos * anim.parpadeo)
        ancho = geo.ojo_ancho
        if self.perfil.trazo.estilo == "redondo":
            # Ojo circular también sin carcasa, donde los rasgos se ensanchan.
            ancho = min(ancho, geo.ojo_alto)
        en_arco = (self._expresion.ojos_arco
                   and anim.apertura_ojos < self.perfil.alegria.umbral_apertura)
        ancho_base, alto_base = ancho, alto
        sc = self.perfil.sin_cejas
        preocupacion = curiosidad = 0.0
        hacia = 1.0
        if sc is not None:
            # Lo que diría la ceja, dicho con el ojo (ver perfil.SinCejas).
            preocupacion = min(1.0, max(0.0, anim.ceja_angulo / sc.angulo_pleno))
            curiosidad = min(1.0, max(0.0, (-anim.ceja_angulo - sc.umbral_curiosidad)
                                      / (sc.curiosidad_plena - sc.umbral_curiosidad)))
            hacia = 1.0 if self._expresion.mirada[0] >= 0 else -1.0
            alto_base = alto * (1.0 - sc.achatado * preocupacion)

        for lado, signo in (("izq", -1), ("der", 1)):
            ox = geo.rasgos_x + signo * geo.sep_ojos
            ancho, alto = ancho_base, alto_base
            if sc is not None:
                tamano = 1.0 + sc.asimetria * curiosidad * signo * hacia
                ancho, alto = ancho * tamano, alto * tamano
                self._dibujar_parpado(lado, signo, ox, cy, ancho, alto, preocupacion,
                                      en_arco, centro, inclinacion)

            if en_arco:
                self._dibujar_arco_ojo(lado, ox, cy, ancho, geo, anim,
                                       centro, inclinacion)
                for clave in (f"ojo_{lado}", f"brillo_{lado}", f"punto_{lado}"):
                    lienzo.itemconfigure(self._items[clave], state="hidden")
                continue

            lienzo.itemconfigure(self._items[f"arco_{lado}"], state="hidden")
            contorno = rectangulo_redondeado(
                ox - ancho / 2, cy - alto / 2, ox + ancho / 2, cy + alto / 2,
                min(ancho, alto) * po.radio, centro=centro, inclinacion=inclinacion,
            )
            estilo = self.perfil.trazo.estilo
            if estilo == "pixeles":
                self._coords_pixeles(self._items[f"ojo_{lado}"], contorno, "contorno")
                lienzo.itemconfigure(self._items[f"ojo_{lado}"], state="normal",
                                     outline=anim.color, width=self._rejilla()[0])
            else:
                self._coords(self._items[f"ojo_{lado}"], *contorno)
                lienzo.itemconfigure(
                    self._items[f"ojo_{lado}"], state="normal",
                    outline=anim.color, width=max(2, int(geo.unidad * po.borde)),
                    **({"fill": anim.color} if estilo == "redondo" else {}),
                )

            visible = "normal" if anim.parpadeo > 0.4 else "hidden"
            # Brillo grande arriba, punto pequeño abajo: dentro del ojo, que
            # es lo que lo hace parecer una mirada y no una lámpara.
            bx = ox + (anim.mirada_x + anim.deriva[0] + self._barrido) * ancho * po.mirada_x
            by = cy + (anim.mirada_y + anim.deriva[1]) * alto * po.mirada_y
            if sc is not None:
                # El brillo baja con el párpado: sigue dentro de lo que se ve.
                by += alto * preocupacion * (sc.parpado_exterior + sc.parpado_interior) / 2
            radio = ancho * po.brillo_radio
            gx, gy = rotar(bx - ancho * po.brillo_x, by - alto * po.brillo_y,
                           centro[0], centro[1], inclinacion)
            if self.perfil.trazo.estilo == "pixeles":
                # El brillo, un cuadrado de píxeles enteros.
                p_lado, rx, ry = self._rejilla()
                gx, gy = self._escalar([gx, gy])
                lado_b = max(p_lado, round(2 * radio / p_lado) * p_lado)
                x0 = rx + round((gx - lado_b / 2 - rx) / p_lado) * p_lado
                y0 = ry + round((gy - lado_b / 2 - ry) / p_lado) * p_lado
                lienzo.coords(self._items[f"brillo_{lado}"], x0, y0, x0 + lado_b, y0,
                              x0 + lado_b, y0 + lado_b, x0, y0 + lado_b)
                lienzo.itemconfigure(self._items[f"brillo_{lado}"], state=visible)
                continue
            self._coords(self._items[f"brillo_{lado}"],
                         gx - radio, gy - radio, gx + radio, gy + radio)
            lienzo.itemconfigure(self._items[f"brillo_{lado}"], state=visible)

            radio2 = ancho * po.punto_radio
            if radio2 <= 0:
                # Sin pupila (cápsula): ojo de color limpio, solo el brillo.
                lienzo.itemconfigure(self._items[f"punto_{lado}"], state="hidden")
                continue
            px, py = rotar(bx + ancho * po.punto_x, by + alto * po.punto_y,
                           centro[0], centro[1], inclinacion)
            self._coords(self._items[f"punto_{lado}"],
                         px - radio2, py - radio2, px + radio2, py + radio2)
            # Ojo macizo (cápsula): el punto, del color de la pantalla.
            lienzo.itemconfigure(
                self._items[f"punto_{lado}"], state=visible,
                fill=self._fondo_rasgos if self.perfil.trazo.estilo == "redondo"
                else anim.color)

    def _dibujar_parpado(self, lado: str, signo: int, ox: float, cy: float,
                         ancho: float, alto: float, preocupacion: float,
                         en_arco: bool, centro: tuple[float, float],
                         inclinacion: float) -> None:
        """Párpado de la preocupación en un rostro sin cejas: tapa la parte de
        arriba del ojo con el color de la pantalla, más por fuera que por
        dentro, de modo que el ojo «cae» hacia fuera."""
        item = self._items[f"parpado_{lado}"]
        sc = self.perfil.sin_cejas
        if en_arco or preocupacion < 0.02:
            self.lienzo.itemconfigure(item, state="hidden")
            return
        margen = ancho * 0.15
        arriba = cy - alto / 2
        fuera, dentro = ox + signo * (ancho / 2 + margen), ox - signo * (ancho / 2 + margen)
        y_fuera = arriba + alto * sc.parpado_exterior * preocupacion
        y_dentro = arriba + alto * sc.parpado_interior * preocupacion
        planas = []
        for x, y in ((dentro, arriba - margen), (fuera, arriba - margen),
                     (fuera, y_fuera), (dentro, y_dentro)):
            planas.extend(rotar(x, y, centro[0], centro[1], inclinacion))
        self._coords(item, *planas)
        self.lienzo.itemconfigure(item, state="normal", fill=self._fondo_rasgos)

    def _dibujar_arco_ojo(self, lado: str, ox: float, oy: float, ancho: float,
                          geo: _Geometria, anim: _Animacion,
                          centro: tuple[float, float],
                          inclinacion: float) -> None:
        """Ojo feliz: un arco grueso hacia arriba, el clásico «^»."""
        pa = self.perfil.alegria
        cierre = min(1.0, max(0.0, (pa.umbral_apertura - anim.apertura_ojos)
                              / pa.umbral_apertura))
        altura = geo.ojo_alto * (pa.altura + pa.altura_cierre * cierre)
        puntos = arco(
            ox, oy + altura * pa.bajada, ancho * pa.ancho, altura,
            centro=centro, inclinacion=inclinacion, puntos=10,
        )
        if self.perfil.trazo.estilo == "pixeles":
            self._coords_pixeles(self._items[f"arco_{lado}"], puntos, "trazo")
            self.lienzo.itemconfigure(self._items[f"arco_{lado}"], state="normal",
                                      fill=anim.color, width=self._rejilla()[0])
            return
        self._coords(self._items[f"arco_{lado}"], *puntos)
        self.lienzo.itemconfigure(
            self._items[f"arco_{lado}"], state="normal", fill=anim.color,
            width=max(4, int(geo.unidad * pa.grosor)),
        )

    def _dibujar_boca(self, geo: _Geometria, anim: _Animacion,
                      centro: tuple[float, float], inclinacion: float,
                      dy: float) -> None:
        lienzo, p, pb = self.lienzo, self.paleta, self.perfil.boca
        cy = geo.y_boca + dy
        apertura = anim.apertura_boca * geo.ref_alto * pb.apertura
        grosor = geo.unidad * pb.grosor
        alto = max(grosor, apertura)
        # La curva separa una boca neutra de una sonriente sin cambiar de
        # figura: con curva positiva el centro queda más bajo que los
        # extremos (sonrisa); con curva negativa, más alto (preocupación).
        ancho = geo.boca_ancho * (1.0 + pb.ensanche_sonrisa * max(0.0, anim.curva_boca))
        # Cuándo la boca pasa a «abierta» es GRAMÁTICA, no aspecto: no puede
        # depender del grosor de trazo de cada rostro (con trazo grueso, la
        # exhalación guiada no abría la boca). Umbral fijo, el de siempre.
        if apertura > (geo.unidad * _GROSOR_BOCA_GRAMATICA) * 1.4:
            # Boca abierta: interior oscuro con borde del color de los ojos.
            # Una banda maciza se leía como un rectángulo, no como una boca.
            puntos = rectangulo_redondeado(
                geo.rasgos_x - ancho / 2, cy - alto * pb.arriba,
                geo.rasgos_x + ancho / 2, cy + alto * pb.abajo,
                min(ancho, alto) * pb.radio, centro=centro, inclinacion=inclinacion,
            )
            pixeles = self.perfil.trazo.estilo == "pixeles"
            if pixeles:
                self._coords_pixeles(self._items["boca"], puntos, "contorno")
            else:
                self._coords(self._items["boca"], *puntos)
            lienzo.itemconfigure(
                self._items["boca"],
                fill=mezclar(p.boca_interior, self._fondo_rasgos,
                             pb.interior_hacia_fondo),
                outline=anim.color,
                width=self._rejilla()[0] if pixeles else max(2, int(grosor * pb.borde)),
            )
        else:
            # Fase 1 (corrección): antes se pasaba `desplazamiento` como
            # altura del arco, y una altura positiva SUBE el centro: la
            # sonrisa salía como ∩ y la preocupación como ∪. Ahora la altura
            # va con signo contrario y la boca sigue centrada en `cy`.
            desplazamiento = anim.curva_boca * geo.ref_alto * pb.curva
            puntos = arco(
                geo.rasgos_x, cy - desplazamiento / 2, ancho, -desplazamiento,
                centro=centro, inclinacion=inclinacion, puntos=8,
            )
            estilo = self.perfil.trazo.estilo
            if estilo == "pixeles":
                # Una tira de píxeles; si hay curva, al menos un escalón: la
                # rejilla no puede borrar la sonrisa ni la preocupación.
                celdas = max(1, round(grosor / self._rejilla()[0]))
                self._coords_pixeles(self._items["boca"], puntos, "banda", celdas,
                                     curva=desplazamiento)
            elif estilo == "redondo":
                # Guion redondeado: la misma curva, con extremos redondos.
                self._coords(self._items["boca"], *_capsula(puntos, grosor))
            else:
                # Un arco necesita grosor: se convierte en una banda estrecha.
                self._coords(self._items["boca"], *_banda(puntos, grosor))
            lienzo.itemconfigure(self._items["boca"], fill=anim.color,
                                 outline="", width=1)


    def _dibujar_barras(self, geo: _Geometria, anim: _Animacion) -> None:
        """Barras verticales del micrófono, simétricas respecto a su línea.

        Es el indicador de captación, no un adorno:
        - existen SOLO con el micrófono abierto de verdad (estado funcional
          «calibrando» o «escuchando», A1). En reposo, pensando o con la cara
          de escucha mientras el robot habla, no se dibujan;
        - en silencio, todas a `alto_minimo`: se ve que escucha;
        - su altura crece con el nivel REAL que llega del micrófono,
          fotograma a fotograma. Ningún movimiento inventado.

        Elemento propio: no gira con la cabeza ni respira con ella. Con
        carcasa van debajo de la cabeza; sin carcasa, abajo del todo.
        """
        lienzo = self.lienzo
        if not self.microfono_abierto:
            self._historial_escucha.clear()
            if self._barras_estado is not None:
                for item in self._barras_items:
                    lienzo.itemconfigure(item, state="hidden")
                self._barras_estado = None
            return
        pb = self.perfil.barras
        numero = len(self._barras_items)
        mitad = numero // 2
        self._historial_escucha.insert(0, anim.nivel_escucha)
        del self._historial_escucha[mitad + 1:]

        # Sin carcasa la unidad es la de una cara que llena la pantalla: las
        # barras se reducen (`escala_sin_carcasa`) para dejar hueco con la boca.
        u = geo.unidad * (1.0 if self.carcasa else pb.escala_sin_carcasa)
        ancho, paso = u * pb.ancho, u * (pb.ancho + pb.separacion)
        minimo, maximo = max(u * pb.alto_minimo, ancho), u * pb.alto_maximo
        if self.carcasa:
            cy = geo.centro_y + geo.cabeza_alto / 2 + geo.pie + u * pb.hueco + maximo / 2
        else:
            # Abajo del todo, a `margen_inferior_sin_carcasa` del borde.
            cy = geo.alto * (1 - pb.margen_inferior_sin_carcasa) - maximo / 2
        x0 = geo.ancho / 2 - paso * (numero - 1) / 2
        # Estado y grosor solo cuando cambian: en cada fotograma, solo coords.
        if self._barras_estado != (True, ancho):
            for item in self._barras_items:
                lienzo.itemconfigure(item, state="normal", width=ancho)
            self._barras_estado = (True, ancho)
        for i, item in enumerate(self._barras_items):
            distancia = abs(i - mitad)
            nivel = (self._historial_escucha[distancia]
                     if distancia < len(self._historial_escucha) else 0.0)
            # Las del centro llegan más alto: la forma clásica del ecualizador.
            forma = math.cos(math.pi / 2 * distancia / (mitad + 1))
            alto = minimo + (maximo - minimo) * nivel * forma
            # El extremo redondo añade medio grosor por cada lado.
            tramo = (alto - ancho) / 2
            x = x0 + paso * i
            lienzo.coords(item, x, cy - tramo, x, cy + tramo)

    def _dibujar_signo(self, geo: _Geometria, anim: _Animacion,
                       centro: tuple[float, float], inclinacion: float,
                       dy: float) -> None:
        """«!» o «?» arriba y por fuera del ojo derecho, del color de los
        ojos. Está o no está: no crece ni se anima."""
        signo = self._expresion.signo
        trazo, punto = self._items["signo_trazo"], self._items["signo_punto"]
        celdas = getattr(self, "_celdas_signo", [])
        for item in (trazo, punto, *celdas):
            self.lienzo.itemconfigure(item, state="hidden")
        if signo not in ("!", "?"):
            return
        if self.perfil.trazo.estilo == "pixeles":
            self._dibujar_signo_pixeles(geo, anim, signo, dy)
            return
        # Arriba y por fuera del ojo derecho, sin salirse del área de la
        # cara (la pantalla, o la ventana sin carcasa).
        h = geo.ojo_alto * 0.62
        if self.carcasa:
            x_max, y_min = geo.area[2], geo.area[1]
        else:
            x_max, y_min = geo.ancho * 0.97, geo.alto * 0.03
        borde_ojo = geo.rasgos_x + geo.sep_ojos + geo.ojo_ancho / 2
        # Medio ancho del signo: el «!» es estrecho y cabe por fuera del ojo
        # también sin carcasa.
        medio = (0.12 if signo == "!" else 0.3) * h
        x0 = min(borde_ojo + 0.2 * h + medio, x_max - medio)
        y0 = max(geo.y_ceja + dy - h * 0.75, y_min + 0.05 * h)
        if signo == "!":
            # Al lado del ojo, desde su borde de arriba: más alto se cruzaba
            # con el extremo de la ceja.
            y0 = geo.y_ojos + dy - geo.ojo_alto * anim.apertura_ojos / 2
        giro = 0.0
        if x0 - medio < borde_ojo and signo == "?":
            # Sin carcasa el «?» no cabe por fuera: entre los ojos, poco a la
            # derecha del centro. Es curvo: no se lee como arruga.
            x0 = geo.rasgos_x + geo.sep_ojos * 0.18
            y0 = geo.y_ceja + dy - h * 0.2
        elif x0 - medio < borde_ojo:
            # El «!» NUNCA entre los ojos: ahí una raya vertical es la arruga
            # del ceño (sondeo del 27-11-2026). Si por fuera no cabe del todo,
            # encima del ojo y inclinado, para que no sea una raya simétrica.
            y0 = max(y_min + 0.05 * h,
                     min(y0, geo.y_ojos + dy - geo.ojo_alto / 2 - 1.05 * h))
            giro = 18.0
        if signo == "!":
            linea = [(0.0, 0.08), (0.0, 0.62)]
            grosor = 0.2
        else:
            linea = [(0.2 * math.cos(math.radians(a)), 0.3 - 0.2 * math.sin(math.radians(a)))
                     for a in range(160, -61, -20)] + [(0.0, 0.64)]
            grosor = 0.16
        def situar(x, y):
            x, y = rotar(x0 + x * h, y0 + y * h, x0, y0 + 0.5 * h, giro)
            return rotar(x, y, centro[0], centro[1], inclinacion)

        puntos = [p for x, y in linea for p in situar(x, y)]
        pcx, pcy = situar(0.0, 0.87)
        radio = 0.11 * h
        octogono = [v for k in range(8)
                    for v in (pcx + radio * math.cos(k * math.pi / 4 + math.pi / 8),
                              pcy + radio * math.sin(k * math.pi / 4 + math.pi / 8))]
        self._coords(trazo, *_capsula(puntos, grosor * h))
        self._coords(punto, *octogono)
        for item in (trazo, punto):
            self.lienzo.itemconfigure(item, state="normal", fill=anim.color)

    def _dibujar_signo_pixeles(self, geo: _Geometria, anim: _Animacion,
                               signo: str, dy: float) -> None:
        """El signo como mapa de bits de 5×7 celdas de la rejilla: en una
        pantalla de píxeles, un «?» en escalera parecía un «3»."""
        lado, ox, oy = self._rejilla()
        mapa = _SIGNOS_PIXELES[signo]
        if self.carcasa:
            x_max, y_min = geo.area[2], geo.area[1]
        else:
            x_max, y_min = geo.ancho * 0.97, geo.alto * 0.03
        usadas = [col for linea in mapa for col, m in enumerate(linea) if m == "#"]
        c0, ancho = min(usadas), max(usadas) - min(usadas) + 1
        borde_ojo = geo.rasgos_x + geo.sep_ojos + geo.ojo_ancho / 2
        x0 = min(borde_ojo + 2 * lado, x_max - ancho * lado) - c0 * lado
        y0 = max(geo.y_ceja + dy - lado, y_min + lado)
        if signo == "!":
            y0 = geo.y_ojos + dy - geo.ojo_alto * anim.apertura_ojos / 2
        sesgo = 0
        if x0 + c0 * lado < borde_ojo and signo == "?":
            # No cabe por fuera del ojo (sin carcasa): entre los ojos.
            x0 = geo.rasgos_x + geo.sep_ojos * 0.18 - 2.5 * lado
            y0 = geo.y_ceja + dy - 2 * lado
        elif x0 + c0 * lado < borde_ojo:
            # El «!» nunca entre los ojos (ver _dibujar_signo): encima del
            # ojo y en cursiva, una celda cada tres filas.
            y0 = max(y_min + lado, min(y0, geo.y_ojos + dy - geo.ojo_alto / 2 - 8 * lado))
            x0 -= 2 * lado
            sesgo = 1
        # A la rejilla hacia dentro: redondear podía sacarlo 1-2 px.
        x0 = ox + math.floor((x0 - ox) / lado) * lado
        y0 = oy + math.ceil((y0 - oy) / lado) * lado
        celdas = [(col, fila) for fila, linea in enumerate(mapa)
                  for col, marca in enumerate(linea) if marca == "#"]
        for item, (col, fila) in zip(self._celdas_signo, celdas):
            x, y = x0 + (col + sesgo * (6 - fila) // 3) * lado, y0 + fila * lado
            self.lienzo.coords(item, x, y, x + lado, y, x + lado, y + lado, x, y + lado)
            self.lienzo.itemconfigure(item, state="normal", fill=anim.color)

    def _dibujar_destellos(self, geo: _Geometria, anim: _Animacion,
                           centro: tuple[float, float], t: float) -> None:
        if anim.destellos < 0.05:
            for item in self._destellos_items:
                self.lienzo.itemconfigure(item, state="hidden")
            return
        pd = self.perfil.destellos
        tamano = max(5.0, geo.unidad * pd.tamano)
        for indice, item in enumerate(self._destellos_items):
            if self.carcasa and not geo.estatico:
                # Con la cabeza, un óvalo a su alrededor. Con mueble estático o sin
                # carcasa, alrededor de los ojos.
                angulo = (indice / len(self._destellos_items)) * 2 * math.pi + t * 0.5
                x = centro[0] + geo.cabeza_ancho * pd.carcasa_radio_x * math.cos(angulo)
                y = centro[1] + geo.cabeza_alto * pd.carcasa_radio_y * math.sin(angulo)
            else:
                # Sin carcasa, tres alrededor de cada ojo: acompañan a la
                # cara a cualquier tamaño en vez de pegarse a los bordes.
                signo = -1 if indice % 2 == 0 else 1
                angulo = (indice // 2) / 3 * 2 * math.pi + t * 0.5 * signo
                ox = geo.rasgos_x + signo * geo.sep_ojos
                x = ox + geo.ojo_ancho * pd.ojo_radio_x * math.cos(angulo)
                y = (geo.y_ojos + (centro[1] - geo.rasgos_y)
                     + geo.ojo_alto * pd.ojo_radio_y * math.sin(angulo))
                x, y = rotar(x, y, centro[0], centro[1], self._anim.inclinacion)
            brillo = 0.4 + 0.6 * (0.5 + 0.5 * math.sin(t * 3.1 + indice))
            self._coords(item, *_estrella(x, y, tamano))
            self.lienzo.itemconfigure(
                item, state="normal",
                fill=mezclar(self.paleta.fondo, self.paleta.destello,
                             brillo * anim.destellos),
            )


# Signos en rejilla de píxeles (5×7): «#» es una celda encendida.
_SIGNOS_PIXELES = {
    "!": ("..#..", "..#..", "..#..", "..#..", "..#..", ".....", "..#.."),
    "?": (".###.", "#...#", "....#", "...#.", "..#..", ".....", "..#.."),
}


def _capsula(linea: list[float], grosor: float, pasos_tapa: int = 6) -> list[float]:
    """Cápsula que sigue una línea curva: borde a ambos lados y tapas redondas.

    `linea` son coordenadas planas [x0, y0, x1, y1, …] (la curva central).
    """
    pares = [(linea[i], linea[i + 1]) for i in range(0, len(linea) - 1, 2)]
    r = grosor / 2
    normales = []
    for i in range(len(pares)):
        x0, y0 = pares[max(0, i - 1)]
        x1, y1 = pares[min(len(pares) - 1, i + 1)]
        tx, ty = x1 - x0, y1 - y0
        largo = math.hypot(tx, ty) or 1.0
        tx, ty = tx / largo, ty / largo
        normales.append((tx, ty, -ty, tx))      # tangente y normal
    izquierda = [(x + nx * r, y + ny * r) for (x, y), (_, _, nx, ny) in zip(pares, normales)]
    derecha = [(x - nx * r, y - ny * r) for (x, y), (_, _, nx, ny) in zip(pares, normales)]

    def tapa(punto, tx, ty, nx, ny, sentido):
        x, y = punto
        return [(x + r * (math.cos(a) * nx + math.sin(a) * tx * sentido),
                 y + r * (math.cos(a) * ny + math.sin(a) * ty * sentido))
                for a in (math.pi * k / pasos_tapa for k in range(1, pasos_tapa))]

    tx, ty, nx, ny = normales[-1]
    final = tapa(pares[-1], tx, ty, nx, ny, 1)
    tx, ty, nx, ny = normales[0]
    inicio = tapa(pares[0], tx, ty, -nx, -ny, -1)
    plano: list[float] = []
    for x, y in izquierda + final + list(reversed(derecha)) + inicio:
        plano.extend((x, y))
    return plano


def _a_rejilla(valor: float, origen: float, lado: float) -> float:
    return origen + round((valor - origen) / lado) * lado


def _remuestrear(planas, paso: float, cerrado: bool) -> list[tuple[float, float]]:
    """Recorre la figura dejando un punto cada `paso`: así ningún tramo largo
    se salta celdas al llevarla a la rejilla."""
    pares = [(planas[i], planas[i + 1]) for i in range(0, len(planas) - 1, 2)]
    if cerrado:
        pares.append(pares[0])
    salida = [pares[0]]
    for (x0, y0), (x1, y1) in zip(pares, pares[1:]):
        n = max(1, int(math.hypot(x1 - x0, y1 - y0) / paso))
        salida += [(x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n) for k in range(1, n + 1)]
    return salida


def _a_celda(valor: float, origen: float, lado: float) -> float:
    """El centro de la celda de la rejilla que contiene `valor`."""
    return origen + (math.floor((valor - origen) / lado) + 0.5) * lado


def _escalera(planas, lado: float, ox: float, oy: float, cerrado: bool) -> list[float]:
    """Lleva una figura a la rejilla y la convierte en escalera: solo tramos
    horizontales y verticales que pasan por el CENTRO de las celdas. Con un
    trazo de `lado` de grueso, cada tramo pinta celdas enteras."""
    puntos = []
    for x, y in _remuestrear(planas, lado / 2, cerrado):
        punto = (_a_celda(x, ox, lado), _a_celda(y, oy, lado))
        if not puntos or punto != puntos[-1]:
            puntos.append(punto)
    if cerrado and len(puntos) > 1 and puntos[0] == puntos[-1]:
        puntos.pop()
    salida = []
    n = len(puntos)
    for i, a in enumerate(puntos):
        salida.append(a)
        if i + 1 < n or cerrado:
            b = puntos[(i + 1) % n]
            if a[0] != b[0] and a[1] != b[1]:
                salida.append((b[0], a[1]))
    if len(salida) < 3:
        salida += [salida[-1]] * (3 - len(salida))
    return [v for punto in salida for v in punto]


def _banda_pixeles(planas, lado: float, ox: float, oy: float, celdas: int = 1,
                   curva: float = 0.0) -> list[float]:
    """Una tira de `celdas` píxeles de grueso que sigue una curva abierta,
    columna a columna. Con `curva` (centro menos extremos, en px), si la
    rejilla dejara la tira plana se fuerza un escalón con su signo."""
    pares = [(planas[i], planas[i + 1]) for i in range(0, len(planas) - 1, 2)]
    pares.sort()
    xs = [x for x, _ in pares]
    primera = math.floor((xs[0] - ox) / lado)
    ultima = max(primera, math.floor((xs[-1] - ox) / lado))

    def y_en(x):
        if x <= xs[0]:
            return pares[0][1]
        for (x0, y0), (x1, y1) in zip(pares, pares[1:]):
            if x0 <= x <= x1:
                return y0 + (y1 - y0) * ((x - x0) / (x1 - x0) if x1 != x0 else 0.0)
        return pares[-1][1]

    columnas = list(range(primera, ultima + 1))
    filas = [math.floor((y_en(ox + (c + 0.5) * lado) - oy) / lado) for c in columnas]
    if abs(curva) >= 0.25 * lado and len(filas) >= 3:
        medio = len(filas) // 2
        if filas[medio] == filas[0] and filas[medio] == filas[-1]:
            paso = 1 if curva > 0 else -1
            tercio = max(1, len(filas) // 3)
            for k in range(tercio, len(filas) - tercio):
                filas[k] += paso
    arriba, abajo = [], []
    for c, f in zip(columnas, filas):
        x0, x1 = ox + c * lado, ox + (c + 1) * lado
        y0 = oy + f * lado
        arriba += [(x0, y0), (x1, y0)]
        abajo += [(x0, y0 + celdas * lado), (x1, y0 + celdas * lado)]
    return [v for punto in arriba + abajo[::-1] for v in punto]


def _estrella(x: float, y: float, radio: float) -> list[float]:
    """Estrella de cuatro puntas: ocho vértices, puntas y entrantes."""
    puntos: list[float] = []
    for k in range(8):
        r = radio if k % 2 == 0 else radio * 0.32
        a = math.pi / 4 * k - math.pi / 2
        puntos.extend((x + r * math.cos(a), y + r * math.sin(a)))
    return puntos


def _banda(puntos: list[float], grosor: float) -> list[float]:
    """Convierte una curva abierta en un polígono cerrado con grosor."""
    pares = [(puntos[i], puntos[i + 1]) for i in range(0, len(puntos), 2)]
    arriba = [(x, y - grosor / 2) for x, y in pares]
    abajo = [(x, y + grosor / 2) for x, y in reversed(pares)]
    plano: list[float] = []
    for x, y in arriba + abajo:
        plano.extend((x, y))
    return plano


def crear_cara(lienzo, ajustes_rostro) -> Cara:
    """La cara tal como la dibuja la aplicación, a partir de sus ajustes.

    Es el ÚNICO punto por el que la aplicación y el visor
    (bin/vista_previa_rostro.py) crean el rostro: mismo perfil, misma
    carcasa, mismo código de dibujo. Así lo que se ve en el visor es lo que
    se verá en la aplicación.
    """
    perfil = cargar_perfil(getattr(ajustes_rostro, "perfil", None) or "hybrid_balanced")
    cara = Cara(lienzo, perfil.colores, carcasa=ajustes_rostro.carcasa, perfil=perfil)
    aplicar_ajustes(cara, ajustes_rostro)
    return cara


def aplicar_ajustes(cara: Cara, ajustes_rostro) -> None:
    """Tamaño, animaciones y parpadeo de la configuración (en caliente)."""
    tamano = max(0.5, min(1.0, float(getattr(ajustes_rostro, "tamano_rostro", 1.0))))
    cambia = tamano != cara.tamano_rostro
    cara.tamano_rostro = tamano
    cara.animaciones = bool(getattr(ajustes_rostro, "animaciones", True))
    cara.parpadeo_activo = bool(getattr(ajustes_rostro, "parpadeo", True))
    if cambia:
        cara.reconfigurar()
