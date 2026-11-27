#!/usr/bin/env python3
"""Visor del rostro: una ventana para recorrer las expresiones.

Usa EXACTAMENTE el mismo código de dibujo que la aplicación: crea la cara con
`crear_cara()` —la misma fábrica que emotibot/app.py, con los mismos ajustes
de config/ajustes.json y el mismo perfil de config/rostro/— y la pinta con el
mismo bucle (`fijar_nivel_voz` + `dibujar` a los FPS configurados). Lo que se
ve aquí es lo que se verá en la aplicación; una prueba comprueba que ninguno
de los dos crea la cara por otro camino.

Teclas:
    → / ESPACIO   siguiente expresión          ←   anterior
    C             con carcasa / sin carcasa
    H             hablar (voz de demostración: mueve solo la boca)
    M             micrófono REAL encendido / apagado (la cara pasa a escuchar)
    P             volver a leer el perfil del disco (para probar variantes)
    F11           pantalla completa            Esc / Q   salir

Las barras del micrófono solo existen con el micrófono REAL abierto (tecla
M), igual que en la aplicación: abrir el micrófono ES pasar a «escuchando».
Su altura es el nivel real, con el mismo cálculo que la captura de la
aplicación; el visor no se inventa una captura. Mientras M está activo, se
ve arriba a la izquierda el NIVEL numérico en vivo, para comprobar que el
sonido llega. El audio no se guarda.

Con --svg escribe además la lámina SVG de antes, sin entorno gráfico, con la
misma clase `Cara` sobre un lienzo que escribe SVG.

Uso:
    python bin/vista_previa_rostro.py                       # ventana
    python bin/vista_previa_rostro.py --svg                 # lámina SVG
    python bin/vista_previa_rostro.py --svg -o cara.svg reposo feliz
"""
from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import dataclasses  # noqa: E402
import threading  # noqa: E402

from emotibot import ajustes as mod_ajustes  # noqa: E402
from emotibot.rostro import crear_cara, perfil as mod_perfil  # noqa: E402
from emotibot.rostro.estados import EXPRESIONES  # noqa: E402

ANCHO = 420
ALTO = 380
COLUMNAS = 3
FOTOGRAMAS = 46          # suficiente para que las transiciones se asienten

# Nivel de voz con el que se dibuja cada estado, para que la boca se vea
# como se verá de verdad cuando el altavoz esté sonando.
NIVEL_VOZ = {
    "hablando": 0.85,
    "respirando_exhalar": 0.45,
}


def _pares(coords):
    return [(coords[i], coords[i + 1]) for i in range(0, len(coords), 2)]


