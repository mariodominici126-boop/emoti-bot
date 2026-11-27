"""Ventana del prototipo: rostro A (producción) y B (Pillow), lado a lado o
alternados, sobre el MISMO Canvas de Tkinter y con la misma animación.

No abre micrófono ni altavoz, ni llama a ninguna IA. La «voz» de la tecla V
es una envolvente de DEMOSTRACIÓN para ver la boca: el robot real usa la
envolvente del audio que suena.

Teclas:
  1 reposo · 2 escuchando · 3 pensando · 4 hablando · 5 feliz · 6 curioso ·
  7 preocupado
  B alterna A (producción) / B (Pillow)   V voz de demostración
  S supermuestreo ×1/×2                   Esc salir
"""
from __future__ import annotations

import math
import time
import tkinter as tk

from PIL import ImageTk

from emotibot.rostro import PALETA, Cara

from .animador import Animador
from .expresiones import EXPRESIONES_C4  # noqa: F401  (se reexporta)
from .render import RostroPillow


class VentanaPrototipo:
    def __init__(self, ancho: int = 900, alto: int = 560, fps: int = 30) -> None:
        self.raiz = tk.Tk()
        self.raiz.title("EMOTI-BOT · prototipo de rostro (Fase 1C)")
        self.raiz.geometry(f"{ancho}x{alto}")
        self.lienzo = tk.Canvas(self.raiz, bg=PALETA.fondo, highlightthickness=0)
        self.lienzo.pack(fill="both", expand=True)
        self.fps = fps
        self.motor = "B"
        self.supermuestreo = 2
        self.voz = False
        self.nombre = "reposo"

        self.animador = Animador()
        self.cara_a = Cara(self.lienzo, PALETA)       # producción, sin cambios
        self._rostro: RostroPillow | None = None
        self._foto: ImageTk.PhotoImage | None = None
        self._item = self.lienzo.create_image(0, 0, anchor="nw")
        self._texto = self.lienzo.create_text(10, 10, anchor="nw", fill=PALETA.tenue,
                                              font=("DejaVu Sans", 10))
        self._tiempos: list[float] = []
        self.raiz.bind("<Key>", self._tecla)
        self._fijar("reposo")

    def _fijar(self, nombre: str) -> None:
        self.nombre = nombre
        funcional, expresion = EXPRESIONES_C4[nombre]
        self.animador.fijar(funcional=funcional, expresion=expresion)
        self.cara_a.fijar(funcional=funcional, expresion=expresion)

    def _tecla(self, evento) -> None:
        c = (evento.char or "").lower()
        if evento.keysym == "Escape":
            self.raiz.destroy()
        elif c in "1234567" and c:
            self._fijar(list(EXPRESIONES_C4)[int(c) - 1])
        elif c == "b":
            self.motor = "A" if self.motor == "B" else "B"
            self.lienzo.delete("rostro")             # A recrea sus figuras
            self.cara_a._creado = False
            self.cara_a._geo.ancho = 0
        elif c == "v":
            self.voz = not self.voz
        elif c == "s":
            self.supermuestreo = 1 if self.supermuestreo == 2 else 2
            self._rostro = None

    def _nivel_demo(self, t: float) -> float:
        if not self.voz:
            return 0.0
        return max(0.0, 0.55 + 0.45 * math.sin(t * 17) * math.sin(t * 3.3))

    def _pintar(self) -> None:
        inicio = time.perf_counter()
        ancho = max(self.lienzo.winfo_width(), 320)
        alto = max(self.lienzo.winfo_height(), 240)
        t = time.monotonic()
        nivel = self._nivel_demo(t)
        escucha = 0.5 + 0.4 * math.sin(t * 6)

        if self.motor == "A":
            self.lienzo.itemconfigure(self._item, state="hidden")
            self.cara_a.fijar_nivel_voz(nivel)
            self.cara_a.fijar_nivel_escucha(escucha)
            self.cara_a.dibujar()
        else:
            if (self._rostro is None or self._rostro.geo.ancho != ancho
                    or self._rostro.geo.alto != alto):
                self._rostro = RostroPillow(ancho, alto, supermuestreo=self.supermuestreo)
                self._foto = None
            self.lienzo.itemconfigure("rostro", state="hidden")
            self.animador.fijar_nivel_voz(nivel)
            self.animador.fijar_nivel_escucha(escucha)
            transcurrido = self.animador.avanzar()
            imagen = self._rostro.cuadro(self.animador.anim, self.animador.expresion,
                                         transcurrido)
            if self._foto is None or (self._foto.width(), self._foto.height()) != imagen.size:
                self._foto = ImageTk.PhotoImage(imagen)
                self.lienzo.itemconfigure(self._item, image=self._foto)
            else:
                self._foto.paste(imagen)            # reutiliza la textura
            self.lienzo.itemconfigure(self._item, state="normal")

        self._tiempos.append((time.perf_counter() - inicio) * 1000)
        self._tiempos = self._tiempos[-60:]
        media = sum(self._tiempos) / len(self._tiempos)
        self.lienzo.itemconfigure(
            self._texto,
            text=(f"{'A producción' if self.motor == 'A' else 'B Pillow ×' + str(self.supermuestreo)}"
                  f" · {self.nombre} · {media:.1f} ms/cuadro · "
                  "1-7 expresión · B motor · V voz demo · S supermuestreo"))
        self.lienzo.tag_raise(self._texto)
        self.raiz.after(max(1, int(1000 / self.fps)), self._pintar)

    def ejecutar(self) -> None:
        self._pintar()
        self.raiz.mainloop()
