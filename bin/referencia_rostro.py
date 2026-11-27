#!/usr/bin/env python3
"""Referencia de 720 casos por rostro: que nada cambie sin querer.

Dibuja cada caso con reloj y azar fijos y guarda una HUELLA (sha256) de todo
lo dibujado: tipo, coordenadas (a 2 decimales) y configuración de cada figura.
Los casos: 4 tamaños × con y sin carcasa × 15 expresiones × 3 estados
funcionales × 2 niveles de voz/escucha = 720.

    python bin/referencia_rostro.py grabar  [rostro …]   # todos por defecto
    python bin/referencia_rostro.py comparar [rostro …]

Las huellas viven en tests/datos/referencia_rostro_<rostro>.json, y
tests/test_referencia_rostro.py las compara en cada batería. Grabar de nuevo
solo cuando un cambio del dibujo es INTENCIONADO, y dejarlo en la bitácora.
"""
from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import emotibot.rostro.cara as mod_cara  # noqa: E402
from emotibot.rostro import EXPRESIONES  # noqa: E402
from emotibot.rostro import perfil as mod_perfil  # noqa: E402

DATOS = RAIZ / "tests" / "datos"
_RANDOM = random.Random


class _Lienzo:
    """Lo justo de un Canvas para dibujar sin pantalla."""

    def __init__(self, ancho, alto):
        self.ancho, self.alto, self.items, self.n = ancho, alto, {}, 0

    def winfo_width(self):
        return self.ancho

    def winfo_height(self):
        return self.alto

    def _crear(self, tipo, coords, kw):
        self.n += 1
        planas = coords[0] if len(coords) == 1 and isinstance(coords[0], (list, tuple)) else coords
        self.items[self.n] = {"tipo": tipo, "coords": list(planas), "config": dict(kw)}
        return self.n

    def create_polygon(self, *c, **k):
        return self._crear("polygon", c, k)

    def create_line(self, *c, **k):
        return self._crear("line", c, k)

    def create_oval(self, *c, **k):
        return self._crear("oval", c, k)

    def create_text(self, x, y, **k):
        return self._crear("text", (x, y), k)

    def coords(self, item, *valores):
        planas = valores[0] if len(valores) == 1 and isinstance(valores[0], (list, tuple)) else valores
        self.items[item]["coords"] = list(planas)

    def itemconfigure(self, item, **kw):
        self.items[item]["config"].update(kw)

    def delete(self, _etiqueta):
        self.items.clear()


def casos():
    for ancho, alto in ((800, 480), (1280, 720), (1024, 600), (800, 600)):
        for carcasa in (True, False):
            for expresion in EXPRESIONES:
                for funcional in (None, "hablando", "escuchando"):
                    for voz, escucha in ((0.0, 0.0), (0.7, 0.6)):
                        yield ancho, alto, carcasa, expresion, funcional, voz, escucha


def huella(rostro: str, ancho, alto, carcasa, expresion, funcional, voz, escucha) -> str:
    reloj = [1000.0]
    with mock.patch.object(mod_cara.time, "monotonic", lambda: reloj[0]), \
            mock.patch.object(mod_cara.random, "Random", lambda: _RANDOM(7)):
        lienzo = _Lienzo(ancho, alto)
        cara = mod_cara.Cara(lienzo, carcasa=carcasa, perfil=mod_perfil.cargar(rostro))
        if funcional:
            cara.fijar(funcional=funcional, expresion=expresion)
        else:
            cara.fijar_estado(expresion)
        cara.fijar_nivel_voz(voz)
        cara.fijar_nivel_escucha(escucha)
        cara.asentar()
        for _ in range(12):
            reloj[0] += 1 / 30
            cara.dibujar()
    volcado = [[d["tipo"], [round(c, 2) for c in d["coords"]],
                sorted((k, str(v)) for k, v in d["config"].items())]
               for _, d in sorted(lienzo.items.items())]
    return hashlib.sha256(json.dumps(volcado).encode("utf-8")).hexdigest()


def calcular(rostro: str) -> dict[str, str]:
    return {"|".join(map(str, c)): huella(rostro, *c) for c in casos()}


def archivo(rostro: str) -> Path:
    return DATOS / f"referencia_rostro_{rostro}.json"


def comparar(rostro: str) -> list[str]:
    guardada = json.loads(archivo(rostro).read_text(encoding="utf-8"))
    actual = calcular(rostro)
    return sorted(k for k in guardada if guardada[k] != actual.get(k)) + \
        sorted(k for k in actual if k not in guardada)


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in ("grabar", "comparar"):
        print(__doc__)
        return 2
    rostros = sys.argv[2:] or sorted(p.stem for p in mod_perfil.DIRECTORIO.glob("*.json"))
    for rostro in rostros:
        if sys.argv[1] == "grabar":
            DATOS.mkdir(parents=True, exist_ok=True)
            huellas = calcular(rostro)
            archivo(rostro).write_text(json.dumps(huellas, indent=0, sort_keys=True) + "\n",
                                       encoding="utf-8")
            print(f"{rostro}: grabados {len(huellas)} casos")
        else:
            distintos = comparar(rostro)
            print(f"{rostro}: {len(distintos)} casos distintos de {sum(1 for _ in casos())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