def _esc(texto: str) -> str:
    return (str(texto).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


class LienzoSvg:
    """Imita lo justo de tkinter.Canvas y acumula figuras para volcar a SVG."""

    def __init__(self, ancho: int, alto: int) -> None:
        self._ancho, self._alto = ancho, alto
        self._siguiente = 1
        self.items: dict[int, dict] = {}

    def winfo_width(self) -> int:
        return self._ancho

    def winfo_height(self) -> int:
        return self._alto

    def _crear(self, tipo, coords, kwargs):
        identificador = self._siguiente
        self._siguiente += 1
        self.items[identificador] = {
            "tipo": tipo, "coords": list(coords), "config": dict(kwargs)
        }
        return identificador

    @staticmethod
    def _planas(coords):
        if len(coords) == 1 and isinstance(coords[0], (list, tuple)):
            return list(coords[0])
        return list(coords)

    def create_oval(self, *c, **k):
        return self._crear("oval", c, k)

    def create_arc(self, *c, **k):
        return self._crear("arc", c, k)

    def create_line(self, *c, **k):
        return self._crear("line", self._planas(c), k)

    def create_polygon(self, *c, **k):
        return self._crear("polygon", self._planas(c), k)

    def create_text(self, x, y, **k):
        return self._crear("text", (x, y), k)

    def coords(self, identificador, *valores):
        self.items[identificador]["coords"] = self._planas(valores)

    def itemconfigure(self, identificador, **kwargs):
        self.items[identificador]["config"].update(kwargs)

    itemconfig = itemconfigure

    def delete(self, _etiqueta):
        self.items.clear()
        self._siguiente = 1

    # ------------------------------------------------------------------ volcado
    def a_svg(self, desplazamiento_x: float = 0.0,
              desplazamiento_y: float = 0.0) -> list[str]:
        salida: list[str] = []
        for datos in self.items.values():
            config = datos["config"]
            if config.get("state") == "hidden":
                continue
            relleno = config.get("fill") or "none"
            borde = config.get("outline") or "none"
            grosor = config.get("width", 1)
            puntos = [(x + desplazamiento_x, y + desplazamiento_y)
                      for x, y in _pares(datos["coords"])]
            tipo = datos["tipo"]

            if tipo in ("oval", "arc") and len(puntos) == 2:
                (x0, y0), (x1, y1) = puntos
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                rx, ry = abs(x1 - x0) / 2, abs(y1 - y0) / 2
                if tipo == "arc":
                    # Hay que respetar start/extent: un arco de Tkinter NO es
                    # una elipse completa, y dibujarlo así hacía que las ondas
                    # de escucha parecieran círculos alrededor del rostro.
                    salida.append(
                        f'<path d="{_arco(cx, cy, rx, ry, config)}" '
                        f'fill="none" stroke="{borde}" '
                        f'stroke-width="{grosor}" stroke-linecap="round"/>')
                else:
                    salida.append(
                        f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" rx="{rx:.1f}" '
                        f'ry="{ry:.1f}" fill="{relleno}"/>')
            elif tipo == "line" and len(puntos) >= 2:
                salida.append(
                    f'<path d="{_trazo(puntos, config)}" fill="none" '
                    f'stroke="{relleno}" stroke-width="{grosor}" '
                    f'stroke-linecap="round"/>')
            elif tipo == "polygon" and len(puntos) >= 3:
                salida.append(
                    f'<path d="{_trazo(puntos, config)} Z" fill="{relleno}" '
                    f'stroke="{borde}" stroke-width="{grosor}" '
                    f'stroke-linejoin="round"/>')
            elif tipo == "text":
                tamano = 12
                fuente = config.get("font")
                if isinstance(fuente, (tuple, list)) and len(fuente) >= 2:
                    tamano = int(fuente[1])
                x, y = puntos[0]
                salida.append(
                    f'<text x="{x:.1f}" y="{y:.1f}" fill="{relleno}" '
                    f'font-family="DejaVu Sans, sans-serif" '
                    f'font-size="{tamano}" text-anchor="middle">'
                    f'{_esc(config.get("text", ""))}</text>')
        return salida


def _trazo(puntos: list[tuple[float, float]], config: dict) -> str:
    """Respeta el `smooth` de Tkinter.

    Un contorno ya denso —como el de un rectángulo redondeado, que trae sus
    esquinas calculadas punto a punto— debe trazarse con segmentos rectos. Al
    suavizarlo salían bultos en los bordes de la carcasa que no existen en la
    ventana real.
    """
    if config.get("smooth"):
        return _suave(puntos)
    partes = [f"M {puntos[0][0]:.1f} {puntos[0][1]:.1f}"]
    partes += [f"L {x:.1f} {y:.1f}" for x, y in puntos[1:]]
    return " ".join(partes)


def _arco(cx: float, cy: float, rx: float, ry: float, config: dict) -> str:
    """Traduce un arco de Tkinter a un path de SVG.

    Tkinter mide los ángulos desde las 3 en punto y en sentido antihorario tal
    como se ven en pantalla, con la Y hacia abajo; de ahí el signo negativo en
    el seno.
    """
    inicio = float(config.get("start", 0.0))
    extension = float(config.get("extent", 359.0))
    if abs(extension) >= 360.0:
        return (f"M {cx - rx:.1f} {cy:.1f} "
                f"A {rx:.1f} {ry:.1f} 0 1 0 {cx + rx:.1f} {cy:.1f} "
                f"A {rx:.1f} {ry:.1f} 0 1 0 {cx - rx:.1f} {cy:.1f}")
    a0 = math.radians(inicio)
    a1 = math.radians(inicio + extension)
    x0, y0 = cx + rx * math.cos(a0), cy - ry * math.sin(a0)
    x1, y1 = cx + rx * math.cos(a1), cy - ry * math.sin(a1)
    grande = 1 if abs(extension) > 180 else 0
    barrido = 0 if extension > 0 else 1
    return (f"M {x0:.1f} {y0:.1f} A {rx:.1f} {ry:.1f} 0 "
            f"{grande} {barrido} {x1:.1f} {y1:.1f}")


def _suave(puntos: list[tuple[float, float]]) -> str:
    """Path con curvas, para imitar el `smooth=True` de Tkinter."""
    if len(puntos) == 2:
        (x0, y0), (x1, y1) = puntos
        return f"M {x0:.1f} {y0:.1f} L {x1:.1f} {y1:.1f}"
    if len(puntos) == 3:
        (x0, y0), (cx, cy), (x1, y1) = puntos
        return (f"M {x0:.1f} {y0:.1f} Q {cx:.1f} {cy:.1f} {x1:.1f} {y1:.1f}")
    partes = [f"M {puntos[0][0]:.1f} {puntos[0][1]:.1f}"]
    for indice in range(1, len(puntos) - 1):
        x0, y0 = puntos[indice]
        x1, y1 = puntos[indice + 1]
        partes.append(f"Q {x0:.1f} {y0:.1f} {(x0 + x1) / 2:.1f} "
                      f"{(y0 + y1) / 2:.1f}")
    partes.append(f"L {puntos[-1][0]:.1f} {puntos[-1][1]:.1f}")
    return " ".join(partes)


def dibujar_estado(nombre: str, rostro) -> list[str]:
    lienzo = LienzoSvg(ANCHO, ALTO)
    cara = crear_cara(lienzo, rostro)
    cara.fijar_estado(nombre)
    nivel = NIVEL_VOZ.get(nombre, 0.0)
    if nivel > 0:
        # Con voz, la expresión se muestra hablando (Fase 1, A1).
        cara.fijar(funcional="hablando", expresion=nombre)
    # Sin nivel de escucha: no hay captura real que mostrar (la onda queda
    # plana en «escuchando»).
    cara.fijar_nivel_voz(nivel)
    cara.dibujar()          # crea las figuras y fija la geometría
    cara.asentar()          # lleva la expresión a su destino
    for _ in range(FOTOGRAMAS):
        cara.fijar_nivel_voz(nivel)
        cara.asentar()
        cara.dibujar()
    return lienzo.a_svg()


def construir(estados: list[str], rostro) -> str:
    paleta = mod_perfil.cargar(rostro.perfil).colores
    columnas = min(COLUMNAS, max(1, len(estados)))
    filas = (len(estados) + columnas - 1) // columnas
    ancho_total = columnas * ANCHO
    alto_total = filas * (ALTO + 34)

    piezas = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{ancho_total}" '
        f'height="{alto_total}" viewBox="0 0 {ancho_total} {alto_total}">',
        f'<rect width="{ancho_total}" height="{alto_total}" '
        f'fill="{paleta.fondo}"/>',
    ]
    for indice, nombre in enumerate(estados):
        columna, fila = indice % columnas, indice // columnas
        dx, dy = columna * ANCHO, fila * (ALTO + 34)
        piezas.append(f'<g transform="translate({dx},{dy})">')
        piezas.extend(dibujar_estado(nombre, rostro))
        piezas.append(
            f'<text x="{ANCHO / 2:.0f}" y="{ALTO + 20}" '
            f'fill="{paleta.tenue}" font-family="DejaVu Sans, sans-serif" '
            f'font-size="15" text-anchor="middle">{_esc(nombre)}</text>')
        piezas.append("</g>")
    piezas.append("</svg>")
    return "\n".join(piezas)


