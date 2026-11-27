#!/usr/bin/env python3
"""C3/C4 — Capturas comparables del rostro A (producción) y B (prototipo).

Mismas siete expresiones del protocolo C4, mismo tamaño, mismo instante de
la animación (sin parpadeo ni respiración, mirada centrada):

- A se captura de una ventana REAL de Tkinter con ImageGrab, así que es
  exactamente lo que se ve hoy, con sus bordes dentados.
- B se genera con el renderizador del prototipo.

Salida en docs/fase1/capturas/: un PNG por expresión y motor, y una lámina
comparativa con todas. La carpeta láminas_c4/ son las láminas SIN etiqueta
para la prueba de legibilidad (ver bin/legibilidad_rostro.py).

Uso:
    .venv\\Scripts\\python.exe bin\\capturas_rostro.py
    .venv\\Scripts\\python.exe bin\\capturas_rostro.py --tamano 1024x600
"""
from __future__ import annotations

import argparse
import ctypes
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))
try:  # consola de Windows en cp1252: que se vean tildes y símbolos
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

import tkinter as tk  # noqa: E402

from PIL import Image, ImageDraw, ImageFont, ImageGrab, ImageStat  # noqa: E402

import dataclasses  # noqa: E402

from emotibot import ajustes as mod_ajustes  # noqa: E402
from emotibot.rostro import PALETA, crear_cara  # noqa: E402
from prototipos.rostro_pillow.animador import Animador  # noqa: E402
from prototipos.rostro_pillow.render import RostroPillow  # noqa: E402
from prototipos.rostro_pillow.expresiones import EXPRESIONES_C4  # noqa: E402

DESTINO = RAIZ / "docs" / "fase1" / "capturas"
NIVEL_VOZ = 0.85
NIVEL_ESCUCHA = 0.6


def _congelar(anim) -> None:
    """Mismo instante para A y B: ojos abiertos y mirada sin deriva."""
    anim.parpadeo = 1.0
    anim.deriva = (0.0, 0.0)


def _foto_de_la_ventana(raiz, lienzo, ancho: int, alto: int) -> Image.Image:
    """Solo la ventana del rostro, nunca la pantalla: en Windows, con
    PrintWindow, que la copia aunque otra ventana la tape. En otros sistemas,
    la zona de la pantalla (la ventana va siempre encima)."""
    if sys.platform == "win32":
        from ctypes import wintypes
        u32, g32 = ctypes.windll.user32, ctypes.windll.gdi32
        hwnd = int(raiz.wm_frame(), 16)
        r = wintypes.RECT()
        u32.GetWindowRect(hwnd, ctypes.byref(r))
        w, h = r.right - r.left, r.bottom - r.top
        hdc = u32.GetWindowDC(hwnd)
        mdc = g32.CreateCompatibleDC(hdc)
        bmp = g32.CreateCompatibleBitmap(hdc, w, h)
        g32.SelectObject(mdc, bmp)
        u32.PrintWindow(hwnd, mdc, 2)
        cabecera = (ctypes.c_uint32 * 10)(40, w, (-h) & 0xFFFFFFFF, 1 | (32 << 16),
                                          0, 0, 0, 0, 0, 0)
        datos = ctypes.create_string_buffer(w * h * 4)
        g32.GetDIBits(mdc, bmp, 0, h, datos, cabecera, 0)
        g32.DeleteObject(bmp)
        g32.DeleteDC(mdc)
        u32.ReleaseDC(hwnd, hdc)
        imagen = Image.frombuffer("RGB", (w, h), datos, "raw", "BGRX", 0, 1)
        dx, dy = lienzo.winfo_rootx() - r.left, lienzo.winfo_rooty() - r.top
        return imagen.crop((dx, dy, dx + ancho, dy + alto))
    x, y = lienzo.winfo_rootx(), lienzo.winfo_rooty()
    return ImageGrab.grab(bbox=(x, y, x + ancho, y + alto), all_screens=True)


