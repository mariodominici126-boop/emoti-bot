#!/usr/bin/env python3
"""Lanzador de EMOTI-BOT.

Funciona desde cualquier directorio y sin instalar el paquete:

    python3 bin/emotibot.py
"""
from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from emotibot.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
