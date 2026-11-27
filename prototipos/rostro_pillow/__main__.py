"""python -m prototipos.rostro_pillow  — ventana del prototipo (Fase 1C)."""
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from prototipos.rostro_pillow.ventana import VentanaPrototipo  # noqa: E402

if __name__ == "__main__":
    VentanaPrototipo().ejecutar()
