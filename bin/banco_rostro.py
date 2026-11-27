#!/usr/bin/env python3
"""C3 — Banco de rendimiento del rostro: A (Tkinter, producción) frente a
B (Pillow, prototipo), en la ventana real de Tkinter.

Para cada motor y resolución, durante N segundos a los FPS objetivo:
- ms por fotograma (mediana y p95) del trabajo de dibujo, incluida la
  actualización de Tk;
- FPS efectivos;
- CPU del proceso (% de un núcleo: tiempo de CPU ÷ tiempo real);
- memoria residente al final (RSS).

Con --carga se lanza a la vez un proceso que ocupa un núcleo entero, para
imitar al reconocimiento de voz trabajando mientras la cara se anima.

Todos los resultados son de la máquina donde se ejecuta. Medido en un PC, no
dice cómo irá en la Raspberry Pi: allí hay que ejecutarlo también.

Uso:
    .venv\\Scripts\\python.exe bin\\banco_rostro.py
    .venv\\Scripts\\python.exe bin\\banco_rostro.py --segundos 10 --carga
    .venv\\Scripts\\python.exe bin\\banco_rostro.py --resoluciones 800x480
"""
from __future__ import annotations

import argparse
import ctypes
import json
import multiprocessing
import platform
import statistics
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

from emotibot import __version__, rutas  # noqa: E402
from emotibot.rostro import PALETA, Cara  # noqa: E402

SECUENCIA = ("reposo", "escuchando", "hablando", "feliz", "preocupado", "sin_entender")


def rss_mb() -> float | None:
    """Memoria residente del proceso, sin dependencias externas."""
    if sys.platform == "win32":
        class Contadores(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]
        from ctypes import wintypes
        c = Contadores()
        c.cb = ctypes.sizeof(c)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        funcion = kernel.K32GetProcessMemoryInfo
        funcion.argtypes = [wintypes.HANDLE, ctypes.POINTER(Contadores), wintypes.DWORD]
        funcion.restype = wintypes.BOOL
        if funcion(kernel.GetCurrentProcess(), ctypes.byref(c), c.cb):
            return c.WorkingSetSize / 1e6
        return None
    try:
        for linea in Path("/proc/self/status").read_text().splitlines():
            if linea.startswith("VmRSS:"):
                return int(linea.split()[1]) / 1e3
    except OSError:
        pass
    return None


def _ocupar_nucleo(hasta: float) -> None:
    x = 0
    while time.time() < hasta:
        x = (x * 31 + 7) % 1_000_003


def medir(motor: str, ancho: int, alto: int, segundos: float, fps: int,
          supermuestreo: int, escuchando: bool = False, rostro: str | None = None) -> dict:
    raiz = tk.Tk()
    raiz.geometry(f"{ancho}x{alto}+20+20")
    raiz.title(f"banco {motor} {ancho}x{alto}")
    lienzo = tk.Canvas(raiz, width=ancho, height=alto, bg=PALETA.fondo,
                       highlightthickness=0)
    lienzo.pack(fill="both", expand=True)
    raiz.update()

    if motor in ("A", "A0"):
        # A0 = el mismo motor sin carcasa (solo rasgos sobre el fondo).
        from emotibot.rostro import perfil as mod_perfil
        perfil = mod_perfil.cargar(rostro) if rostro else None
        cara = Cara(lienzo, perfil.colores if perfil else PALETA, perfil=perfil,
                    **({"carcasa": False} if motor == "A0" else {}))
        fijar = cara.fijar
        voz = cara.fijar_nivel_voz
        escucha = cara.fijar_nivel_escucha

        def pintar():
            cara.dibujar()
    else:
        from PIL import ImageTk
        from prototipos.rostro_pillow.animador import Animador
        from prototipos.rostro_pillow.render import RostroPillow
        animador = Animador()
        rostro = RostroPillow(max(lienzo.winfo_width(), 320),
                              max(lienzo.winfo_height(), 240),
                              supermuestreo=supermuestreo)
        primero = rostro.cuadro(animador.anim, animador.expresion, 0.0)
        foto = ImageTk.PhotoImage(primero)
        lienzo.create_image(0, 0, anchor="nw", image=foto)
        fijar = animador.fijar
        voz = animador.fijar_nivel_voz
        escucha = animador.fijar_nivel_escucha

        def pintar():
            t = animador.avanzar()
            foto.paste(rostro.cuadro(animador.anim, animador.expresion, t))

    from prototipos.rostro_pillow.expresiones import EXPRESIONES_C4
    tiempos: list[float] = []
    cuadros = 0
    cpu0, real0 = time.process_time(), time.perf_counter()
    fin = real0 + segundos
    paso = 1.0 / fps
    siguiente = real0
    while time.perf_counter() < fin:
        ahora = time.perf_counter()
        # Cambia de expresión cada segundo y «habla» en la mitad del tiempo:
        # así se miden las transiciones, no un fotograma congelado.
        indice = int(ahora - real0) % len(SECUENCIA)
        funcional, expresion = EXPRESIONES_C4[SECUENCIA[indice]]
        if escuchando:
            # Micrófono abierto todo el rato y un nivel que cambia en cada
            # fotograma: las barras del micrófono se redibujan siempre.
            funcional = "escuchando"
            escucha(abs(((ahora * 5) % 2) - 1))
        fijar(funcional=funcional, expresion=expresion)
        voz(0.3 + 0.6 * abs(((ahora * 7) % 2) - 1) if funcional == "hablando" else 0.0)
        inicio = time.perf_counter()
        pintar()
        raiz.update()
        tiempos.append((time.perf_counter() - inicio) * 1000)
        cuadros += 1
        siguiente += paso
        espera = siguiente - time.perf_counter()
        if espera > 0:
            time.sleep(espera)
        else:
            siguiente = time.perf_counter()
    real = time.perf_counter() - real0
    cpu = time.process_time() - cpu0
    memoria = rss_mb()
    raiz.destroy()
    ordenados = sorted(tiempos)
    return {
        "motor": motor, "resolucion": f"{ancho}x{alto}",
        "supermuestreo": supermuestreo if motor == "B" else None,
        "fps_objetivo": fps, "fps_efectivos": round(cuadros / real, 1),
        "ms_mediana": round(statistics.median(tiempos), 2),
        "ms_p95": round(ordenados[int(0.95 * (len(ordenados) - 1))], 2),
        "cpu_pct_nucleo": round(100 * cpu / real, 1),
        "rss_mb": None if memoria is None else round(memoria, 1),
        "cuadros": cuadros,
        "escuchando": escuchando,
    }


