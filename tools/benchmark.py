"""Benchmark empírico de modelos (Fase 6, já utilizável).

Estrutura esperada (formato MUSDB18-HQ; pastas próprias por género são bem-vindas):
    bench/
      Kuduro - Faixa 01/   mixture.wav  vocals.wav  drums.wav  bass.wav  other.wav
      Afro House - Faixa 02/ ...
O género é lido do nome da pasta antes de " - ".

    python tools/benchmark.py bench/ --models htdemucs,htdemucs_ft --quality balanced,high --out bench_result

Métricas por stem: SDR, SI-SDR, "bleeding" (energia de outras fontes que entra no stem,
estimada por projecção nas fontes verdadeiras), preservação de transientes (correlação de
envolventes de onset), tempo, RAM máxima. Resultado em CSV + resumo Markdown por género.
"""
from __future__ import annotations

import argparse
import csv
try:
    import resource  # não existe no Windows
except ImportError:
    resource = None
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from stems4u import audio_io  # noqa: E402
from stems4u.models import backends  # noqa: E402
from stems4u.models.registry import Registry  # noqa: E402

EPS = 1e-10


def sdr(ref, est):
    return 10 * np.log10((np.sum(ref ** 2) + EPS) / (np.sum((ref - est) ** 2) + EPS))


def si_sdr(ref, est):
    r, e = ref.reshape(-1), est.reshape(-1)
    a = np.dot(e, r) / (np.dot(r, r) + EPS)
    t = a * r
    return 10 * np.log10((np.sum(t ** 2) + EPS) / (np.sum((e - t) ** 2) + EPS))


def bleeding(refs: dict, name: str, est):
    """Fracção de energia do stem estimado explicada por OUTRAS fontes (mínimos quadrados)."""
    keys = list(refs)
    A = np.stack([refs[k].reshape(-1) for k in keys], axis=1)
    coef, *_ = np.linalg.lstsq(A, est.reshape(-1), rcond=None)
    parts = {k: float(np.sum((coef[i] * A[:, i]) ** 2)) for i, k in enumerate(keys)}
    tot = sum(parts.values()) + EPS
    return {k: v / tot for k, v in parts.items() if k != name}


def onset_env(x, sr, hop=512):
    m = np.abs(x).mean(0)
    n = len(m) // hop
    e = m[: n * hop].reshape(n, hop).max(1)
    return np.maximum(np.diff(e, prepend=e[:1]), 0)


def transient_preservation(ref, est, sr):
    a, b = onset_env(ref, sr), onset_env(est, sr)
    if a.std() < EPS or b.std() < EPS:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--models", default="htdemucs")
    ap.add_argument("--quality", default="balanced")
    ap.add_argument("--out", default="bench_result")
    ap.add_argument("--seconds", type=float, default=0, help="limitar a N segundos por faixa (0 = tudo)")
    a = ap.parse_args()
    reg = Registry()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for song in sorted(p for p in Path(a.folder).iterdir() if (p / "mixture.wav").exists()):
        genre = song.name.split(" - ")[0] if " - " in song.name else "—"
        mix, sr = audio_io.load(song / "mixture.wav")
        refs = {f.stem: audio_io.load(f)[0] for f in song.glob("*.wav") if f.stem != "mixture"}
        if a.seconds:
            n = int(a.seconds * sr)
            mix = mix[:, :n]
            refs = {k: v[:, :n] for k, v in refs.items()}
        x = audio_io.resample(mix, sr, 44100)
        for mid in a.models.split(","):
            spec = reg.get(mid)
            for q in a.quality.split(","):
                t0 = time.time()
                est = backends.make(spec).separate(x, q, lambda f: None, lambda: False)
                dt = time.time() - t0
                rss = (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 if sys.platform != "darwin" else 1024 ** 2)) if resource else 0
                for name, e in est.items():
                    if name not in refs:
                        continue
                    e = audio_io.resample(e, 44100, sr)[:, : refs[name].shape[1]]
                    bl = bleeding(refs, name, e)
                    rows.append({"song": song.name, "genre": genre, "model": mid, "quality": q, "stem": name,
                                 "sdr": round(sdr(refs[name], e), 2), "si_sdr": round(si_sdr(refs[name], e), 2),
                                 "bleed_total_pct": round(100 * sum(bl.values()), 2),
                                 "bleed_detail": ";".join(f"{k}:{100*v:.1f}%" for k, v in sorted(bl.items(), key=lambda kv: -kv[1])[:3]),
                                 "transient_corr": round(transient_preservation(refs[name], e, sr), 3),
                                 "seconds": round(dt, 1), "rt_factor": round(dt / (mix.shape[1] / sr), 2),
                                 "max_rss_mb": round(rss)})
                print(f"{song.name} | {mid}/{q}: {dt:.1f}s")
    if not rows:
        print("Nenhuma faixa encontrada (precisa de mixture.wav + stems de referência).")
        return 1
    with open(out / "benchmark.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    agg = defaultdict(list)
    for r in rows:
        agg[(r["genre"], r["model"], r["quality"], r["stem"])].append(r["sdr"])
    lines = ["| Género | Modelo | Qualidade | Stem | SDR médio (dB) | n |", "|---|---|---|---|---|---|"]
    for (g, m, q, s), v in sorted(agg.items()):
        lines.append(f"| {g} | {m} | {q} | {s} | {np.mean(v):.2f} | {len(v)} |")
    (out / "resumo.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
