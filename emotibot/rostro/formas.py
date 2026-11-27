"""Formas que Tkinter no trae de serie.

El lienzo de Tkinter no sabe dibujar un rectángulo redondeado, que es la
figura de la que está hecho el robot: la carcasa, la pantalla, las orejas, los
ojos y la boca. Aquí se genera como lista plana de coordenadas, lista para
`create_polygon`, y se puede rotar entera para inclinar la cabeza.
"""
from __future__ import annotations

import math

# Segmentos por esquina. Con 7 el faceteado se nota: la carcasa tiene un
# radio grande y la flecha de cada cuerda llega a ser de un píxel. Son cuatro
# figuras por fotograma, así que subirlo no cuesta nada medible.
PASOS_ESQUINA = 16


def rotar(x: float, y: float, cx: float, cy: float, grados: float) -> tuple[float, float]:
    if abs(grados) < 0.01:
        return x, y
    radianes = math.radians(grados)
    seno, coseno = math.sin(radianes), math.cos(radianes)
    dx, dy = x - cx, y - cy
    return cx + dx * coseno - dy * seno, cy + dx * seno + dy * coseno


def rectangulo_redondeado(
    x0: float, y0: float, x1: float, y1: float, radio: float,
    centro: tuple[float, float] | None = None, inclinacion: float = 0.0,
    pasos: int = PASOS_ESQUINA,
) -> list[float]:
    """Contorno de un rectángulo de esquinas redondeadas.

    Devuelve coordenadas planas [x0, y0, x1, y1, …] para `create_polygon`.
    Con `centro` e `inclinacion` el resultado sale ya girado, que es como se
    inclina la cabeza sin recalcular nada.
    """
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0
    radio = max(0.0, min(radio, (x1 - x0) / 2, (y1 - y0) / 2))
    cx, cy = centro if centro else ((x0 + x1) / 2, (y0 + y1) / 2)

    esquinas = (
        (x1 - radio, y0 + radio, -90.0),   # superior derecha
        (x1 - radio, y1 - radio, 0.0),     # inferior derecha
        (x0 + radio, y1 - radio, 90.0),    # inferior izquierda
        (x0 + radio, y0 + radio, 180.0),   # superior izquierda
    )
    puntos: list[float] = []
    for ex, ey, inicio in esquinas:
        for paso in range(pasos + 1):
            angulo = math.radians(inicio + 90.0 * paso / pasos)
            px = ex + radio * math.cos(angulo)
            py = ey + radio * math.sin(angulo)
            px, py = rotar(px, py, cx, cy, inclinacion)
            puntos.extend((px, py))
    return puntos


def arco(
    cx: float, cy: float, ancho: float, altura: float,
    centro: tuple[float, float] | None = None, inclinacion: float = 0.0,
    sesgo: float = 0.0, puntos: int = 12,
) -> list[float]:
    """Arco suave centrado en (cx, cy).

    `altura` positiva curva hacia arriba. `sesgo` inclina el arco de un
    extremo al otro: con una sola ceja continua, es lo que permite que la
    expresión siga leyéndose como preocupación o curiosidad.
    """
    base = centro if centro else (cx, cy)
    salida: list[float] = []
    for indice in range(puntos + 1):
        fraccion = indice / puntos
        x = cx - ancho / 2 + ancho * fraccion
        curva = math.sin(math.pi * fraccion)
        y = cy - altura * curva + sesgo * (fraccion - 0.5)
        px, py = rotar(x, y, base[0], base[1], inclinacion)
        salida.extend((px, py))
    return salida
