"""Punto de entrada para PyInstaller: el mismo `python -m emotibot`.
(`emotibot/__main__.py` usa un import relativo y PyInstaller necesita un
guion con import absoluto.)"""
import sys

from emotibot.app import main

if __name__ == "__main__":
    sys.exit(main())
