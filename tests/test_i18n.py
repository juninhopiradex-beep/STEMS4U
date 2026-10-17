"""Idioma partilhado com os plugins Piradex (Piradex.settings, formato PropertiesFile XML do JUCE)."""
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from stems4u import i18n

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def settings(tmp_path, monkeypatch):
    p = tmp_path / "Piradex" / "Piradex.settings"
    monkeypatch.setenv("PIRADEX_SETTINGS", str(p))
    monkeypatch.setattr(i18n, "_current", None)
    return p


def test_reads_file_written_by_juce_plugins(settings):
    settings.parent.mkdir(parents=True)
    settings.write_text('<?xml version="1.0" encoding="UTF-8"?>\n\n<PROPERTIES>\n'
                        '  <VALUE name="otherPluginKey" val="42"/>\n  <VALUE name="language" val="en"/>\n</PROPERTIES>\n')
    assert i18n.current() == "en"
    assert i18n.tr("Áudio", "Audio") == "Audio"


def test_set_preserves_other_values_and_is_juce_readable(settings):
    settings.parent.mkdir(parents=True)
    settings.write_text('<PROPERTIES><VALUE name="otherPluginKey" val="42"/></PROPERTIES>')
    assert i18n.set("en") == "en"
    root = ET.fromstring(settings.read_text(encoding="utf-8"))
    vals = {v.get("name"): v.get("val") for v in root.iter("VALUE")}
    assert vals == {"otherPluginKey": "42", "language": "en"}
    i18n.set("pt")
    assert i18n.reload() == "pt"


def test_first_run_follows_system_language(settings, monkeypatch):
    monkeypatch.setattr(i18n, "system_language", lambda: "en")
    assert i18n.current() == "en"
    assert not settings.exists()  # só grava quando o utilizador escolhe


def test_corrupt_file_falls_back(settings, monkeypatch):
    settings.parent.mkdir(parents=True)
    settings.write_text("isto não é xml")
    monkeypatch.setattr(i18n, "system_language", lambda: "pt")
    assert i18n.current() == "pt"
    i18n.set("en")  # reescreve um ficheiro válido
    assert i18n.reload() == "en"


def _ui_dictionary() -> set[str]:
    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    block = html[html.index("const EN = {"):html.index("const EN_DATE")]
    return set(re.findall(r'"((?:[^"\\]|\\.)*)":"', block))


def test_engine_texts_have_english_translation():
    """Tudo o que o motor envia para a interface (stems, roadmap, notas dos modelos) tem tradução."""
    from stems4u import stems
    keys = _ui_dictionary()
    missing = []
    for s in list(stems.STEMS.values()) + [stems.OTHER]:
        missing += [t for t in (s.label, s.hint) if t not in keys]
    for r in stems.ROADMAP:
        missing += [t for t in (r["label"], r["reason"]) if t not in keys]
    man = json.loads((ROOT / "stems4u" / "models" / "manifest.json").read_text(encoding="utf-8"))
    for m in man["models"]:
        nota = (m.get("quality") or {}).get("nota")
        if nota:
            missing.append(nota) if nota not in keys else None
        w = m["license"].get("weights")
        if w and w != "MIT" and w not in keys:
            missing.append(w)
    assert not missing, missing


def test_web_page_matches_app_page():
    ui = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    web = (ROOT / "index.html").read_text(encoding="utf-8")
    assert web.endswith(ui), "index.html (GitHub Pages) tem de ser ui/index.html com o cabeçalho HTML"


def test_engine_error_messages_have_english_translation():
    """Mensagens de erro fixas (UserError) e de progresso do motor estão no dicionário EN da interface."""
    import ast
    keys = _ui_dictionary()
    missing = []
    for p in sorted((ROOT / "stems4u").rglob("*.py")):
        if p.name == "cli.py":
            continue
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if not isinstance(n, ast.Call):
                continue
            name = getattr(n.func, "id", getattr(n.func, "attr", ""))
            args = n.args[:2] if name == "UserError" else n.args[2:3] if name == "ev" else []
            for a in args:
                if (isinstance(a, ast.Constant) and isinstance(a.value, str) and a.value
                        and not a.value.startswith("pip ") and a.value not in keys):  # comandos não se traduzem
                    missing.append(f"{p.name}: {a.value}")
    assert not missing, missing
