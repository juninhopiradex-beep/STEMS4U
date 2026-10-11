"""Interface de linha de comandos.

  stems4u separate musica.wav --stems vocals,kick,bass --quality high --out ~/Stems
  stems4u separate musica.wav --stems vocals --preview 30
  stems4u models list | install htdemucs | import drumsep_inagoy 49469ca8.th | verify htdemucs
  stems4u info          (hardware, stems disponíveis)
  stems4u app           (abre a aplicação)
  stems4u serve         (só o motor/API, para desenvolvimento da interface)
"""
from __future__ import annotations

import argparse
import json
import sys
import time

from . import __version__, hardware, stems
from .chunking import Cancelled
from .config import UserError, ensure_dirs
from .models.registry import Registry, check_public_build
from .pipeline import JobRequest, available_stems, plan, run


def _bar(e: dict):
    p = e.get("progress", 0)
    sys.stdout.write(f"\r[{'#' * int(p * 30):<30}] {p * 100:5.1f}%  {e.get('message', '')[:60]:<60}")
    sys.stdout.flush()
    if e.get("stage") == "done":
        print()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="stems4u", description="STEMS4U by Piradex — separação de stems")
    ap.add_argument("--version", action="version", version=f"STEMS4U {__version__}")
    sub = ap.add_subparsers(dest="cmd")

    s = sub.add_parser("separate", help="separar uma ou mais músicas")
    s.add_argument("inputs", nargs="+")
    s.add_argument("--stems", default="vocals,drums,bass", help="ids separados por vírgula (ver 'stems4u info')")
    s.add_argument("--quality", "--mode", default="balanced", choices=["fast", "balanced", "high", "ultra"])
    s.add_argument("--out", required=True, help="pasta de trabalho")
    s.add_argument("--format", default="wav24", choices=["wav16", "wav24", "wav32f", "aiff24", "flac24", "flac16"])
    s.add_argument("--preview", type=float, choices=[10, 30, 60], help="processar só N segundos")
    s.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda", "mps"])
    s.add_argument("--no-cache", action="store_true")
    s.add_argument("--dry-run", action="store_true", help="mostra o plano de modelos sem processar")

    m = sub.add_parser("models", help="gestor de modelos")
    m.add_argument("action", choices=["list", "install", "remove", "verify", "import", "check-public"])
    m.add_argument("id", nargs="?")
    m.add_argument("file", nargs="?")

    sub.add_parser("info", help="hardware e stems disponíveis")
    sub.add_parser("app", help="abrir a aplicação")
    sv = sub.add_parser("serve", help="só o motor (API local)")
    sv.add_argument("--port", type=int, default=8765)

    a = ap.parse_args(argv)
    ensure_dirs()
    reg = Registry()
    try:
        if a.cmd in (None, "app"):
            from .desktop import main as app_main
            return app_main()
        if a.cmd == "serve":
            from .server import Engine, serve
            eng = Engine()
            _, url = serve(eng, a.port)
            print(f"Abre: {url}")
            while True:
                time.sleep(3600)
        if a.cmd == "info":
            hw = hardware.detect()
            print(json.dumps(hw, indent=2, ensure_ascii=False))
            av = available_stems(reg)
            print("\nStems disponíveis:")
            for st in stems.STEMS.values():
                mark = "✔" if st.id in av else "·"
                print(f"  {mark} {st.id:<16} {st.label}  {', '.join(av.get(st.id, []))}")
            return 0
        if a.cmd == "models":
            if a.action == "list":
                for x in reg.list():
                    flag = "instalado" if x["installed"] else "—"
                    print(f"{x['id']:<18} {x['name']:<46} {flag:<10} licença pesos: {x['license']['weights']} "
                          f"[{x['license']['status']}]")
            elif a.action == "install":
                print(json.dumps(reg.install(a.id, lambda p, n: print(f"\r{n} {p*100:5.1f}%", end="")), indent=1)[:300])
            elif a.action == "import":
                reg.import_file(a.id, a.file)
                print("Importado.")
            elif a.action == "remove":
                reg.remove(a.id)
            elif a.action == "verify":
                print(json.dumps(reg.verify(a.id), indent=2))
            elif a.action == "check-public":
                ids = a.id.split(",") if a.id else [x for x in reg.models]
                probs = check_public_build(reg, ids)
                for p in probs:
                    print("FALHA:", p)
                return 1 if probs else 0
            return 0
        if a.cmd == "separate":
            ids = [x.strip() for x in a.stems.split(",") if x.strip()]
            if a.dry_run:
                for st in plan(ids, a.quality, reg):
                    print(f"{reg.get(st.model_id).name:<40} entrada={st.input or 'mistura':<10} → {', '.join(st.produces)}")
                return 0
            for inp in a.inputs:
                print(f"\n▶ {inp}")
                req = JobRequest(input=inp, stems=ids, outdir=a.out, quality=a.quality, fmt=a.format,
                                 device=a.device, preview_seconds=a.preview, use_cache=not a.no_cache)
                res = run(req, reg, _bar)
                r = res.report
                print(f"Pasta: {res.outdir}")
                for t in res.tracks:
                    mm = t["metrics"]
                    print(f"  {t['label']:<24} {mm['peak_db']:>7.2f} dBFS pico  {mm['lufs'] or float('nan'):>7.2f} LUFS"
                          + ("  (mute por defeito)" if t["muted"] else ""))
                if r.get("model_reconstruction"):
                    mr = r["model_reconstruction"]
                    print(f"Reconstrução do modelo: {mr['accuracy_pct']:.2f}% (SNR {mr['snr_db']} dB)")
                for d in r["dropped"]:
                    print(f"  ! {d['label']}: {d['reason']}")
                for w in r["warnings"]:
                    print(f"  ! {w}")
            return 0
    except UserError as exc:
        print(f"\nErro: {exc.message}" + (f"\n{exc.hint}" if exc.hint else ""), file=sys.stderr)
        return 2
    except Cancelled:
        print("\nCancelado.")
        return 130
    except KeyboardInterrupt:
        print("\nInterrompido.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
