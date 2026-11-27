"""Cómo se ve la configuración: pantalla completa superpuesta, en dos niveles.

En 800×480 no cabe una barra lateral con siete secciones y sus filas, así
que: inicio con las siete secciones en mosaico (4 + 3, botones grandes para
el dedo) y, al tocar una, su página de filas (etiqueta a la izquierda,
«‹ valor ›» a la derecha). Cabecera fija con «‹ Volver» y «✕». Lo mismo con
teclado: flechas, ENTER, RETROCESO y Esc.

Cada texto va en una CAJA y se MIDE antes de darlo por bueno (como los de la
pantalla principal): si no cabe, baja la letra; si ni con la mínima cabe, se
recorta con «…». Así ningún texto se sale de su caja ni pisa a otro.

Solo dibuja y dice qué hay bajo un toque (`objetivo_en`); no decide nada.
"""
from __future__ import annotations

from . import configuracion as conf
from .disposicion_textos import FUENTE, LETRA_MINIMA
from .rostro.paleta import mezclar

ETIQUETA = "configuracion"
RELLENO = 6            # px entre el borde de una caja y su texto
SEPARACION = 6         # px entre filas


class VistaConfiguracion:
    def __init__(self, lienzo) -> None:
        self.lienzo = lienzo
        self._zonas: list[tuple[tuple[float, float, float, float], tuple]] = []
        # (item de texto, caja que no puede rebasar): lo comprueban las pruebas.
        self.cajas_texto: list[tuple[int, tuple[float, float, float, float]]] = []
        self._firma = None
        self.visible = False

    # ------------------------------------------------------------------ toque
    def objetivo_en(self, x: float, y: float) -> tuple | None:
        for (x0, y0, x1, y1), objetivo in reversed(self._zonas):
            if x0 <= x <= x1 and y0 <= y <= y1:
                return objetivo
        return None

    def ocultar(self) -> None:
        self.lienzo.delete(ETIQUETA)
        self._zonas.clear()
        self.cajas_texto.clear()
        self._firma = None
        self.visible = False

    # ----------------------------------------------------------------- dibujo
    def dibujar(self, menu: conf.Menu, ancho: int, alto: int, paleta, info) -> None:
        firma = (ancho, alto, menu.pagina, menu.seccion, menu.fila, menu.nota,
                 menu.texto, tuple(sorted((k, repr(v)) for k, v in menu.valores.items())),
                 tuple(info(f.clave) for f in menu.filas if isinstance(f, conf.Info)), paleta)
        if firma == self._firma:
            return
        self._firma = firma
        self.lienzo.delete(ETIQUETA)
        self._zonas.clear()
        self.cajas_texto.clear()
        self.visible = True
        self._p, self._lado = paleta, min(ancho, alto)
        self.lienzo.create_rectangle(0, 0, ancho, alto, fill=paleta.fondo, outline="",
                                     tags=(ETIQUETA,))
        cabecera = max(48.0, alto * 0.12)
        nota_alto = max(30.0, alto * 0.075)
        volver = (8, 6, max(150.0, ancho * 0.19), cabecera - 6)
        cerrar = (ancho - max(60.0, cabecera), 6, ancho - 8, cabecera - 6)
        titulo = {conf.INICIO: "Configuración",
                  conf.SECCION: menu.catalogo[menu.seccion][0],
                  conf.TEXTO: menu.texto[0]}[menu.pagina]
        self._texto((volver[2] + 8, 0, cerrar[0] - 8, cabecera), titulo, 0.05, paleta.tinta)
        if menu.pagina != conf.INICIO:
            self._boton(volver, "‹ Volver", ("volver",), 0.036)
        self._boton(cerrar, "✕", ("cerrar",), 0.05)
        cuerpo = (cabecera + 4, alto - nota_alto)
        if menu.pagina == conf.INICIO:
            self._inicio(menu, ancho, cuerpo)
        elif menu.pagina == conf.SECCION:
            self._seccion(menu, ancho, cuerpo, info)
        else:
            self._pagina_texto(menu, ancho, cuerpo)
        if menu.nota:
            self._texto((12, alto - nota_alto, ancho - 12, alto - 2), menu.nota, 0.028,
                        paleta.ojos_atento)

    # ---------------------------------------------------------- texto medido
    def _texto(self, caja, texto, tamano, color, ancla="center") -> int:
        """Texto dentro de `caja` (x0, y0, x1, y1), medido: si no cabe, baja la
        letra; con la mínima, se recorta con «…»."""
        x0, y0, x1, y1 = caja
        ancho, alto = max(1.0, x1 - x0 - 2 * RELLENO), max(1.0, y1 - y0)
        x = {"center": (x0 + x1) / 2, "w": x0 + RELLENO, "e": x1 - RELLENO}[ancla]
        justificado = {"center": "center", "w": "left", "e": "right"}[ancla]
        letra = max(LETRA_MINIMA, int(self._lado * tamano))
        item = self.lienzo.create_text(
            x, (y0 + y1) / 2, text=texto, fill=color, anchor=ancla, justify=justificado,
            width=int(ancho), font=(FUENTE, letra), tags=(ETIQUETA,))
        while not self._cabe(item, ancho, alto):
            if letra > LETRA_MINIMA:
                letra -= 1
                self.lienzo.itemconfigure(item, font=(FUENTE, letra))
                continue
            actual = self.lienzo.itemcget(item, "text")
            if len(actual) <= 2:
                break
            self.lienzo.itemconfigure(item, text=actual[:-2].rstrip() + "…")
        self.cajas_texto.append((item, (x0, y0, x1, y1)))
        return item

    def _cabe(self, item, ancho, alto) -> bool:
        caja = self.lienzo.bbox(item)
        if not caja:
            return True
        return caja[2] - caja[0] <= ancho + 2 and caja[3] - caja[1] <= alto

    def _boton(self, caja, texto, objetivo, tamano=0.034, foco=False):
        p = self._p
        x0, y0, x1, y1 = caja
        self.lienzo.create_rectangle(
            x0, y0, x1, y1, fill=mezclar(p.fondo, p.tinta, 0.10),
            outline=p.ojos_atento if foco else mezclar(p.fondo, p.tinta, 0.25),
            width=3 if foco else 1, tags=(ETIQUETA,))
        self._texto((x0 + 2, y0 + 2, x1 - 2, y1 - 2), texto, tamano, p.tinta)
        self._zonas.append((caja, objetivo))

    # --------------------------------------------------------------- páginas
    def _inicio(self, menu, ancho, cuerpo):
        n = len(menu.catalogo)
        columnas = 4 if ancho >= 640 else 2
        filas = -(-n // columnas)
        margen = 10
        y0, y1 = cuerpo
        w = (ancho - margen * (columnas + 1)) / columnas
        h = (y1 - y0 - margen * (filas + 1)) / filas
        for i, (nombre, _) in enumerate(menu.catalogo):
            fila, col = divmod(i, columnas)
            x = margen + col * (w + margen)
            y = y0 + margen + fila * (h + margen)
            self._boton((x, y, x + w, y + h), nombre, ("seccion", i), 0.034,
                        foco=i == menu.fila)

    def _seccion(self, menu, ancho, cuerpo, info):
        p, filas = self._p, menu.filas
        y0, y1 = cuerpo
        if any(isinstance(f, conf.Ajuste) and f.reinicio for f in filas):
            leyenda = 22.0
            self._texto((12, y1 - leyenda, ancho - 12, y1), "⟳ se aplica al reiniciar",
                        0.024, p.tenue, ancla="w")
            y1 -= leyenda
        alto_fila = min(68.0, (y1 - y0) / max(1, len(filas)))
        x_valor = ancho * 0.52
        for i, fila in enumerate(filas):
            top = y0 + i * alto_fila + SEPARACION / 2
            bottom = y0 + (i + 1) * alto_fila - SEPARACION / 2
            if i == menu.fila:
                self.lienzo.create_rectangle(4, top - 2, ancho - 4, bottom + 2,
                                             outline=p.ojos_atento, width=2, tags=(ETIQUETA,))
            self._texto((10, top, x_valor - 8, bottom), fila.etiqueta, 0.034, p.tinta, ancla="w")
            derecha = ancho - 14
            if isinstance(fila, conf.Ajuste):
                boton = min(60.0, max(44.0, bottom - top))
                self._boton((x_valor, top, x_valor + boton, bottom), "‹", ("menos", i), 0.045)
                self._boton((derecha - boton, top, derecha, bottom), "›", ("mas", i), 0.045)
                texto = menu.valor_texto(fila) + ("  ⟳" if fila.reinicio else "")
                caja = (x_valor + boton + 4, top, derecha - boton - 4, bottom)
                self._texto(caja, texto, 0.032, p.ojos_atento)
                self._zonas.append((caja, ("mas", i)))
            elif isinstance(fila, conf.Accion):
                self._boton((x_valor, top, derecha, bottom), fila.texto_boton, ("fila", i),
                            foco=i == menu.fila)
            elif fila.ver:
                self._boton((x_valor, top, derecha, bottom), "Ver ›", ("fila", i),
                            foco=i == menu.fila)
            else:
                self._texto((x_valor, top, derecha, bottom), info(fila.clave), 0.028,
                            p.tenue, ancla="e")

    def _pagina_texto(self, menu, ancho, cuerpo):
        """Las líneas, de arriba abajo; si no caben todas, letra más pequeña."""
        lineas = menu.texto[1] or ("",)
        y0, y1 = cuerpo
        tamano = 0.03
        while True:
            alto_linea = max(LETRA_MINIMA, int(self._lado * tamano)) * 1.6
            if alto_linea * len(lineas) <= y1 - y0 - 8 or tamano <= 0.016:
                break
            tamano -= 0.002
        alto_linea = min(alto_linea, (y1 - y0 - 8) / len(lineas))
        for i, linea in enumerate(lineas):
            top = y0 + 4 + i * alto_linea
            self._texto((16, top, ancho - 16, top + alto_linea), linea, tamano,
                        self._p.tinta, ancla="w")
