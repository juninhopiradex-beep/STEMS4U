"""Descarrega os modelos com URL pública, calcula o SHA-256 completo e grava-o no manifesto.

Corre em CI (GitHub Actions tem acesso à rede) ou no teu Mac:
    python tools/pin_models.py            # mostra os hashes
    python tools/pin_models.py --write    # grava-os em stems4u/models/manifest.json
Depois do --write, o verificador fail-closed aceita esses modelos numa build pública.
"""
import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

MANIFEST = Path(__file__).resolve().parent.parent / "stems4u" / "models" / "manifest.json"


def sha256_url(url: str) -> str:
    h = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=120) as r:
        while chunk := r.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bad = 0
    for m in data["models"]:
        for f in m["files"]:
            if not f.get("url"):
                continue
            digest = sha256_url(f["url"])
            ok = not f.get("sha256_prefix") or digest.startswith(f["sha256_prefix"])
            print(f"{m['id']:<14} {f['name']:<26} {digest} {'OK' if ok else 'PREFIXO NÃO CONFERE'}")
            if not ok:
                bad += 1
            elif a.write:
                f["sha256"] = digest
    if a.write and not bad:
        MANIFEST.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("Manifesto actualizado.")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
