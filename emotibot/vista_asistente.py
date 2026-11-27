"""Cómo se ve el asistente de perfil: textos arriba y abajo del rostro REAL.

El rostro que se elige es la cara de la aplicación, dibujada con su perfil
(no un nombre ni una miniatura). Los textos van en las dos franjas que deja
libres (`Cara.limites_verticales()`), como los de la aplicación, así que no
la pisan. Solo lee el estado de `asistente.Asistente`: la navegación no está
aquí.
"""
from __future__ import annotations

from . import asistente as mod
from .disposicion_textos import FUENTE, LETRA_MINIMA

CLAVES = ("titulo", "subtitulo", "opcion", "descripcion", "teclas")
# Letra (fracción de min(ancho, alto)) y posición dentro de su franja.
TAMANO = {"titulo": 0.046, "subtitulo": 0.024, "opcion": 0.042,
          "descripcion": 0.025, "teclas": 0.022}
POSICION = {"titulo": 0.36, "subtitulo": 0.76,
            "opcion": 0.24, "descripcion": 0.53, "teclas": 0.83}
ARRIBA = ("titulo", "subtitulo")

TECLAS_PASO = ("← →  cambiar   ·   ENTER  elegir   ·   RETROCESO  atrás   ·   "
               "Esc  salir guardando lo elegido")
TITULOS = {"rostro": "Elige mi cara", "voz": "Elige mi voz",
           "personalidad": "Elige mi personalidad", "estilo": "Elige mi estilo"}


def contenidos(a: mod.Asistente, nombre_robot: str, nota: str = "") -> dict[str, str]:
    """Qué dice cada texto en el estado actual del asistente."""
    if a.paso == mod.INICIO:
        if a.primer_arranque:
            return {
                "titulo": f"¡Hola! Soy {nombre_robot}.",
                "subtitulo": "Antes de empezar: ¿me quieres como vengo o a tu gusto?",
                "opcion": "ENTER   empezar ya, con lo estándar",
                "descripcion": "P   elegir mi cara, mi voz, mi personalidad y mi estilo",
                "teclas": "Esc  salir (me quedo con lo estándar)",
            }
        return {
            "titulo": "Cambiar mi perfil",
            "subtitulo": "Puedes volver a lo estándar o elegir de nuevo.",
            "opcion": "ENTER   volver a lo estándar",
            "descripcion": "P   elegir mi cara, mi voz, mi personalidad y mi estilo",
            "teclas": "Esc  dejarlo como está",
        }
    if a.paso not in mod.PASOS:
        return {clave: "" for clave in CLAVES}
    eje = a.paso
    lista = a.opciones[eje]
    posicion = f"{a.indice[eje] + 1} de {len(lista)}"
    subtitulo = f"Paso {a.numero_paso} de {len(mod.PASOS)}"
    if eje == "rostro":
        # El rostro se elige VIÉNDOLO: sin nombre.
        opcion, descripcion = f"‹    {posicion}    ›", "Así me verás."
    else:
        opcion = f"‹    {mod.titulo(a.actual())}    ›"
        subtitulo += f"  ·  {posicion}"
        if eje == "voz":
            descripcion = nota or "Escucha: hablo con esa voz al elegirla."
        else:
            descripcion = mod.descripcion(eje, a.actual())
    return {"titulo": TITULOS[eje], "subtitulo": subtitulo, "opcion": opcion,
            "descripcion": descripcion, "teclas": TECLAS_PASO}


class VistaAsistente:
    def __init__(self, lienzo) -> None:
        self.lienzo = lienzo
        self._items: dict[str, int] = {}
        self._firma = None

    def dibujar(self, a: mod.Asistente, ancho: int, alto: int,
                franja: tuple[float, float], paleta, nombre_robot: str,
                nota: str = "") -> None:
        textos = contenidos(a, nombre_robot, nota)
        firma = (ancho, alto, tuple(franja), tuple(sorted(textos.items())), paleta)
        if firma == self._firma:
            return
        self._firma = firma
        lado = min(ancho, alto)
        arriba, abajo = franja
        colores = {"titulo": paleta.tinta, "subtitulo": paleta.tenue,
                   "opcion": paleta.ojos_atento, "descripcion": paleta.tinta,
                   "teclas": paleta.tenue}
        for clave in CLAVES:
            if clave in ARRIBA:
                y = arriba * POSICION[clave]
            else:
                y = abajo + (alto - abajo) * POSICION[clave]
            if clave not in self._items:
                self._items[clave] = self.lienzo.create_text(
                    0, 0, text="", anchor="center", justify="center",
                    tags=("asistente",))
            item = self._items[clave]
            self.lienzo.coords(item, ancho / 2, y)
            self.lienzo.itemconfigure(
                item, text=textos[clave], fill=colores[clave], state="normal",
                width=int(ancho * 0.94),
                font=(FUENTE, max(LETRA_MINIMA, int(lado * TAMANO[clave]))))

    def ocultar(self) -> None:
        for item in self._items.values():
            self.lienzo.itemconfigure(item, state="hidden")
        self._firma = None
