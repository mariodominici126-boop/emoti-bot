"""Rostro HYBRID BALANCED dibujado con Pillow (Fase 1C, EXPERIMENTAL).

Lo que cambia respecto al rostro de producción, y por qué
---------------------------------------------------------
1. Motor: se dibuja en una imagen RGBA con supermuestreo (×2 y reducción con
   LANCZOS), lo que da bordes suavizados, y con degradados y transparencia
   reales. Tkinter solo muestra la imagen resultante en el mismo Canvas.
2. Geometría (decisión de diseño, separada del motor): ojos más grandes y
   algo más juntos, cejas de cápsula, boca con interior y lengua al abrirse,
   orejas en forma de cápsula con un piloto, y sombra bajo la cabeza.

Lo que se conserva para que siga siendo EMOTI-BOT: la cabeza de carcasa
clara con pantalla oscura, las orejas laterales, los ojos de esquinas
redondeadas con borde luminoso y brillo, los ojos en arco «^ ^» de la
alegría, la barra de la barbilla como piloto del micrófono, la paleta y los
destellos.

Rendimiento: todo lo estático (fondo, sombra, carcasa, orejas, pantalla,
reflejo) se dibuja una vez por tamaño de ventana. La cabeza girada se guarda
en caché por ángulo (pasos de 0,25°). Por fotograma solo se dibujan los
rasgos, en un recorte del tamaño de la cabeza, y el halo, a 1/4 de
resolución.
"""
from __future__ import annotations

import math
from collections import OrderedDict
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFilter

from emotibot.rostro.formas import arco, rectangulo_redondeado, rotar
from emotibot.rostro.paleta import PALETA, Paleta, _a_rgb, aclarar, mezclar, oscurecer

_PERIODO_RESPIRACION = 4.6
_CACHE_GIROS_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class Geometria:
    ancho: int
    alto: int
    escala: float
    cx: float
    cy: float
    cabeza_w: float
    cabeza_h: float
    radio: float
    marco: float
    sep_ojos: float
    ojo_w: float
    ojo_h: float
    y_ojos: float
    y_ceja: float
    y_boca: float
    y_barbilla: float
    boca_w: float
    recorte_w: int
    recorte_h: int


def geometria(ancho: int, alto: int) -> Geometria:
    ancho, alto = max(ancho, 320), max(alto, 240)
    escala = min(ancho, alto)
    cabeza_w = min(ancho * 0.80, escala * 1.10)
    cabeza_h = min(alto * 0.64, escala * 0.80)
    cy = alto * 0.47
    return Geometria(
        ancho=ancho, alto=alto, escala=escala, cx=ancho / 2, cy=cy,
        cabeza_w=cabeza_w, cabeza_h=cabeza_h, radio=cabeza_h * 0.36,
        marco=escala * 0.034,
        sep_ojos=cabeza_w * 0.200, ojo_w=cabeza_w * 0.165,
        ojo_h=cabeza_h * 0.340,
        y_ojos=cy - cabeza_h * 0.04, y_ceja=cy - cabeza_h * 0.275,
        y_boca=cy + cabeza_h * 0.215, y_barbilla=cy + cabeza_h * 0.350,
        boca_w=cabeza_w * 0.110,
        recorte_w=int(cabeza_w * 1.30), recorte_h=int(cabeza_h * 1.34),
    )


def _rgba(color: str, alfa: float = 1.0) -> tuple[int, int, int, int]:
    r, g, b = _a_rgb(color)
    return r, g, b, max(0, min(255, int(255 * alfa)))


def _degradado_vertical(tam: tuple[int, int], arriba: str, abajo: str) -> Image.Image:
    gradiente = Image.linear_gradient("L").resize(tam)
    return Image.composite(Image.new("RGBA", tam, _rgba(abajo)),
                           Image.new("RGBA", tam, _rgba(arriba)), gradiente)


