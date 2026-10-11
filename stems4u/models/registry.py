"""Model Manager.

- Lê o manifesto (identificador, ficheiros, SHA-256, licença do código vs dos pesos,
  capacidades, requisitos de hardware).
- Instala explicitamente (nunca descarrega a meio de uma separação).
- Verifica hashes; política fail-closed na build pública (STEMS4U_BUILD=public):
  só modelos com license.status == "verified" e SHA-256 fixado são utilizáveis.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .. import config
from ..config import UserError, get_logger

log = get_logger("stems4u.models")
MANIFEST = Path(__file__).with_name("manifest.json")


def build_profile() -> str:
    return os.environ.get("STEMS4U_BUILD", "dev").lower()


@dataclass
class ModelSpec:
    raw: dict = field(repr=False)

    def __getattr__(self, item):
        try:
            return self.raw[item]
        except KeyError:
            raise AttributeError(item) from None

    @property
    def dir(self) -> Path:
        return config.MODELS_DIR / self.raw["id"]

    @property
    def license_ok_for_public(self) -> bool:
        lic = self.raw["license"]
        return (lic.get("status") == "verified" and lic.get("redistribution") is True
                and all(f.get("sha256") for f in self.raw["files"]))

    def is_installed(self) -> bool:
        if self.raw["backend"] == "audio_separator":
            return (self.dir / self.raw["model_filename"]).exists()
        return bool(self.raw["files"]) and all((self.dir / f["name"]).exists() for f in self.raw["files"])

    def usable(self) -> tuple[bool, str]:
        if build_profile() == "public" and not self.license_ok_for_public:
            return False, "Licença dos pesos não confirmada — excluído da build pública."
        if not self.is_installed():
            return False, "Modelo não instalado."
        return True, ""

    def summary(self) -> dict:
        ok, why = self.usable()
        r = self.raw
        return {k: r[k] for k in ("id", "name", "arch", "version", "backend", "input", "outputs",
                                  "sample_rate", "tiers", "speed_cpu_rt", "ram_gb", "vram_gb",
                                  "quality", "author", "attribution", "license")} | {
            "installed": self.is_installed(), "usable": ok, "reason": why,
            "size_mb": sum(f.get("size_mb", 0) for f in r["files"]),
            "manual": next((f["manual"] for f in r["files"] if f.get("manual")), None)}


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(chunk):
            h.update(b)
    return h.hexdigest()


class Registry:
    def __init__(self, manifest: Path = MANIFEST):
        data = json.loads(manifest.read_text(encoding="utf-8"))
        self.models: dict[str, ModelSpec] = {m["id"]: ModelSpec(m) for m in data["models"]}

    def get(self, model_id: str) -> ModelSpec:
        if model_id not in self.models:
            raise UserError(f"Modelo não encontrado: {model_id}", "Abre o gestor de modelos.", "model_not_found")
        return self.models[model_id]

    def usable(self) -> list[ModelSpec]:
        return [m for m in self.models.values() if m.usable()[0]]

    def list(self) -> list[dict]:
        return [m.summary() for m in self.models.values()]

    # ----- instalação -----
    def install(self, model_id: str, progress: Callable[[float, str], None] | None = None) -> dict:
        m = self.get(model_id)
        if m.backend == "audio_separator":
            raise UserError("Este modelo instala-se com 'stems4u models import'.",
                            "Modelos Roformer só em build de desenvolvimento enquanto a licença não for confirmada.")
        m.dir.mkdir(parents=True, exist_ok=True)
        total = len(m.files)
        for i, f in enumerate(m.files):
            dest = m.dir / f["name"]
            if dest.exists() and self._check(dest, f):
                continue
            if not f.get("url"):
                raise UserError(f"{m.name}: instalação manual.", f.get("manual", ""), "manual_install")
            tmp = dest.with_suffix(".part")
            log.info("A descarregar %s", f["url"])
            try:
                with urllib.request.urlopen(f["url"], timeout=60) as r, open(tmp, "wb") as out:
                    size = int(r.headers.get("Content-Length") or 0)
                    got = 0
                    while chunk := r.read(1 << 20):
                        out.write(chunk)
                        got += len(chunk)
                        if progress and size:
                            progress((i + got / size) / total, f["name"])
            except Exception as exc:  # noqa: BLE001
                tmp.unlink(missing_ok=True)
                raise UserError("Falha ao descarregar o modelo.", str(exc), "download_failed") from exc
            if not self._check(tmp, f):
                tmp.unlink(missing_ok=True)
                raise UserError("Hash do modelo não corresponde — ficheiro rejeitado.", f["name"], "hash_mismatch")
            tmp.replace(dest)
        for name, content in m.extra_files.items():
            (m.dir / name).write_text(content, encoding="utf-8")
        self._write_provenance(m)
        return m.summary()

    def import_file(self, model_id: str, src: str) -> dict:
        m = self.get(model_id)
        srcp = Path(src)
        if not srcp.exists():
            raise UserError("Ficheiro não encontrado.", src)
        m.dir.mkdir(parents=True, exist_ok=True)
        name = m.model_filename if m.backend == "audio_separator" else m.files[0]["name"]
        spec = {"name": name, "sha256": ""} if m.backend == "audio_separator" else m.files[0]
        if not self._check(srcp, spec):
            raise UserError("Hash do ficheiro não corresponde ao manifesto.", "", "hash_mismatch")
        shutil.copy2(srcp, m.dir / name)
        for n, content in m.extra_files.items():
            (m.dir / n).write_text(content, encoding="utf-8")
        self._write_provenance(m)
        return m.summary()

    def remove(self, model_id: str) -> None:
        shutil.rmtree(self.get(model_id).dir, ignore_errors=True)

    def verify(self, model_id: str) -> dict:
        m = self.get(model_id)
        res = {}
        for f in m.files:
            p = m.dir / f["name"]
            res[f["name"]] = {"exists": p.exists(), "sha256": sha256_file(p) if p.exists() else None,
                              "ok": p.exists() and self._check(p, f)}
        return res

    @staticmethod
    def _check(path: Path, f: dict) -> bool:
        if not f.get("sha256") and not f.get("sha256_prefix"):
            return True  # sem hash fixado: aceite só em dev (build pública já bloqueia)
        digest = sha256_file(path)
        if f.get("sha256"):
            return digest == f["sha256"]
        return digest.startswith(f["sha256_prefix"])

    def _write_provenance(self, m: ModelSpec) -> None:
        prov = {"id": m.id, "version": m.version, "license": m.license, "author": m.author,
                "files": {f["name"]: sha256_file(m.dir / f["name"]) for f in m.files if (m.dir / f["name"]).exists()}}
        (m.dir / "PROVENANCE.json").write_text(json.dumps(prov, indent=2), encoding="utf-8")


def check_public_build(reg: Registry, bundled_ids: list[str]) -> list[str]:
    """Verificador fail-closed para CI. Devolve lista de problemas (vazia = OK)."""
    problems = []
    for mid in bundled_ids:
        if mid not in reg.models:
            problems.append(f"{mid}: modelo não registado no manifesto")
            continue
        m = reg.models[mid]
        if not m.license_ok_for_public:
            problems.append(f"{mid}: licença não verificada ou SHA-256 por fixar")
    return problems
