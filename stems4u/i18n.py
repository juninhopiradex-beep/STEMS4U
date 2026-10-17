"""Idioma da interface (Português / English), partilhado por todos os produtos Piradex.

A escolha fica no mesmo ficheiro usado pelos plugins (ROOM-X, ANALYSER, MIXSPACE,
EQMotion, DELEX), por isso mudar o idioma num deles muda em todos:

    macOS    ~/Library/Application Support/Piradex/Piradex.settings
    Windows  %APPDATA%\\Piradex\\Piradex.settings
    Linux    ~/.config/Piradex/Piradex.settings

Formato (PropertiesFile do JUCE em XML):

    <?xml version="1.0" encoding="UTF-8"?>
    <PROPERTIES>
      <VALUE name="language" val="pt"/>
    </PROPERTIES>

Na primeira vez (sem ficheiro) segue o idioma do sistema: pt* → PT, outro → EN.
Os textos do motor continuam a nascer em PT; a interface traduz (um só dicionário,
partilhado pela app e pela versão web). `tr()` serve para os poucos textos que o
motor mostra directamente (diálogos nativos de ficheiros).
"""
from __future__ import annotations

import locale
import os
import sys
import threading
import xml.etree.ElementTree as ET
from pathlib import Path

LANGS = ("pt", "en")
_lock = threading.Lock()
_current: str | None = None


def settings_path() -> Path:
    if override := os.environ.get("PIRADEX_SETTINGS"):
        return Path(override)
    home = Path.home()
    if sys.platform == "darwin":
        base = home / "Library" / "Application Support"
    elif sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    return base / "Piradex" / "Piradex.settings"


def system_language() -> str:
    cands = [os.environ.get(k, "") for k in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE")]
    try:
        cands.append(locale.getlocale()[0] or "")
    except Exception:  # noqa: BLE001
        pass
    if sys.platform == "darwin":
        try:
            import subprocess
            out = subprocess.run(["defaults", "read", "-g", "AppleLanguages"], capture_output=True,
                                 text=True, timeout=2).stdout
            first = next((l.strip(' ",()') for l in out.splitlines() if l.strip(' ",()')), "")
            cands.insert(0, first)
        except Exception:  # noqa: BLE001
            pass
    elif sys.platform.startswith("win"):
        try:
            import ctypes
            lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            cands.insert(0, "pt" if (lcid & 0x3FF) == 0x16 else "en")
        except Exception:  # noqa: BLE001
            pass
    first = next((c for c in cands if c and c not in ("C", "POSIX")), "")
    return "pt" if first.lower().startswith("pt") else "en"


def _read_file(p: Path) -> ET.Element | None:
    try:
        root = ET.fromstring(p.read_text(encoding="utf-8"))
        return root if root.tag == "PROPERTIES" else None
    except (OSError, ET.ParseError, UnicodeDecodeError):
        return None


def _from_settings() -> str | None:
    root = _read_file(settings_path())
    if root is None:
        return None
    for v in root.iter("VALUE"):
        if v.get("name") == "language" and v.get("val") in LANGS:
            return v.get("val")
    return None


def current() -> str:
    global _current
    with _lock:
        if _current is None:
            _current = _from_settings() or system_language()
        return _current


def reload() -> str:
    """Relê o ficheiro partilhado (outro produto Piradex pode ter mudado o idioma)."""
    global _current
    with _lock:
        _current = _from_settings() or _current or system_language()
        return _current


def set(lang: str) -> str:  # noqa: A001 — mesmo nome que piradex::i18n::set nos plugins
    global _current
    lang = "en" if str(lang).lower().startswith("en") else "pt"
    p = settings_path()
    with _lock:
        root = _read_file(p)
        if root is None:
            root = ET.Element("PROPERTIES")
        node = next((v for v in root.iter("VALUE") if v.get("name") == "language"), None)
        if node is None:
            node = ET.SubElement(root, "VALUE", {"name": "language"})
        node.set("val", lang)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            body = ET.tostring(root, encoding="unicode")
            tmp.write_text('<?xml version="1.0" encoding="UTF-8"?>\n\n' + body + "\n", encoding="utf-8")
            os.replace(tmp, p)
        except OSError:
            pass  # sem permissão de escrita: vale para esta sessão
        _current = lang
    return lang


def tr(pt: str, en: str) -> str:
    return en if current() == "en" else pt