def _degradado_radial(tam: tuple[int, int], centro: str, borde: str) -> Image.Image:
    gradiente = Image.radial_gradient("L").resize(tam)
    return Image.composite(Image.new("RGBA", tam, _rgba(borde)),
                           Image.new("RGBA", tam, _rgba(centro)), gradiente)


def _pares(plano: list[float]) -> list[tuple[float, float]]:
    return [(plano[i], plano[i + 1]) for i in range(0, len(plano) - 1, 2)]


class RostroPillow:
    """Genera fotogramas a partir del estado de animación de la Cara."""

    def __init__(self, ancho: int, alto: int, paleta: Paleta = PALETA,
                 supermuestreo: int = 2, halo: bool = True) -> None:
        self.paleta = paleta
        self.s = max(1, int(supermuestreo))
        self.halo = halo
        self.geo = geometria(ancho, alto)
        self._fondo = self._dibujar_fondo()
        self._cabeza = self._dibujar_cabeza()
        self._giradas: OrderedDict[int, Image.Image] = OrderedDict()
        self._degradados: dict[tuple, Image.Image] = {}

    # ------------------------------------------------------------ coordenadas
    def _local(self, puntos, origen: tuple[float, float], s: int):
        ox, oy = origen
        return [((x - ox) * s, (y - oy) * s) for x, y in puntos]

    # ----------------------------------------------------------- estáticos
    def _dibujar_fondo(self) -> Image.Image:
        g, p = self.geo, self.paleta
        fondo = _degradado_radial((g.ancho, g.alto), aclarar(p.fondo, 0.07),
                                  p.fondo).convert("RGB")
        sombra = Image.new("L", (g.ancho, g.alto), 0)
        ImageDraw.Draw(sombra).ellipse(
            (g.cx - g.cabeza_w * 0.42, g.cy + g.cabeza_h * 0.50,
             g.cx + g.cabeza_w * 0.42, g.cy + g.cabeza_h * 0.60), fill=150)
        sombra = sombra.filter(ImageFilter.GaussianBlur(g.escala * 0.022))
        fondo.paste(Image.new("RGB", fondo.size, (0, 0, 0)), (0, 0), sombra)
        return fondo

    def _dibujar_cabeza(self) -> Image.Image:
        """Carcasa, orejas, pantalla y reflejo, centrados en el recorte."""
        g, p, s = self.geo, self.paleta, self.s
        w, h = g.recorte_w * s, g.recorte_h * s
        capa = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        cx, cy = w / 2, h / 2
        mw, mh = g.cabeza_w / 2 * s, g.cabeza_h / 2 * s

        def pegar(poligono, relleno: Image.Image, caja) -> None:
            mascara = Image.new("L", (w, h), 0)
            ImageDraw.Draw(mascara).polygon(_pares(poligono), fill=255)
            lienzo = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            x0, y0, x1, y1 = (int(v) for v in caja)
            lienzo.paste(relleno.resize((max(1, x1 - x0), max(1, y1 - y0))), (x0, y0))
            capa.alpha_composite(Image.composite(lienzo, Image.new("RGBA", (w, h)), mascara))

        # Orejas: cápsulas detrás de la carcasa.
        oreja_w, oreja_h = g.escala * 0.060 * s, g.cabeza_h * 0.34 * s
        for signo in (-1, 1):
            borde = cx + signo * mw
            x0 = borde - oreja_w * (0.15 if signo > 0 else 1.0)
            x1 = borde + oreja_w * (1.0 if signo > 0 else 0.15)
            caja = (x0, cy - oreja_h / 2, x1, cy + oreja_h / 2)
            pegar(rectangulo_redondeado(*caja, oreja_w * 0.48),
                  _degradado_vertical((8, 64), aclarar(p.carcasa_sombra, 0.18),
                                      oscurecer(p.carcasa_sombra, 0.18)), caja)

        # Carcasa con luz cenital y un filo de luz arriba.
        caja = (cx - mw, cy - mh, cx + mw, cy + mh)
        pegar(rectangulo_redondeado(*caja, g.radio * s),
              _degradado_vertical((8, 128), aclarar(p.carcasa, 0.30),
                                  oscurecer(p.carcasa, 0.16)), caja)
        filo = Image.new("L", (w, h), 0)
        d = ImageDraw.Draw(filo)
        d.polygon(_pares(rectangulo_redondeado(*caja, g.radio * s)), fill=90)
        d.polygon(_pares(rectangulo_redondeado(
            cx - mw, cy - mh + g.escala * 0.010 * s, cx + mw, cy + mh,
            g.radio * s)), fill=0)
        capa.paste(Image.new("RGBA", (w, h), (255, 255, 255, 255)), (0, 0), filo)

        # Pantalla: viñeta radial, más clara en el centro.
        m = g.marco * s
        caja = (cx - mw + m, cy - mh + m, cx + mw - m, cy + mh - m)
        radio_pantalla = max(0.0, g.radio * s - m * 0.6)
        pegar(rectangulo_redondeado(*caja, radio_pantalla),
              _degradado_radial((128, 128), aclarar(p.pantalla_brillo, 0.04),
                                oscurecer(p.pantalla, 0.35)), caja)
        # Reflejo del cristal: una banda diagonal muy tenue, recortada a la pantalla.
        mascara = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mascara).polygon(
            _pares(rectangulo_redondeado(*caja, radio_pantalla)), fill=255)
        reflejo = Image.new("L", (w, h), 0)
        ImageDraw.Draw(reflejo).polygon(
            [(caja[0], caja[1]), (caja[0] + (caja[2] - caja[0]) * 0.55, caja[1]),
             (caja[0] + (caja[2] - caja[0]) * 0.30, caja[1] + (caja[3] - caja[1]) * 0.42),
             (caja[0], caja[1] + (caja[3] - caja[1]) * 0.42)], fill=16)
        reflejo = Image.composite(reflejo, Image.new("L", (w, h), 0), mascara)
        capa.paste(Image.new("RGBA", (w, h), (255, 255, 255, 255)), (0, 0),
                   reflejo.filter(ImageFilter.GaussianBlur(g.escala * 0.02 * s)))

        if s > 1:
            capa = capa.resize((g.recorte_w, g.recorte_h), Image.LANCZOS)
        return capa

    def _cabeza_girada(self, grados: float) -> Image.Image:
        clave = int(round(grados * 4))          # pasos de 0,25°
        if clave in self._giradas:
            self._giradas.move_to_end(clave)
            return self._giradas[clave]
        girada = (self._cabeza if clave == 0 else
                  self._cabeza.rotate(-clave / 4, resample=Image.BICUBIC))
        self._giradas[clave] = girada
        # Tope por MEMORIA, no por número: en 1080p cada giro ocupa ~6 MB.
        por_imagen = self._cabeza.width * self._cabeza.height * 4
        maximo = max(4, int(_CACHE_GIROS_BYTES // max(1, por_imagen)))
        while len(self._giradas) > maximo:
            self._giradas.popitem(last=False)
        return girada

    # ---------------------------------------------------------- fotograma
    def cuadro(self, anim, expresion, t: float) -> Image.Image:
        g, p, s = self.geo, self.paleta, self.s
        respiracion = math.sin(2 * math.pi * t / _PERIODO_RESPIRACION)
        dy = respiracion * g.escala * 0.007 * anim.respira
        inclinacion = anim.inclinacion + respiracion * 0.45
        centro = (g.cx, g.cy + dy)
        ox = round(g.cx - g.recorte_w / 2)
        oy = round(g.cy + dy - g.recorte_h / 2)
        origen = (ox, oy)

        rasgos = Image.new("RGBA", (g.recorte_w * s, g.recorte_h * s), (0, 0, 0, 0))
        pintor = ImageDraw.Draw(rasgos)
        brillo = None
        if self.halo:
            brillo = Image.new("RGBA", (g.recorte_w // 4 + 1, g.recorte_h // 4 + 1),
                               (0, 0, 0, 0))
        color = anim.color

        def a_halo(puntos, relleno, ancho_linea=0):
            if brillo is None:
                return
            locales = self._local(puntos, origen, 1)
            locales = [(x / 4, y / 4) for x, y in locales]
            d = ImageDraw.Draw(brillo)
            if ancho_linea:
                d.line(locales, fill=relleno, width=max(1, int(ancho_linea / 4)),
                       joint="curve")
            else:
                d.polygon(locales, fill=relleno)

        def linea(puntos, relleno, grosor):
            locales = self._local(puntos, origen, s)
            ancho_s = max(1, int(grosor * s))
            pintor.line(locales, fill=relleno, width=ancho_s, joint="curve")
            radio = ancho_s / 2
            for x, y in (locales[0], locales[-1]):    # extremos redondeados
                pintor.ellipse((x - radio, y - radio, x + radio, y + radio), fill=relleno)

        def circulo(x, y, radio, relleno):
            x, y = rotar(x, y, centro[0], centro[1], inclinacion)
            (lx, ly), = self._local([(x, y)], origen, s)
            r = radio * s
            pintor.ellipse((lx - r, ly - r, lx + r, ly + r), fill=relleno)

        # --- Cejas: cápsulas que se inclinan en sentidos opuestos.
        cy_ceja = g.y_ceja + dy - anim.ceja_alto * g.cabeza_h * 0.09
        for signo in (-1, 1):
            ox_ojo = g.cx + signo * g.sep_ojos
            sesgo = math.tan(math.radians(anim.ceja_angulo)) * g.ojo_w * 1.2 * 0.9 * signo
            puntos = _pares(arco(ox_ojo, cy_ceja, g.ojo_w * 1.2, g.cabeza_h * 0.035,
                                 centro=centro, inclinacion=inclinacion,
                                 sesgo=sesgo, puntos=10))
            linea(puntos, _rgba(mezclar(p.pantalla, color, 0.88)), g.escala * 0.017)

        # --- Ojos.
        cy_ojo = g.y_ojos + dy
        alto = max(g.escala * 0.008, g.ojo_h * anim.apertura_ojos * anim.parpadeo)
        en_arco = expresion.ojos_arco and anim.apertura_ojos < 0.55
        for signo in (-1, 1):
            ox_ojo = g.cx + signo * g.sep_ojos
            if en_arco:
                cierre = min(1.0, max(0.0, (0.55 - anim.apertura_ojos) / 0.55))
                altura = g.ojo_h * (0.24 + 0.30 * cierre)
                puntos = _pares(arco(ox_ojo, cy_ojo + altura * 0.35, g.ojo_w * 1.05,
                                     altura, centro=centro, inclinacion=inclinacion,
                                     puntos=14))
                linea(puntos, _rgba(color), g.escala * 0.026)
                a_halo(puntos, _rgba(color, 0.9), g.escala * 0.05)
                continue
            self._ojo(rasgos, pintor, ox_ojo, cy_ojo, alto, anim, color, centro,
                      inclinacion, origen, a_halo, circulo)

        # --- Boca.
        cy_boca = g.y_boca + dy
        apertura = anim.apertura_boca * g.cabeza_h * 0.17
        grosor = g.escala * 0.017
        ancho = g.boca_w * (1.0 + 0.55 * max(0.0, anim.curva_boca))
        if apertura > grosor * 1.4:
            caja = (g.cx - ancho / 2, cy_boca - apertura * 0.35,
                    g.cx + ancho / 2, cy_boca + apertura * 0.65)
            contorno = _pares(rectangulo_redondeado(
                *caja, min(ancho, apertura) * 0.48, centro=centro,
                inclinacion=inclinacion))
            locales = self._local(contorno, origen, s)
            pintor.polygon(locales, fill=_rgba(mezclar(p.boca_interior, p.pantalla, 0.3)),
                           outline=_rgba(color), width=max(1, int(grosor * 0.55 * s)))
            if apertura > grosor * 2.6:            # lengua, solo con la boca bien abierta
                lengua = rectangulo_redondeado(
                    g.cx - ancho * 0.26, caja[3] - apertura * 0.34,
                    g.cx + ancho * 0.26, caja[3] - grosor * 0.35,
                    apertura * 0.2, centro=centro, inclinacion=inclinacion)
                pintor.polygon(self._local(_pares(lengua), origen, s),
                               fill=_rgba(mezclar(p.lengua, p.boca_interior, 0.25)))
            a_halo(contorno, _rgba(color, 0.55))
        else:
            # Curva positiva = sonrisa (centro MÁS BAJO que los extremos). El
            # rostro de producción lo dibuja al revés: ver docs/fase1.
            curva = anim.curva_boca * g.cabeza_h * 0.035
            puntos = _pares(arco(g.cx, cy_boca - curva * 0.4, ancho, -curva,
                                 centro=centro, inclinacion=inclinacion, puntos=12))
            linea(puntos, _rgba(color), grosor)
            a_halo(puntos, _rgba(color, 0.6), grosor * 2.2)

        # --- Barbilla: piloto del micrófono, con halo solo al escuchar.
        escucha = anim.anillo
        nivel = anim.nivel_escucha if escucha > 0.05 else 0.0
        ancho_b = g.cabeza_w * (0.085 + (0.10 + 0.085 * nivel) * escucha)
        alto_b = g.escala * (0.013 + 0.006 * escucha * (0.4 + 0.6 * nivel))
        by = g.y_barbilla + dy
        barra = _pares(rectangulo_redondeado(
            g.cx - ancho_b / 2, by - alto_b / 2, g.cx + ancho_b / 2, by + alto_b / 2,
            alto_b * 0.5, centro=centro, inclinacion=inclinacion))
        intensidad = 0.45 + 0.55 * escucha * (0.5 + 0.5 * nivel)
        pintor.polygon(self._local(barra, origen, s),
                       fill=_rgba(mezclar(p.pantalla, color, intensidad)))
        if escucha > 0.05:
            a_halo(barra, _rgba(color, 0.9 * escucha))

        # --- Rubor y destellos de la alegría.
        if anim.destellos > 0.05 and brillo is not None:
            for signo in (-1, 1):
                x, y = rotar(g.cx + signo * g.sep_ojos * 1.25,
                             g.y_ojos + dy + g.ojo_h * 0.55,
                             centro[0], centro[1], inclinacion)
                (lx, ly), = self._local([(x, y)], origen, 1)
                r = g.ojo_w * 0.28 / 4
                ImageDraw.Draw(brillo).ellipse(
                    (lx / 4 - r * 1.4, ly / 4 - r, lx / 4 + r * 1.4, ly / 4 + r),
                    fill=_rgba(p.lengua, 0.55 * anim.destellos))
        if anim.destellos > 0.05:
            for indice in range(6):
                angulo = (indice / 6) * 2 * math.pi + t * 0.5
                x = centro[0] + g.cabeza_w * 0.60 * math.cos(angulo) * 0.92
                y = centro[1] + g.cabeza_h * 0.46 * math.sin(angulo) * 0.88
                luz = 0.4 + 0.6 * (0.5 + 0.5 * math.sin(t * 3.1 + indice))
                self._estrella(pintor, x, y, g.escala * 0.020, origen,
                               _rgba(p.destello, luz * anim.destellos))

        # --- Composición.
        recorte = self._cabeza_girada(inclinacion).copy()
        if brillo is not None:
            recorte.alpha_composite(
                brillo.filter(ImageFilter.GaussianBlur(max(1.0, g.escala * 0.006)))
                .resize(recorte.size, Image.BILINEAR))
        if s > 1:
            # reduce(): media exacta de bloques s×s. Para un factor entero
            # suaviza igual que LANCZOS y cuesta una fracción.
            rasgos = rasgos.reduce(s)
            if rasgos.size != recorte.size:
                rasgos = rasgos.crop((0, 0, *recorte.size))
        recorte.alpha_composite(rasgos)
        cuadro = self._fondo.copy()
        cuadro.paste(recorte, (ox, oy), recorte)
        return cuadro

    # ------------------------------------------------------------- piezas
    def _ojo(self, rasgos, pintor, ox_ojo, cy_ojo, alto, anim, color, centro,
             inclinacion, origen, a_halo, circulo) -> None:
        g, p, s = self.geo, self.paleta, self.s
        ancho = g.ojo_w
        borde = ancho * 0.115
        contorno = _pares(rectangulo_redondeado(
            ox_ojo - ancho / 2, cy_ojo - alto / 2, ox_ojo + ancho / 2, cy_ojo + alto / 2,
            min(ancho, alto) * 0.46, centro=centro, inclinacion=inclinacion))
        pintor.polygon(self._local(contorno, origen, s), fill=_rgba(color))
        a_halo(contorno, _rgba(color, 0.75))
        if alto <= borde * 2.6:                    # párpado cerrado: solo la línea
            return
        interior = _pares(rectangulo_redondeado(
            ox_ojo - ancho / 2 + borde, cy_ojo - alto / 2 + borde,
            ox_ojo + ancho / 2 - borde, cy_ojo + alto / 2 - borde,
            min(ancho, alto) * 0.40, centro=centro, inclinacion=inclinacion))
        locales = self._local(interior, origen, s)
        xs, ys = [x for x, _ in locales], [y for _, y in locales]
        caja = (int(min(xs)), int(min(ys)), int(max(xs)) + 1, int(max(ys)) + 1)
        tam = (max(1, caja[2] - caja[0]), max(1, caja[3] - caja[1]))
        clave = (color, tam[0] // 4, tam[1] // 4)
        relleno = self._degradados.get(clave)
        if relleno is None:
            relleno = _degradado_vertical((8, 64), oscurecer(p.pantalla, 0.25),
                                          mezclar(p.pantalla, color, 0.32)).resize(tam)
            self._degradados[clave] = relleno
        mascara = Image.new("L", tam, 0)
        ImageDraw.Draw(mascara).polygon([(x - caja[0], y - caja[1]) for x, y in locales],
                                        fill=255)
        rasgos.paste(relleno.resize(tam), caja[:2], mascara)

        if anim.parpadeo <= 0.4:
            return
        # Iris, brillo grande arriba y punto pequeño abajo, siguiendo la mirada.
        bx = ox_ojo + (anim.mirada_x + anim.deriva[0]) * ancho * 0.16
        by = cy_ojo + (anim.mirada_y + anim.deriva[1]) * alto * 0.14
        radio_iris = min(ancho, alto) * 0.26
        circulo(bx, by + alto * 0.04, radio_iris, _rgba(mezclar(p.pantalla, color, 0.55)))
        circulo(bx - ancho * 0.11, by - alto * 0.16, ancho * 0.17, _rgba(p.brillo, 0.95))
        circulo(bx + ancho * 0.13, by + alto * 0.17, ancho * 0.065, _rgba(p.brillo, 0.8))

    def _estrella(self, pintor, x, y, radio, origen, relleno) -> None:
        puntos = []
        for k in range(8):
            r = radio if k % 2 == 0 else radio * 0.32
            a = math.pi / 4 * k - math.pi / 2
            puntos.append((x + r * math.cos(a), y + r * math.sin(a)))
        pintor.polygon(self._local(puntos, origen, self.s), fill=relleno)