def captura_a(nombre: str, ancho: int, alto: int, carcasa: bool = True,
              rostro_perfil: str | None = None,
              estado: tuple[str, str] | None = None) -> Image.Image:
    """`estado` = (funcional, expresión), para estados fuera de las siete
    de C4 (p. ej. «error» en la prueba de legibilidad)."""
    funcional, expresion = estado or EXPRESIONES_C4[nombre]
    raiz = tk.Tk()
    raiz.overrideredirect(True)
    raiz.geometry(f"{ancho}x{alto}+40+40")
    raiz.attributes("-topmost", True)
    lienzo = tk.Canvas(raiz, width=ancho, height=alto, bg=PALETA.fondo,
                       highlightthickness=0)
    lienzo.pack()
    raiz.update()
    # La misma fábrica que la aplicación y el visor.
    rostro = dataclasses.replace(mod_ajustes.cargar().rostro, carcasa=carcasa)
    if rostro_perfil:
        rostro = dataclasses.replace(rostro, perfil=rostro_perfil)
    cara = crear_cara(lienzo, rostro)
    cara.fijar(funcional=funcional, expresion=expresion)
    cara.fijar_nivel_voz(NIVEL_VOZ if funcional == "hablando" else 0.0)
    cara.fijar_nivel_escucha(NIVEL_ESCUCHA)
    cara._inicio = time.monotonic()           # respiración en su punto 0
    # 16 fotogramas: más de los que necesita la onda de escucha para llenarse.
    for _ in range(16):
        cara.asentar()
        _congelar(cara._anim)
        cara._proximo_parpadeo = time.monotonic() + 60
        cara._proxima_saccada = time.monotonic() + 60
        cara._deriva_objetivo = (0.0, 0.0)
        cara._inicio = time.monotonic()
        cara.dibujar()
        raiz.update()
    time.sleep(0.25)
    raiz.update()
    imagen = _foto_de_la_ventana(raiz, lienzo, ancho, alto)
    raiz.destroy()
    if max(ImageStat.Stat(imagen.convert("L")).stddev) < 2:
        raise RuntimeError("La captura de A salió vacía: ¿la pantalla está "
                           "bloqueada o la ventana tapada?")
    return imagen.convert("RGB")


def captura_b(nombre: str, ancho: int, alto: int, supermuestreo: int = 2) -> Image.Image:
    funcional, expresion = EXPRESIONES_C4[nombre]
    animador = Animador()
    animador.fijar(funcional=funcional, expresion=expresion)
    animador.fijar_nivel_voz(NIVEL_VOZ if funcional == "hablando" else 0.0)
    animador.fijar_nivel_escucha(NIVEL_ESCUCHA)
    for _ in range(4):
        animador.asentar()
        _congelar(animador.anim)
    return RostroPillow(ancho, alto, supermuestreo=supermuestreo).cuadro(
        animador.anim, animador.expresion, 0.0)


