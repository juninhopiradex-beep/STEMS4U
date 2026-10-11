"""Caminhos de dados e logging.

Nada é escrito dentro da aplicação instalada (o bundle é só-leitura).
Modelos, cache e logs vivem em:
  macOS   ~/Library/Application Support/STEMS4U  e  ~/Library/Caches/STEMS4U
  Windows %LOCALAPPDATA%\\STEMS4U
  Linux   ~/.local/share/stems4u  e  ~/.cache/stems4u
Pode ser substituído com a variável STEMS4U_HOME.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path

from . import __version__


def _base_dirs() -> tuple[Path, Path]:
    override = os.environ.get("STEMS4U_HOME")
    if override:
        root = Path(override)
        return root / "data", root / "cache"
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library/Application Support/STEMS4U", home / "Library/Caches/STEMS4U"
    if sys.platform.startswith("win"):
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData/Local")) / "STEMS4U"
        return local / "Data", local / "Cache"
    return home / ".local/share/stems4u", home / ".cache/stems4u"


DATA_DIR, CACHE_DIR = _base_dirs()
MODELS_DIR = Path(os.environ.get("STEMS4U_MODELS", DATA_DIR / "models"))
LOG_DIR = DATA_DIR / "logs"
PROJECTS_DIR = DATA_DIR / "projects"

# Taxa de trabalho dos modelos actuais (Demucs, Roformer, MDX23C): 44,1 kHz estéreo.
MODEL_SR = 44100


def ensure_dirs() -> None:
    for d in (DATA_DIR, CACHE_DIR, MODELS_DIR, LOG_DIR, PROJECTS_DIR):
        d.mkdir(parents=True, exist_ok=True)


_configured = False


def get_logger(name: str = "stems4u") -> logging.Logger:
    global _configured
    log = logging.getLogger(name)
    if not _configured:
        _configured = True
        root = logging.getLogger("stems4u")
        root.setLevel(logging.DEBUG)
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        try:
            ensure_dirs()
            fh = logging.handlers.RotatingFileHandler(LOG_DIR / "stems4u.log", maxBytes=5_000_000,
                                                      backupCount=3, encoding="utf-8")
            fh.setFormatter(fmt)
            root.addHandler(fh)
        except OSError:
            pass
        sh = logging.StreamHandler()
        sh.setLevel(logging.INFO if not os.environ.get("STEMS4U_DEBUG") else logging.DEBUG)
        sh.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        root.addHandler(sh)
        root.info("STEMS4U %s — dados em %s", __version__, DATA_DIR)
    return log


class UserError(Exception):
    """Erro com mensagem compreensível para o utilizador (o detalhe técnico vai para o log)."""

    def __init__(self, message: str, hint: str = "", code: str = "error"):
        super().__init__(message)
        self.message, self.hint, self.code = message, hint, code

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "hint": self.hint}