class MicrofonoReal:
    """Nivel del micrófono de verdad, calculado como en la aplicación.

    Mismo motor (`motores.crear_entrada`), mismo bloque de 50 ms y misma
    función de nivel (`senal.nivel_normalizado`) que audio/captura.py. Los
    bloques se miden y se descartan: no se guarda nada.
    """

    def __init__(self, ajustes_audio) -> None:
        from emotibot.audio import motores, senal
        from emotibot.audio.captura import SEGUNDOS_BLOQUE
        self._senal = senal
        self._bytes = int(ajustes_audio.frecuencia_captura * SEGUNDOS_BLOQUE) * 2
        self._entrada = motores.crear_entrada(ajustes_audio, self._bytes)
        self._parar = threading.Event()
        self.nivel = 0.0
        self._entrada.iniciar()
        self._hilo = threading.Thread(target=self._leer, daemon=True)
        self._hilo.start()

    def _leer(self) -> None:
        pendiente = bytearray()
        while not self._parar.is_set():
            try:
                pendiente.extend(self._entrada.leer(self._bytes))
            except Exception:                       # noqa: BLE001
                break
            while len(pendiente) >= self._bytes:
                self.nivel = self._senal.nivel_normalizado(bytes(pendiente[:self._bytes]))
                del pendiente[:self._bytes]

    def cerrar(self) -> None:
        self._parar.set()
        try:
            self._entrada.cerrar()
        except Exception:                           # noqa: BLE001
            pass
        self.nivel = 0.0


