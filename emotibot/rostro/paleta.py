"""Paleta del rostro y mezcla de colores.

El lienzo de Tkinter no tiene canal alfa: no se puede dibujar nada
semitransparente. La solución es premezclar el color con el fondo, que es lo
que hace `mezclar()`. Así se consiguen los tonos intermedios —cejas algo más
apagadas que los ojos, el anillo de escucha apareciendo poco a poco— sin
necesidad de transparencia real.
"""
from __future__ import annotations

from dataclasses import dataclass


def _a_rgb(color: str) -> tuple[int, int, int]:
    texto = color.lstrip("#")
    if len(texto) == 3:
        texto = "".join(c * 2 for c in texto)
    return (int(texto[0:2], 16), int(texto[2:4], 16), int(texto[4:6], 16))


def _a_hex(rgb: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(v))) for v in rgb)


def mezclar(color_a: str, color_b: str, proporcion: float) -> str:
    """Interpola entre dos colores. proporcion=0 → color_a, 1 → color_b."""
    t = max(0.0, min(1.0, proporcion))
    a, b = _a_rgb(color_a), _a_rgb(color_b)
    return _a_hex(tuple(a[i] + (b[i] - a[i]) * t for i in range(3)))


def aclarar(color: str, cantidad: float) -> str:
    return mezclar(color, "#ffffff", cantidad)


def oscurecer(color: str, cantidad: float) -> str:
    return mezclar(color, "#000000", cantidad)


@dataclass(frozen=True)
class Paleta:
    """Tonos cálidos sobre un azul profundo: legible de lejos y acogedor.

    El rostro se dibuja directamente sobre `fondo`, sin halo ni disco: los
    rasgos flotan en la pantalla y forman parte del fondo, como en las
    primeras versiones del proyecto.

    Los valores NO están aquí: vienen del perfil de rostro
    (`config/rostro/<nombre>.json`, sección «colores»), que es la única
    fuente de proporciones y colores. Ver perfil.py.
    """

    fondo: str
    tinta: str
    tenue: str

    # Carcasa del robot: el marco claro que rodea la pantalla, y la sombra
    # con la que se dibujan las orejas para que parezcan detrás.
    carcasa: str
    carcasa_sombra: str
    pantalla: str
    pantalla_brillo: str

    ojos: str
    ojos_feliz: str
    ojos_atento: str
    ojos_preocupado: str
    ojos_error: str

    pupila: str
    brillo: str
    boca_interior: str
    lengua: str
    destello: str

    # Mueble estático (tele, cápsula): degradado por bandas de claro a oscuro,
    # filo de luz, detalles (mandos, rejillas, antenas), acento (botón rojo)
    # y líneas de barrido sobre la pantalla. La cabeza de hybrid_balanced no
    # los usa.
    mueble_claro: str
    mueble_oscuro: str
    mueble_filo: str
    mueble_detalle: str
    mueble_acento: str
    barrido: str

    def color_estado(self, clave: str) -> str:
        return {
            "ojos": self.ojos,
            "feliz": self.ojos_feliz,
            "atento": self.ojos_atento,
            "preocupado": self.ojos_preocupado,
            "error": self.ojos_error,
        }.get(clave, self.ojos)


def __getattr__(nombre: str):
    """`PALETA`: los colores del perfil por defecto, cargados al usarse.

    Se resuelve al pedirla (y no al importar este módulo) porque perfil.py
    necesita la clase `Paleta` de aquí para construir el perfil.
    """
    if nombre == "PALETA":
        from .perfil import cargar
        return cargar().colores
    raise AttributeError(nombre)
