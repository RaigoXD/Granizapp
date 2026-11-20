"""Punto de entrada: `python run.py` (también lo usa PyInstaller para el .exe)."""
import sys

from granizapp.app import main

if __name__ == "__main__":
    sys.exit(main())
