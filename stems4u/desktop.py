"""App desktop: janela nativa (WKWebView no macOS, WebView2 no Windows) via pywebview.

A interface é a mesma de ui/index.html; o motor corre no mesmo processo
numa thread separada, por isso a interface nunca bloqueia.
"""
from __future__ import annotations

from .config import ensure_dirs, get_logger
from .server import Engine, serve

log = get_logger("stems4u.desktop")


def main():
    ensure_dirs()
    try:
        import webview
    except ImportError:
        import webbrowser
        engine = Engine()
        _, url = serve(engine)
        print(f"pywebview não instalado — a abrir no browser: {url}")
        webbrowser.open(url)
        input("Carrega Enter para sair…")
        return

    engine = Engine()
    holder = {}

    def picker(kind: str):
        win = holder["win"]
        if kind == "folder":
            r = win.create_file_dialog(webview.FOLDER_DIALOG)
        elif kind == "project":
            r = win.create_file_dialog(webview.OPEN_DIALOG, file_types=("Projecto STEMS4U (*.s4u)",))
        else:
            r = win.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=False, file_types=(
                "Áudio (*.wav;*.aif;*.aiff;*.flac;*.mp3;*.m4a;*.aac;*.ogg)",
                "Todos os ficheiros (*.*)"))
        if not r:
            return None
        return r[0] if isinstance(r, (list, tuple)) else r

    engine.picker = picker
    _, url = serve(engine)
    holder["win"] = webview.create_window("STEMS4U by Piradex", url, width=1360, height=880,
                                          min_size=(980, 640), background_color="#0E0F13")
    webview.start(debug=False)


if __name__ == "__main__":
    main()
