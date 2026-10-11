"""Ponto de entrada do executável (PyInstaller). Sem argumentos abre a app; com argumentos é a CLI."""
import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from stems4u.cli import main
    sys.exit(main(sys.argv[1:] or ["app"]))
