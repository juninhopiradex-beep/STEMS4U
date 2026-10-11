import multiprocessing
import sys

from .cli import main

if __name__ == "__main__":
    multiprocessing.freeze_support()  # necessário em executáveis PyInstaller no Windows
    sys.exit(main())