def voz_de_demostracion(t: float) -> float:
    """Envolvente con sílabas y pausas, solo para mover la boca."""
    silaba = abs(math.sin(t * 2 * math.pi * 3.1))
    frase = 1.0 if (t % 3.0) < 2.2 else 0.0
    return min(1.0, silaba * 1.1) * frase


class Visor:
    def __init__(self) -> None:
        import tkinter as tk
        self.config = mod_ajustes.cargar()
        self.rostro = self.config.rostro
        self.expresiones = list(EXPRESIONES)
        self.indice = 0
        self.hablando = False
        self.microfono: MicrofonoReal | None = None
        self.aviso = ""

        self.raiz = tk.Tk()
        paleta = mod_perfil.cargar(self.rostro.perfil).colores
        self.raiz.configure(bg=paleta.fondo)
        self.raiz.geometry("900x600")
        # El mismo Canvas que la aplicación.
        self.lienzo = tk.Canvas(self.raiz, bg=paleta.fondo, highlightthickness=0)
        self.lienzo.pack(fill="both", expand=True)
        # Nivel numérico en vivo (solo con M): herramienta del visor, no de
        # la cara; no lleva la etiqueta «rostro».
        self.texto_nivel = self.lienzo.create_text(
            10, 8, anchor="nw", text="", fill=paleta.tinta, font=("DejaVu Sans", 12))
        self.cara = None
        self._crear_cara()
        self.raiz.bind("<Key>", self._tecla)
        self.raiz.protocol("WM_DELETE_WINDOW", self.salir)
        self.raiz.focus_force()

    # ------------------------------------------------------------------ cara
    def _crear_cara(self) -> None:
        # La MISMA fábrica que emotibot/app.py: crear_cara(lienzo, rostro).
        self.cara = crear_cara(self.lienzo, self.rostro)
        self.lienzo.configure(bg=self.cara.paleta.fondo)
        self._aplicar_expresion()
        self.lienzo.tag_raise(self.texto_nivel)

    def _aplicar_expresion(self) -> None:
        nombre = self.expresiones[self.indice]
        self.cara.fijar_estado(nombre)
        if self.microfono:
            # Como en la aplicación: micrófono abierto = estado «escuchando».
            self.cara.fijar(funcional="escuchando", expresion=nombre)
        elif self.hablando:
            self.cara.fijar(funcional="hablando", expresion=nombre)
        self._titulo()

    def _titulo(self) -> None:
        partes = [
            f"Visor del rostro · {self.expresiones[self.indice]}",
            f"carcasa {'sí' if self.rostro.carcasa else 'no'}",
            f"perfil {self.cara.perfil.nombre}",
            "hablando (voz de demostración)" if self.hablando else "",
            "micrófono REAL" if self.microfono else "",
            self.aviso,
        ]
        self.raiz.title(" · ".join(p for p in partes if p))

    # --------------------------------------------------------------- teclado
    def _tecla(self, evento) -> None:
        tecla = evento.keysym.lower()
        if tecla in ("right", "space"):
            self.indice = (self.indice + 1) % len(self.expresiones)
            self._aplicar_expresion()
        elif tecla == "left":
            self.indice = (self.indice - 1) % len(self.expresiones)
            self._aplicar_expresion()
        elif tecla == "c":
            self.rostro = dataclasses.replace(self.rostro, carcasa=not self.rostro.carcasa)
            self._crear_cara()
        elif tecla == "h":
            self.hablando = not self.hablando
            if self.hablando and self.microfono:
                self._alternar_microfono()      # no se habla y escucha a la vez
            if not self.hablando:
                self.cara.fijar_nivel_voz(0.0)
            self._aplicar_expresion()
        elif tecla == "m":
            self._alternar_microfono()
        elif tecla == "p":
            mod_perfil._cache.clear()
            try:
                self._crear_cara()
                self.aviso = ""
            except mod_perfil.ErrorPerfil as exc:
                self.aviso = f"perfil no válido: {exc}"
            self._titulo()
        elif tecla == "f11":
            actual = bool(self.raiz.attributes("-fullscreen"))
            self.raiz.attributes("-fullscreen", not actual)
        elif tecla in ("escape", "q"):
            self.salir()

    def _alternar_microfono(self) -> None:
        if self.microfono:
            self.microfono.cerrar()
            self.microfono = None
            self.aviso = ""
        else:
            try:
                self.microfono = MicrofonoReal(self.config.audio)
                self.hablando = False
                self.aviso = ""
            except Exception as exc:                # noqa: BLE001
                self.aviso = f"sin micrófono: {exc}"
        self._aplicar_expresion()

    # ----------------------------------------------------------------- bucle
    def _pintar(self) -> None:
        """Lo mismo que Aplicacion._pintar: nivel de voz, dibujar, repetir."""
        ahora = time.monotonic()
        self.cara.fijar_nivel_voz(voz_de_demostracion(ahora) if self.hablando else 0.0)
        nivel = self.microfono.nivel if self.microfono else 0.0
        self.cara.fijar_nivel_escucha(nivel)
        self.cara.dibujar()
        self.lienzo.itemconfigure(
            self.texto_nivel,
            text=(f"micrófono · nivel {nivel:.3f} · "
                  f"cara escuchando: {'sí' if self.cara.microfono_abierto else 'no'}")
            if self.microfono else "")
        self.raiz.after(max(16, int(1000 / max(10, self.rostro.fps))), self._pintar)

    def ejecutar(self) -> None:
        self._pintar()
        self.raiz.mainloop()

    def salir(self) -> None:
        if self.microfono:
            self.microfono.cerrar()
        self.raiz.destroy()


def main() -> int:
    analizador = argparse.ArgumentParser(
        description="Visor del rostro (ventana) o lámina SVG con --svg.")
    analizador.add_argument("--svg", action="store_true",
                            help="Escribir la lámina SVG en lugar de abrir la ventana.")
    analizador.add_argument("estados", nargs="*",
                            help="(--svg) Estados a dibujar. Por defecto, todos.")
    analizador.add_argument("-o", "--salida", default="rostro_vista_previa.svg")
    argumentos = analizador.parse_args()

    if not argumentos.svg:
        Visor().ejecutar()
        return 0

    estados = argumentos.estados or list(EXPRESIONES)
    desconocidos = [e for e in estados if e not in EXPRESIONES]
    if desconocidos:
        print(f"Estados desconocidos: {', '.join(desconocidos)}")
        print(f"Disponibles: {', '.join(EXPRESIONES)}")
        return 2

    rostro = mod_ajustes.cargar().rostro
    Path(argumentos.salida).write_text(construir(estados, rostro), encoding="utf-8")
    print(f"Escrito {argumentos.salida} con {len(estados)} estados.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
