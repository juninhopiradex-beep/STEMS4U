"""API interna (Service Layer) entre a interface e o motor.

HTTP local em 127.0.0.1 (porta aleatória) + Server-Sent Events para progresso.
Todas as rotas /api exigem o token de sessão (cabeçalho X-S4U-Token ou ?t=),
para que outras páginas abertas no browser não consigam usar o motor.
A mesma API servirá a futura versão cloud, um plugin ou um cliente móvel.
"""
from __future__ import annotations

import json
import mimetypes
import secrets
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__, audio_io, config, hardware, stems
from .config import UserError, get_logger
from .jobs import JobManager
from .models.registry import Registry, build_profile
from .pipeline import JobRequest, available_stems

log = get_logger("stems4u.server")


def ui_path() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    for cand in (base / "ui" / "index.html", Path(__file__).resolve().parent.parent / "ui" / "index.html"):
        if cand.exists():
            return cand
    raise FileNotFoundError("ui/index.html")


class Engine:
    def __init__(self, separator_factory=None):
        self.token = secrets.token_urlsafe(24)
        self.registry = Registry()
        self.jobs = JobManager(self.registry, separator_factory)
        self.allowed_roots: set[Path] = set()
        self._hw = None
        self.picker = None  # definido pela app desktop (diálogos nativos)
        self.install_state: dict = {"running": False}

    def hw(self):
        if self._hw is None:
            self._hw = hardware.detect()
        return self._hw

    # ---------- instalação de modelos em segundo plano (com progresso para a interface)
    def start_install(self, ids: list[str]) -> dict:
        if self.install_state.get("running"):
            return self.install_state
        self.install_state = {"running": True, "ids": ids, "current": None, "pct": 0.0, "error": None, "done": False}

        def work():
            st = self.install_state
            try:
                for n, mid in enumerate(ids):
                    st["current"] = self.registry.get(mid).name
                    self.registry.install(mid, lambda p, f, n=n: st.update(pct=(n + p) / len(ids)))
                st.update(pct=1.0, done=True)
            except UserError as exc:
                st["error"] = {"message": exc.message, "hint": exc.hint}
            except Exception as exc:  # noqa: BLE001
                log.exception("instalação de modelos")
                st["error"] = {"message": "Falha ao instalar o modelo.", "hint": str(exc)}
            finally:
                st["running"] = False

        threading.Thread(target=work, daemon=True, name="s4u-install").start()
        return self.install_state

    def info(self) -> dict:
        avail = available_stems(self.registry)
        cats = []
        for s in stems.STEMS.values():
            ok = s.id in avail
            reason = ""
            if not ok:
                producers = [m for m in self.registry.models.values() if s.id in m.outputs]
                reason = producers[0].usable()[1] if producers else "Sem modelo."
            install = None
            if not ok:
                for m in self.registry.models.values():
                    if (s.id in m.outputs and not m.is_installed() and m.backend in ("demucs", "mdx23c")
                            and m.files and all(f.get("url") for f in m.files)
                            and (build_profile() != "public" or m.license_ok_for_public)):
                        install = {"id": m.id, "name": m.name, "size_mb": sum(f.get("size_mb", 0) for f in m.files),
                                   "license": m.license.get("status")}
                        reason = "Instala o modelo para activar."
                        break
            cats.append(s.to_dict() | {"available": ok, "reason": reason, "models": avail.get(s.id, []),
                                       "install": install})
        return {"app": "STEMS4U by Piradex", "version": __version__, "build": build_profile(),
                "hardware": self.hw(), "categories": cats, "roadmap": stems.ROADMAP,
                "models": self.registry.list(), "formats": list(audio_io.EXPORT_FORMATS),
                "native_dialogs": self.picker is not None}