def main() -> int:
    analizador = argparse.ArgumentParser(description=__doc__,
                                         formatter_class=argparse.RawDescriptionHelpFormatter)
    analizador.add_argument("--segundos", type=float, default=6.0)
    analizador.add_argument("--fps", type=int, default=30)
    analizador.add_argument("--resoluciones", default="800x480,1280x720,1920x1080")
    analizador.add_argument("--motores", default="A,B1,B2",
                            help="Qué medir: A (Tkinter), B1/B2 (Pillow ×1/×2), "
                                 "A0 (Tkinter sin carcasa).")
    analizador.add_argument("--rostro", default=None,
                            help="Perfil de rostro de config/rostro/ (por defecto, el de hoy).")
    analizador.add_argument("--escuchando", action="store_true",
                            help="Micrófono abierto todo el tiempo con nivel variable "
                                 "(barras del micrófono animándose en cada fotograma).")
    analizador.add_argument("--carga", action="store_true",
                            help="Ocupa un núcleo en paralelo (imita a Whisper).")
    argumentos = analizador.parse_args()
    if sys.platform == "win32":
        try:                       # coordenadas reales, sin escalado de Windows
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass

    todos = {"A": ("A", 1), "A0": ("A0", 1), "B1": ("B", 1), "B2": ("B", 2)}
    casos = [todos[m.strip().upper()] for m in argumentos.motores.split(",")
             if m.strip().upper() in todos]
    resultados = []
    for texto in argumentos.resoluciones.split(","):
        ancho, alto = (int(v) for v in texto.lower().split("x"))
        for motor, s in casos:
            carga = None
            if argumentos.carga:
                carga = multiprocessing.Process(
                    target=_ocupar_nucleo, args=(time.time() + argumentos.segundos + 2,))
                carga.start()
            r = medir(motor, ancho, alto, argumentos.segundos, argumentos.fps, s,
                      argumentos.escuchando, argumentos.rostro)
            r["rostro"] = argumentos.rostro or "hybrid_balanced"
            if carga is not None:
                carga.terminate()
                carga.join()
            r["con_carga"] = argumentos.carga
            resultados.append(r)
            etiqueta = {"A": "A Tk", "A0": "A Tk sin carc."}.get(motor, f"B Pillow×{s}")
            print(f"{r['resolucion']:>10} {etiqueta:<12} {r['fps_efectivos']:>5} fps · "
                  f"{r['ms_mediana']:>6} ms (p95 {r['ms_p95']}) · CPU "
                  f"{r['cpu_pct_nucleo']}% · RSS {r['rss_mb']} MB")

    destino = rutas.LOGS / "mediciones"
    rutas.asegurar_directorio(destino)
    archivo = destino / f"c3_rendimiento_{time.strftime('%Y%m%d-%H%M%S')}.json"
    archivo.write_text(json.dumps({
        "fecha": time.strftime("%Y-%m-%dT%H:%M:%S"), "version_emotibot": __version__,
        "python": sys.executable,
        "sistema": f"{platform.system()} {platform.release()} {platform.machine()}",
        "procesador": platform.processor(), "nucleos": multiprocessing.cpu_count(),
        "segundos": argumentos.segundos, "resultados": resultados,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nResultados: {archivo}")
    print("Nota: el RSS incluye todo el proceso (Tk, Pillow…) y se acumula entre")
    print("casos de la misma ejecución; compáralo con prudencia.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
