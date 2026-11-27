"""Muebles ESTÁTICOS de los rostros: la tele y la cápsula.

Se dibujan una sola vez, al crear la cara (o al cambiar el tamaño de la
ventana), y no se vuelven a tocar: por fotograma solo se mueven los rasgos
de dentro de la pantalla. Las bandas del degradado, las líneas de barrido,
los mandos y las rejillas cuestan CERO por fotograma.

Todo son figuras planas de Canvas. El «metal» y el «plástico» se sugieren
con degradados POR BANDAS: diez o doce franjas horizontales de color
escalonado (paleta.mezclar), recortadas a la silueta del mueble, y un filo
de luz claro en el borde superior. No hay reflejos especulares ni cristal
curvo: eso es renderizado 3D y en Canvas quedaría chapucero.

`figuras()` es pura (no toca el lienzo): devuelve qué dibujar. Así la cara
dibuja con ella y calcula con ella la caja que ocupa el mueble (antenas y
zócalo incluidos) para que los textos de la aplicación la esquiven.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .formas import rectangulo_redondeado
from .paleta import mezclar

ETIQUETA = "mueble"


@dataclass(frozen=True)
class Caja:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def ancho(self) -> float:
        return self.x1 - self.x0

    @property
    def alto(self) -> float:
        return self.y1 - self.y0

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


def caja_mueble(cx: float, cy: float, alto: float, mueble) -> Caja:
    ancho = alto * mueble.proporcion
    return Caja(cx - ancho / 2, cy - alto / 2, cx + ancho / 2, cy + alto / 2)


def caja_pantalla(mueble_caja: Caja, mueble) -> Caja:
    c = mueble_caja
    return Caja(c.x0 + mueble.pantalla_x0 * c.ancho, c.y0 + mueble.pantalla_y0 * c.alto,
                c.x0 + mueble.pantalla_x1 * c.ancho, c.y0 + mueble.pantalla_y1 * c.alto)


# ------------------------------------------------------------------ geometría
def _recortar(puntos: list[float], ya: float, yb: float) -> list[float]:
    """Recorta un polígono a la franja horizontal ya ≤ y ≤ yb."""
    def corte(pts, dentro, cruce):
        salida = []
        for i in range(len(pts)):
            a, b = pts[i - 1], pts[i]
            if dentro(b):
                if not dentro(a):
                    salida.append(cruce(a, b))
                salida.append(b)
            elif dentro(a):
                salida.append(cruce(a, b))
        return salida

    def en_y(y):
        def cruce(a, b):
            t = (y - a[1]) / (b[1] - a[1])
            return (a[0] + (b[0] - a[0]) * t, y)
        return cruce

    pts = [(puntos[i], puntos[i + 1]) for i in range(0, len(puntos), 2)]
    pts = corte(pts, lambda p: p[1] >= ya, en_y(ya))
    pts = corte(pts, lambda p: p[1] <= yb, en_y(yb)) if pts else []
    return [v for p in pts for v in p]


def _redondeado(c: Caja, radio: float) -> list[float]:
    return rectangulo_redondeado(c.x0, c.y0, c.x1, c.y1, min(radio, c.alto / 2, c.ancho / 2))


def _bandas(contorno: list[float], c: Caja, n: int, claro: str, oscuro: str) -> list[dict]:
    """Degradado por bandas: n franjas planas de claro (arriba) a oscuro."""
    figuras = []
    for i in range(n):
        ya = c.y0 + c.alto * i / n
        yb = c.y0 + c.alto * (i + 1) / n + 0.5        # solape: sin rendijas
        trozo = _recortar(contorno, ya, yb)
        if len(trozo) >= 6:
            figuras.append(_poligono(trozo, mezclar(claro, oscuro, i / max(1, n - 1))))
    return figuras


def _poligono(coords, relleno, borde="", grosor=1) -> dict:
    return {"tipo": "polygon", "coords": list(coords),
            "kw": {"fill": relleno, "outline": borde, "width": grosor}}


def _linea(coords, color, grosor, cap="round") -> dict:
    return {"tipo": "line", "coords": list(coords),
            "kw": {"fill": color, "width": grosor, "capstyle": cap}}


def _circulo(x, y, r, relleno, borde="", grosor=1) -> dict:
    return {"tipo": "oval", "coords": [x - r, y - r, x + r, y + r],
            "kw": {"fill": relleno, "outline": borde, "width": grosor}}


def _extremos_en(c: Caja, radio: float, y: float) -> tuple[float, float]:
    """Extremos x del rectángulo redondeado `c` a la altura y."""
    r = min(radio, c.alto / 2, c.ancho / 2)
    d = max(c.y0 + r - y, y - (c.y1 - r), 0.0)
    dx = r - math.sqrt(max(0.0, r * r - d * d))
    return c.x0 + dx, c.x1 - dx


def _filo_de_luz(c: Caja, radio: float, color: str) -> dict:
    """Un solo polígono claro a lo largo del borde superior."""
    interior = Caja(c.x0 + c.ancho * 0.035, c.y0 + c.alto * 0.012,
                    c.x1 - c.ancho * 0.035, c.y1)
    trozo = _recortar(_redondeado(interior, radio * 0.9), interior.y0,
                      interior.y0 + c.alto * 0.022)
    return _poligono(trozo, color)


# ----------------------------------------------------------------------- tele
def _tele(caja: Caja, m, p) -> list[dict]:
    H, W = caja.alto, caja.ancho
    claro, oscuro, filo = p.mueble_claro, p.mueble_oscuro, p.mueble_filo
    detalle, acento = p.mueble_detalle, p.mueble_acento
    figuras: list[dict] = []
    # Antenas: dos varillas con bola, en V, detrás del mueble.
    grosor = max(2.0, H * 0.016)
    base_y = caja.y0 - H * 0.02
    alto_antena = H * m.antena
    for signo in (-1, 1):
        x_tope = caja.cx + signo * W * 0.20
        y_tope = caja.y0 - alto_antena + H * 0.035
        figuras.append(_linea([caja.cx + signo * W * 0.03, base_y, x_tope, y_tope],
                              detalle, grosor))
        figuras.append(_circulo(x_tope, y_tope, H * 0.032, claro, detalle, max(1, grosor / 2)))
    # Cúpula de las antenas.
    cupula = Caja(caja.cx - W * 0.11, caja.y0 - H * 0.055, caja.cx + W * 0.11, caja.y0 + H * 0.05)
    figuras += _bandas(_redondeado(cupula, cupula.alto * 0.5), cupula, 3, claro, oscuro)
    # Zócalo, debajo y detrás.
    zocalo = Caja(caja.x0 + W * 0.13, caja.y1 - H * 0.04, caja.x1 - W * 0.13,
                  caja.y1 + H * m.zocalo)
    figuras += _bandas(_redondeado(zocalo, H * 0.03), zocalo, 3,
                       mezclar(claro, oscuro, 0.45), mezclar(oscuro, detalle, 0.4))
    # Mueble: bandas de metal y filo de luz.
    contorno = _redondeado(caja, H * m.radio)
    figuras += _bandas(contorno, caja, m.bandas, claro, oscuro)
    figuras.append(_filo_de_luz(caja, H * m.radio, filo))
    # El tubo: esquinas MUY redondeadas.
    pant = caja_pantalla(caja, m)
    r_pant = pant.alto * m.radio_pantalla
    grueso_marco = H * 0.035
    marco = Caja(pant.x0 - grueso_marco, pant.y0 - grueso_marco, pant.x1 + grueso_marco,
                 pant.y1 + grueso_marco)
    figuras.append(_poligono(_redondeado(marco, r_pant + grueso_marco), p.pantalla))
    # Líneas de barrido: horizontales, finas, apenas más claras, estáticas.
    # UNA sola figura en zigzag (Tk repinta por figura lo que queda bajo los
    # rasgos que se mueven: 40 líneas sueltas costaban ~0,8 ms por fotograma).
    # Las uniones verticales caen en la zona del marco, que va encima.
    paso = max(3.0, round(pant.alto / 55))
    r_marco = r_pant + grueso_marco

    def en_el_anillo(y):
        # x a mitad del anillo a esa altura, en cada lado: las uniones del
        # zigzag van ahí, siempre tapadas, también en las esquinas redondas.
        oa, ob = _extremos_en(marco, r_marco, y)
        ia, ib = _extremos_en(pant, r_pant, y)
        return (oa + ia) / 2, (ob + ib) / 2

    filas = []
    y = pant.y0 + paso / 2
    while y < pant.y1 - 1:
        filas.append(y)
        y += paso
    zigzag = []
    for k, y in enumerate(filas):
        a, b = en_el_anillo(y)
        zigzag += [a, y, b, y] if k % 2 == 0 else [b, y, a, y]
    if len(zigzag) >= 4:
        figuras.append({"tipo": "line", "coords": zigzag,
                        "kw": {"fill": p.barrido, "width": 1, "capstyle": "butt",
                               "joinstyle": "miter"}})
    # El marco del tubo, ENCIMA: un anillo (contorno exterior y, al revés,
    # el interior) por bandas. Tapa las uniones del barrido y deja ver el tubo.
    exterior = _redondeado(marco, r_pant + grueso_marco)
    interior = _redondeado(pant, r_pant)
    pares_int = [(interior[i], interior[i + 1]) for i in range(0, len(interior), 2)][::-1]
    anillo = exterior + exterior[:2] + [v for par in pares_int + pares_int[:1] for v in par]
    figuras += _bandas(anillo, marco, 4, mezclar(oscuro, claro, 0.15),
                       mezclar(oscuro, detalle, 0.55))
    # Columna derecha: dos mandos (círculos concéntricos con muesca) y rejilla.
    col_x = (pant.x1 + H * 0.035 + caja.x1) / 2
    r_mando = min(H * 0.075, (caja.x1 - pant.x1) * 0.32)
    for i, y_mando in enumerate((caja.y0 + H * 0.24, caja.y0 + H * 0.45)):
        figuras.append(_circulo(col_x, y_mando, r_mando, detalle))
        figuras.append(_circulo(col_x, y_mando, r_mando * 0.80, mezclar(oscuro, claro, 0.35)))
        figuras.append(_circulo(col_x, y_mando, r_mando * 0.55, mezclar(claro, oscuro, 0.15)))
        angulo = math.radians(-50 - 70 * i)
        figuras.append(_linea([col_x, y_mando, col_x + r_mando * 0.75 * math.cos(angulo),
                               y_mando + r_mando * 0.75 * math.sin(angulo)],
                              detalle, max(2.0, r_mando * 0.14)))
    rejilla_w = r_mando * 1.1
    for k in range(6):
        y_linea = caja.y0 + H * (0.61 + 0.032 * k)
        figuras.append(_linea([col_x - rejilla_w, y_linea, col_x + rejilla_w, y_linea],
                              detalle, max(1.5, H * 0.012), cap="butt"))
    # Franja inferior: dos botones pequeños, uno gris y uno rojo.
    y_boton = (pant.y1 + H * 0.035 + caja.y1) / 2
    lado = H * 0.045
    for k, color in enumerate((mezclar(claro, detalle, 0.45), acento)):
        x_boton = col_x - lado * 1.3 + k * lado * 1.5
        b = Caja(x_boton - lado * 0.6, y_boton - lado * 0.45, x_boton + lado * 0.6,
                 y_boton + lado * 0.45)
        figuras.append(_poligono(_redondeado(b, lado * 0.15), color, detalle, 1))
    return figuras


# -------------------------------------------------------------------- cápsula
def _capsula(caja: Caja, m, p) -> list[dict]:
    H, W = caja.alto, caja.ancho
    claro, oscuro, filo, detalle = p.mueble_claro, p.mueble_oscuro, p.mueble_filo, p.mueble_detalle
    figuras: list[dict] = []
    # Auriculares: discos redondos y compactos, casi todo detrás de la
    # carcasa; solo asoma un creciente de `asoma` por cada lado.
    r_oreja, asoma = H * 0.19, H * 0.065
    x_oreja = W / 2 - (r_oreja - asoma)
    # Antenas: varillas finas que salen de detrás de los auriculares, con bola.
    for signo in (-1, 1):
        x_base = caja.cx + signo * (W / 2 + asoma * 0.45)
        x_tope = caja.cx + signo * (W / 2 + asoma * 0.75)
        y_tope = caja.y0 - H * m.antena + H * 0.035
        figuras.append(_linea([x_base, caja.cy - r_oreja * 0.4, x_tope, y_tope],
                              mezclar(claro, detalle, 0.45), max(2.0, H * 0.016)))
        figuras.append(_circulo(x_tope, y_tope, H * 0.03, claro, detalle, 1))
    for signo in (-1, 1):
        x = caja.cx + signo * x_oreja
        figuras.append(_circulo(x, caja.cy, r_oreja, detalle))
        figuras.append(_circulo(x, caja.cy, r_oreja - asoma * 0.35, mezclar(detalle, claro, 0.35)))
        figuras.append(_circulo(x, caja.cy, r_oreja - asoma * 0.7, mezclar(detalle, oscuro, 0.25)))
    # Carcasa crema, cuadrada y muy redondeada: bandas y filo de luz.
    contorno = _redondeado(caja, H * m.radio)
    figuras += _bandas(contorno, caja, m.bandas, claro, oscuro)
    figuras.append(_filo_de_luz(caja, H * m.radio, filo))
    # Pantalla con un marco GRUESO beige-tostado, con su filo oscuro fuera
    # y una línea clara dentro: el bisel de la referencia, en tres bandas.
    pant = caja_pantalla(caja, m)
    r_pant = pant.alto * m.radio_pantalla
    for grosor, color in ((0.042, mezclar(detalle, oscuro, 0.35)),
                          (0.036, mezclar(detalle, claro, 0.35)),
                          (0.012, detalle)):
        g = H * grosor
        marco = Caja(pant.x0 - g, pant.y0 - g, pant.x1 + g, pant.y1 + g)
        figuras.append(_poligono(_redondeado(marco, r_pant + g), color))
    figuras.append(_poligono(_redondeado(pant, r_pant), p.pantalla))
    return figuras


def figuras(tipo: str, caja: Caja, mueble, paleta) -> list[dict]:
    if tipo == "tele":
        return _tele(caja, mueble, paleta)
    if tipo == "capsula":
        return _capsula(caja, mueble, paleta)
    raise ValueError(f"Mueble sin dibujo: {tipo!r}")


def extension(lista: list[dict]) -> Caja:
    """La caja que ocupan las figuras (con medio grosor de las líneas)."""
    xs, ys = [], []
    for f in lista:
        co = f["coords"]
        extra = float(f["kw"].get("width", 1)) / 2 if f["tipo"] == "line" else 0.0
        xs += [min(co[0::2]) - extra, max(co[0::2]) + extra]
        ys += [min(co[1::2]) - extra, max(co[1::2]) + extra]
    return Caja(min(xs), min(ys), max(xs), max(ys))


def dibujar(lienzo, lista: list[dict]) -> list[int]:
    """Crea las figuras UNA vez. Etiquetas: «rostro» y «mueble»."""
    items = []
    for f in lista:
        crear = {"polygon": lienzo.create_polygon, "line": lienzo.create_line,
                 "oval": lienzo.create_oval}[f["tipo"]]
        items.append(crear(*f["coords"], tags=("rostro", ETIQUETA), **f["kw"]))
    return items
