"""Barra lateral del directorio de ayuda.

Se abre con la tecla A o cuando alguien pide los números hablando, y es la
única interfaz del directorio. No comparte nada con la ruta de crisis (que
solo habla) ni con la línea de avisos del borde inferior, donde vive
«Revisa config/crisis.json».

Va a la derecha, sobre un fondo opaco, y ocupa en vertical la MISMA franja
que el rostro (`Cara.limites_verticales()`): los textos de la aplicación,
también la línea del aviso, quedan siempre fuera de esa franja, así que la
barra no puede pisarlos. Con carcasa cae junto a la oreja derecha; sin
carcasa, o en ventanas 4:3, tapa el lado derecho de la cara mientras está
abierta. Si su contenido no cabe, la letra se reduce. Cada entrada dice la SITUACIÓN («peligro ahora
mismo»), el número tal cual se marca y su horario; una línea fuera de
horario va al final y lo dice.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from .dialogo import horario as mod_horario
from .dialogo.directorio import NO_PUEDO_LLAMAR, Directorio

ETIQUETA = "directorio"
SEGUNDOS_SI_SE_PIDE_HABLANDO = 90.0


@dataclass(frozen=True)
class Entrada:
    etiqueta: str
    numero: str
    detalle: str
    abierta: bool


def entradas_panel(directorio: Directorio, hora: dt.time) -> list[Entrada]:
    """Lo que muestra la barra, en orden: abiertas primero, cerradas al final."""
    salida = []
    for linea, abierta in directorio.entradas(hora):
        partes = [mod_horario.describir(linea.horario)]
        if linea.idiomas:
            partes.append(linea.idiomas)
        if not abierta:
            partes.append("ahora fuera de horario")
        salida.append(Entrada(linea.etiqueta, linea.numero, " · ".join(partes), abierta))
    return salida


class PanelDirectorio:
    def __init__(self, lienzo, paleta, directorio: Directorio) -> None:
        self.lienzo = lienzo
        self.paleta = paleta
        self.directorio = directorio
        self.visible = False
        self._hasta: float | None = None          # cierre automático (monotonic)
        self._firma = None                         # qué hay dibujado

    # --------------------------------------------------------------- estado
    def mostrar(self, segundos: float | None = None, ahora: float = 0.0) -> None:
        self.visible = True
        self._hasta = (ahora + segundos) if segundos else None
        self._firma = None

    def ocultar(self) -> None:
        self.visible = False
        self._hasta = None
        self._borrar()

    def alternar(self) -> None:
        self.ocultar() if self.visible else self.mostrar()

    # --------------------------------------------------------------- dibujo
    def _borrar(self) -> None:
        self.lienzo.delete(ETIQUETA)
        self._firma = None

    def actualizar(self, ancho: int, alto: int, ahora: float,
                   hora: dt.time | None = None,
                   franja: tuple[float, float] | None = None) -> None:
        """Llamar en cada fotograma. Solo redibuja si cambia algo.

        `franja`: (arriba, abajo) que puede ocupar; por defecto, del 12 % al
        88 % del alto.
        """
        if self.visible and self._hasta is not None and ahora >= self._hasta:
            self.ocultar()
        if not self.visible:
            return
        hora = hora or self.directorio.hora()
        entradas = entradas_panel(self.directorio, hora)
        franja = franja or (alto * 0.12, alto * 0.88)
        firma = (ancho, alto, tuple(entradas), franja)
        if firma == self._firma:
            return
        factor = 1.0
        while True:
            self._borrar()
            fondo = self._dibujar(ancho, alto, entradas, franja, factor)
            if fondo <= franja[1] or factor < 0.45:
                break
            factor *= 0.9
        self._firma = firma

    def _dibujar(self, ancho: int, alto: int, entradas: list[Entrada],
                 franja: tuple[float, float], factor: float) -> float:
        """Dibuja la barra; devuelve dónde acabó el contenido."""
        lienzo, p = self.lienzo, self.paleta
        escala = min(ancho, alto) * factor
        w = min(max(ancho * 0.22, 210.0), ancho * 0.34)
        x0, x1 = ancho - w - ancho * 0.012, ancho - ancho * 0.012
        y0, y1 = franja
        lienzo.create_polygon(x0, y0, x1, y0, x1, y1, x0, y1, fill=p.fondo,
                              outline=p.tenue, width=2, tags=ETIQUETA)
        margen = w * 0.08
        x, ancho_texto = x0 + margen, w - 2 * margen
        y = y0 + margen

        def texto(contenido, color, tamano, negrita=False, separacion=1.5):
            nonlocal y
            item = lienzo.create_text(
                x, y, text=contenido, fill=color, anchor="nw",
                width=int(ancho_texto), tags=ETIQUETA,
                font=("DejaVu Sans", max(8, int(tamano)), "bold" if negrita else "normal"))
            caja = lienzo.bbox(item) if hasattr(lienzo, "bbox") else None
            if caja:
                # Medida real: lo que ocupa de verdad, con sus líneas.
                y = caja[3] + tamano * (separacion - 1.0)
            else:
                lineas = 1 + int(len(contenido) * tamano * 0.6 > ancho_texto * 1.3)
                y += tamano * separacion * lineas

        texto("Números de ayuda", p.tinta, escala * 0.032, negrita=True)
        texto(self.directorio.pais or "", p.tenue, escala * 0.020, separacion=2.2)
        if not entradas:
            texto(self.directorio.motivo_vacio or "No tengo números configurados.",
                  p.tinta, escala * 0.022, separacion=2.0)
        for entrada in entradas:
            color = p.tinta if entrada.abierta else p.tenue
            texto(entrada.etiqueta, color, escala * 0.022, separacion=1.4)
            texto(entrada.numero, p.ojos_atento if entrada.abierta else p.tenue,
                  escala * 0.048, negrita=True, separacion=1.35)
            texto(entrada.detalle, p.tenue, escala * 0.018, separacion=2.4)
        texto(NO_PUEDO_LLAMAR + " Márcalo tú.", p.tinta, escala * 0.020)
        texto("A para cerrar", p.tenue, escala * 0.017, separacion=1.0)
        if hasattr(lienzo, "tag_raise"):
            lienzo.tag_raise(ETIQUETA)
        return y + margen