def make_handler(engine: Engine):
    class H(BaseHTTPRequestHandler):
        server_version = f"STEMS4U/{__version__}"

        def log_message(self, fmt, *args):  # silencioso; erros vão para o log
            log.debug("%s %s", self.address_string(), fmt % args)

        # ---------- utilitários
        def _json(self, obj, code=200):
            body = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _auth(self, q) -> bool:
            tok = self.headers.get("X-S4U-Token") or (q.get("t") or [""])[0]
            if not secrets.compare_digest(tok, engine.token):
                self._json({"code": "forbidden", "message": "Token inválido"}, 403)
                return False
            return True

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}")

        # ---------- GET
        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            try:
                if u.path in ("/", "/index.html"):
                    data = ui_path().read_bytes()
                    if not data.lstrip().lower().startswith(b"<!doctype"):
                        # o mesmo ficheiro é publicado como página web (que recebe o esqueleto noutro lado)
                        data = b'<!doctype html><html lang="pt"><head><meta charset="utf-8">' + data
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                if not u.path.startswith("/api/") or not self._auth(q):
                    if not u.path.startswith("/api/"):
                        self.send_error(404)
                    return
                if u.path == "/api/models/progress":
                    return self._json(engine.install_state)
                if u.path == "/api/info":
                    return self._json(engine.info())
                if u.path == "/api/jobs":
                    return self._json(engine.jobs.list())
                if u.path.startswith("/api/jobs/") and u.path.endswith("/events"):
                    return self._sse(u.path.split("/")[3])
                if u.path.startswith("/api/jobs/"):
                    return self._json(engine.jobs.jobs[u.path.split("/")[3]].snapshot())
                if u.path == "/api/file":
                    return self._file(q.get("path", [""])[0])
                if u.path == "/api/pcm":
                    return self._pcm(q.get("path", [""])[0])
                if u.path == "/api/project":
                    p = Path(q.get("path", [""])[0]).resolve()
                    proj = json.loads(p.read_text(encoding="utf-8"))
                    if proj.get("type") != "stems4u-project":
                        raise UserError("Este ficheiro não é um projecto STEMS4U.")
                    engine.allowed_roots.add(p.parent)
                    return self._json(proj | {"folder": str(p.parent)})
                self._json({"message": "Rota desconhecida"}, 404)
            except KeyError:
                self._json({"message": "Não encontrado"}, 404)
            except UserError as exc:
                self._json(exc.to_dict(), 400)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as exc:  # noqa: BLE001
                log.exception("GET %s", self.path)
                self._json({"code": "internal", "message": "Erro interno", "hint": str(exc)}, 500)

        def _sse(self, job_id: str):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            i = 0
            while True:
                evs, status = engine.jobs.wait_events(job_id, i)
                for e in evs:
                    self.wfile.write(f"data: {json.dumps(e, ensure_ascii=False)}\n\n".encode())
                i += len(evs)
                if status not in ("queued", "processing") and not evs:
                    snap = engine.jobs.jobs[job_id].snapshot()
                    self.wfile.write(f"event: end\ndata: {json.dumps(snap, ensure_ascii=False, default=str)}\n\n".encode())
                    self.wfile.flush()
                    return
                if not evs:
                    self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()

        def _pcm(self, path: str):
            """Áudio já descodificado em float32 planar (canal 0 inteiro, depois canal 1).
            O mixer não depende do descodificador do WebKit e recebe a taxa original exacta."""
            import numpy as np
            import soundfile as sf
            p = Path(path).resolve()
            if not any(str(p).startswith(str(r)) for r in engine.allowed_roots) or not p.is_file():
                return self._json({"message": "Acesso negado a este ficheiro"}, 403)
            data, sr = sf.read(str(p), dtype="float32", always_2d=True)
            body = np.ascontiguousarray(data.T).astype("<f4").tobytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-S4U-SR", str(sr))
            self.send_header("X-S4U-Frames", str(data.shape[0]))
            self.send_header("X-S4U-Channels", str(data.shape[1]))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            mv = memoryview(body)
            for i in range(0, len(body), 1 << 20):
                self.wfile.write(mv[i:i + (1 << 20)])

        def _file(self, path: str):
            p = Path(path).resolve()
            if not any(str(p).startswith(str(r)) for r in engine.allowed_roots) or not p.is_file():
                return self._json({"message": "Acesso negado a este ficheiro"}, 403)
            ctype = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
            size = p.stat().st_size
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(size))
            self.end_headers()
            with open(p, "rb") as f:
                while chunk := f.read(1 << 20):
                    self.wfile.write(chunk)

        def _binary(self, path: str, q):
            n = int(self.headers.get("Content-Length") or 0)
            name = Path(q.get("name", ["audio"])[0]).name  # sem caminhos
            if path == "/api/upload":
                dest_dir = config.CACHE_DIR / "imports" / secrets.token_hex(6)
            else:
                dest_dir = Path(q.get("dir", [""])[0]).resolve()
                if not any(str(dest_dir).startswith(str(r)) for r in engine.allowed_roots):
                    return self._json({"message": "Pasta não autorizada"}, 403)
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / name
            left = n
            try:
                with open(dest, "wb") as f:
                    while left > 0:
                        chunk = self.rfile.read(min(1 << 20, left))
                        if not chunk:
                            break
                        f.write(chunk)
                        left -= len(chunk)
            except OSError as exc:
                raise UserError("Não foi possível gravar o ficheiro.", str(exc), "write_failed") from exc
            if path == "/api/upload":
                engine.allowed_roots.add(dest_dir)
                return self._json(audio_io.probe(dest).to_dict())
            return self._json({"path": str(dest)})

        # ---------- POST
        def do_POST(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if not self._auth(q):
                return
            try:
                if u.path in ("/api/upload", "/api/save"):
                    return self._binary(u.path, q)
                b = self._body()
                if u.path == "/api/probe":
                    info = audio_io.probe(b["path"])
                    engine.allowed_roots.add(Path(b["path"]).resolve().parent)
                    return self._json(info.to_dict())
                if u.path == "/api/jobs":
                    if not b.get("outdir"):
                        raise UserError("Escolhe uma pasta de trabalho antes de separar.", "", "no_outdir")
                    req = JobRequest(input=b["input"], stems=b["stems"], outdir=b["outdir"],
                                     quality=b.get("quality", "balanced"), fmt=b.get("fmt", "wav24"),
                                     preview_seconds=b.get("preview_seconds"))
                    engine.allowed_roots.add(Path(b["outdir"]).resolve())
                    engine.allowed_roots.add(Path(b["input"]).resolve().parent)
                    return self._json(engine.jobs.submit(req).snapshot())
                if u.path.startswith("/api/jobs/") and u.path.endswith("/cancel"):
                    engine.jobs.cancel(u.path.split("/")[3])
                    return self._json({"ok": True})
                if u.path == "/api/models/install":
                    return self._json(engine.start_install(b.get("ids") or [b["id"]]))
                if u.path == "/api/models/remove":
                    engine.registry.remove(b["id"])
                    return self._json({"ok": True})
                if u.path == "/api/pick" and engine.picker:
                    res = engine.picker(b.get("kind", "file"))
                    if res and b.get("kind") == "folder":
                        engine.allowed_roots.add(Path(res).resolve())
                    return self._json({"path": res})
                if u.path == "/api/reveal":
                    _reveal(b["path"])
                    return self._json({"ok": True})
                self._json({"message": "Rota desconhecida"}, 404)
            except UserError as exc:
                self._json(exc.to_dict(), 400)
            except KeyError as exc:
                self._json({"code": "bad_request", "message": f"Campo em falta: {exc}"}, 400)
            except Exception as exc:  # noqa: BLE001
                log.exception("POST %s", self.path)
                self._json({"code": "internal", "message": "Erro interno", "hint": str(exc)}, 500)

    return H


def _reveal(path: str):
    import subprocess
    p = Path(path)
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(p)])
    elif sys.platform.startswith("win"):
        subprocess.Popen(["explorer", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p)])


def serve(engine: Engine, port: int = 0) -> tuple[ThreadingHTTPServer, str]:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(engine))
    httpd.daemon_threads = True
    url = f"http://127.0.0.1:{httpd.server_address[1]}/?t={engine.token}"
    threading.Thread(target=httpd.serve_forever, daemon=True, name="s4u-http").start()
    log.info("Motor a escutar em %s", url.split("?")[0])
    return httpd, url
