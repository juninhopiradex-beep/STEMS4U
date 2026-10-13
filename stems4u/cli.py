"""Interface de linha de comandos.

  stems4u separate musica.wav --stems vocals,kick,bass --quality high --out ~/Stems
  stems4u separate musica.wav --stems vocals --preview 30
  stems4u models list | install htdemucs | import drumsep_inagoy 49469ca8.th | verify htdemucs
  stems4u info          (hardware, stems disponíveis)
  stems4u licenca entrar | estado | sair   (senha master ou beta)
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


def selftest() -> int:
    """Corre o caminho real de separação (Demucs + PyTorch + chunking + export) com o modelo de
    teste do próprio Demucs, que não precisa de download. Falha se faltar alguma biblioteca."""
    import tempfile
    from pathlib import Path

    import numpy as np

    from . import audio_io, metrics
    from .models.backends import DemucsSeparator
    from .models.registry import ModelSpec

    spec = ModelSpec({"id": "selftest", "name": "Demucs (teste)", "demucs_name": "demucs_unittest",
                      "outputs": {"drums": "drums", "bass": "bass", "other": "other", "vocals": "vocals"},
                      "sample_rate": 44100, "files": [], "backend": "demucs"})
    x = (np.random.default_rng(0).standard_normal((2, 44100 * 40)) * 0.1).astype(np.float32)
    out = DemucsSeparator(spec, "cpu").separate(x, "fast", lambda p: None, lambda: False)
    assert set(out) == {"drums", "bass", "other", "vocals"}, out.keys()
    assert all(v.shape == x.shape for v in out.values())
    with tempfile.TemporaryDirectory() as d:
        r = audio_io.write(Path(d) / "t", out["vocals"], 44100, "wav24")
        y, sr = audio_io.load(r["path"])
        assert y.shape == x.shape and sr == 44100
    metrics.analyze(x, 44100)
    # Rede MDX23C (DrumSep 6 peças) com pesos aleatórios: confirma que o código e o STFT estão na app.
    import torch
    from .models.mdx23c.config import MDX23CConfig
    from .models.mdx23c.model import TFC_TDF_net
    cfg = MDX23CConfig.drumsep_6stem()
    net = TFC_TDF_net(cfg, torch.device("cpu")).eval()
    chunk = cfg.audio.hop_length * (cfg.inference.dim_t - 1)
    with torch.no_grad():
        y = net(torch.zeros(1, 2, chunk))
    assert tuple(y.shape[-2:]) == (2, chunk), y.shape
    # Acesso por senha: chaves presentes, PBKDF2 e identificador do computador a funcionar na app empacotada.
    from . import license as lic
    assert lic.KEYS and len(lic.pbkdf2_hex("x", "00" * 16)) == 64 and lic._device_id()
    print("SELFTEST OK — Demucs, PyTorch, chunking, export e métricas a funcionar")
    return 0


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
    lc = sub.add_parser("licenca", help="senha de acesso (master ou beta)")
    lc.add_argument("action", choices=["entrar", "estado", "sair"])
    lc.add_argument("--nao-lembrar", action="store_true", help="não guardar a sessão neste computador")
    sub.add_parser("selftest", help="verifica o motor completo (usado no CI sobre a app empacotada)")
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
        if a.cmd == "selftest":
            return selftest()
        if a.cmd == "licenca":
            from .license import License
            lic = License()
            if a.action == "estado":
                print(lic.status()["label"])
                return 0 if lic.unlocked else 1
            if a.action == "sair":
                lic.lock()
                print("Sessão terminada neste computador.")
                return 0
            import getpass
            res = lic.try_password(getpass.getpass("Senha STEMS4U: "), remember=not a.nao_lembrar)
            if res != "ok":
                print("Esta senha beta já expirou." if res == "expired" else "Senha errada.", file=sys.stderr)
                return 1
            print("Desbloqueado: " + lic.status()["label"])
            return 0
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
            from .license import License, locked_error
            if not a.dry_run and not License().unlocked:
                err = locked_error()
                err.hint = "Corre primeiro: stems4u licenca entrar"
                raise err
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