def lamina_columnas(filas: list[tuple[str, list[Image.Image]]], titulos: list[str],
                    escala: float = 0.5) -> Image.Image:
    """Una fila por expresión y una columna por variante."""
    w = int(filas[0][1][0].width * escala)
    h = int(filas[0][1][0].height * escala)
    n = len(titulos)
    cabecera, margen = 34, 8
    hoja = Image.new("RGB", (n * w + (n + 1) * margen + 120,
                             len(filas) * (h + margen) + cabecera + margen), (240, 244, 248))
    d = ImageDraw.Draw(hoja)
    fuente = ImageFont.load_default(15)
    for i, titulo in enumerate(titulos):
        d.text((120 + margen + i * (w + margen), 9), titulo, fill=(20, 30, 40), font=fuente)
    for fila, (nombre, imagenes) in enumerate(filas):
        y = cabecera + fila * (h + margen)
        d.text((margen, y + h // 2 - 8), nombre, fill=(20, 30, 40), font=fuente)
        for i, imagen in enumerate(imagenes):
            hoja.paste(imagen.resize((w, h), Image.LANCZOS), (120 + margen + i * (w + margen), y))
    return hoja


def lamina(pares: list[tuple[str, Image.Image, Image.Image]], escala: float = 0.5,
           titulos: tuple[str, str] = ("A · producción (Tkinter)",
                                       "B · prototipo Hybrid Balanced (Pillow ×2)")) -> Image.Image:
    w = int(pares[0][1].width * escala)
    h = int(pares[0][1].height * escala)
    cabecera, margen = 34, 8
    hoja = Image.new("RGB", (2 * w + 3 * margen + 120, len(pares) * (h + margen) + cabecera + margen),
                     (240, 244, 248))
    d = ImageDraw.Draw(hoja)
    fuente = ImageFont.load_default(15)
    d.text((120 + margen, 9), titulos[0], fill=(20, 30, 40), font=fuente)
    d.text((120 + 2 * margen + w, 9), titulos[1], fill=(20, 30, 40), font=fuente)
    for fila, (nombre, a, b) in enumerate(pares):
        y = cabecera + fila * (h + margen)
        d.text((margen, y + h // 2 - 8), nombre, fill=(20, 30, 40), font=fuente)
        hoja.paste(a.resize((w, h), Image.LANCZOS), (120 + margen, y))
        hoja.paste(b.resize((w, h), Image.LANCZOS), (120 + 2 * margen + w, y))
    return hoja


def main() -> int:
    analizador = argparse.ArgumentParser(description=__doc__,
                                         formatter_class=argparse.RawDescriptionHelpFormatter)
    analizador.add_argument("--tamano", default="800x480")
    analizador.add_argument("--rostros", action="store_true",
                            help="Solo la comparativa de los rostros publicados (D10), "
                                 "con y sin carcasa.")
    argumentos = analizador.parse_args()
    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass
    ancho, alto = (int(v) for v in argumentos.tamano.lower().split("x"))
    DESTINO.mkdir(parents=True, exist_ok=True)
    if argumentos.rostros:
        from emotibot.rostro import perfil as mod_perfil
        rostros = ["hybrid_balanced"] + sorted(
            p.stem for p in mod_perfil.DIRECTORIO.glob("*.json") if p.stem != "hybrid_balanced")
        titulos = rostros
        for carcasa, sufijo in ((True, ""), (False, "_sin_carcasa")):
            filas = []
            for nombre in EXPRESIONES_C4:
                imagenes = [captura_a(nombre, ancho, alto, carcasa, r) for r in rostros]
                filas.append((nombre, imagenes))
                print(f"  {nombre}{sufijo}")
            lamina_columnas(filas, titulos).save(DESTINO / f"comparativa_rostros{sufijo}.png")
        print(f"\nCapturas en {DESTINO}")
        return 0
    pares = []
    for nombre in EXPRESIONES_C4:
        a = captura_a(nombre, ancho, alto)
        b = captura_b(nombre, ancho, alto)
        a.save(DESTINO / f"{nombre}_A.png")
        b.save(DESTINO / f"{nombre}_B.png")
        pares.append((nombre, a, b))
        print(f"  {nombre}")
    lamina(pares).save(DESTINO / "comparativa_A_B.png")
    # Modo sin carcasa (pantalla montada dentro del robot): con y sin, lado a
    # lado, en la misma ventana.
    sin_carcasa = []
    for nombre, a, _ in pares:
        s = captura_a(nombre, ancho, alto, carcasa=False)
        s.save(DESTINO / f"{nombre}_A_sin_carcasa.png")
        sin_carcasa.append((nombre, a, s))
    lamina(sin_carcasa, titulos=("A · con carcasa (desarrollo)",
                                 "A · sin carcasa (pantalla dentro del robot)")
           ).save(DESTINO / "comparativa_carcasa.png")
    print(f"\nCapturas en {DESTINO}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
