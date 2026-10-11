"""Fixtures de teste.

O "oráculo" é um separador SÓ DE TESTE: recebe as fontes verdadeiras de uma mistura
sintética e devolve-as, para validar tudo o que está à volta do modelo
(planeamento, Other, sincronização, taxas, exportação, API). Nunca é registado
na aplicação nem aparece na interface. A qualidade dos modelos reais é medida
pelo benchmark (tools/benchmark.py) e pelo teste real em CI.
"""
import os
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("STEMS4U_BUILD", "dev")
    from stems4u import config
    home = tmp_path / "home"
    for attr, sub in (("DATA_DIR", "data"), ("CACHE_DIR", "cache"), ("MODELS_DIR", "data/models"),
                      ("LOG_DIR", "data/logs"), ("PROJECTS_DIR", "data/projects")):
        monkeypatch.setattr(config, attr, home / sub)
    config.ensure_dirs()
    yield


SR = 48000


def synth_sources(seconds=8.0, sr=SR, seed=1):
    rng = np.random.default_rng(seed)
    n = int(seconds * sr)
    t = np.arange(n) / sr
    beat = 0.5  # 120 bpm

    def hits(period, offset, decay, sig):
        env = np.zeros(n)
        for s in np.arange(offset, seconds, period):
            i = int(s * sr)
            k = np.arange(n - i)
            env[i:] += np.exp(-k / (decay * sr))
        return env * sig

    kick = hits(beat, 0, 0.08, np.sin(2 * np.pi * 55 * t)) * 0.5
    snare = hits(beat * 2, beat, 0.06, rng.standard_normal(n)) * 0.15
    toms = hits(beat * 8, beat * 3.5, 0.15, np.sin(2 * np.pi * 140 * t)) * 0.2
    cymb = hits(beat / 2, 0.25, 0.03, rng.standard_normal(n) * 0.5) * 0.05
    bass = 0.25 * np.sin(2 * np.pi * 41.2 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 0.5 * t))
    vocal = 0.2 * np.sin(2 * np.pi * 220 * t + 3 * np.sin(2 * np.pi * 5 * t)) * (np.sin(2 * np.pi * 0.25 * t) > 0)
    other = 0.08 * (np.sin(2 * np.pi * 330 * t) + np.sin(2 * np.pi * 415 * t))

    def st(x, pan=0.0):
        return np.stack([x * (1 - pan), x * (1 + pan)]).astype(np.float32)

    src = {"kick": st(kick), "snare": st(snare, 0.1), "toms": st(toms, -0.4), "cymbals": st(cymb, 0.3),
           "bass": st(bass), "vocals": st(vocal), "other": st(other, -0.2)}
    src["drums"] = src["kick"] + src["snare"] + src["toms"] + src["cymbals"]
    mix = src["drums"] + src["bass"] + src["vocals"] + src["other"]
    return mix, src


class Oracle:
    """Separador de teste que conhece as fontes verdadeiras (à taxa da mistura)."""

    def __init__(self, spec, sources, sr_src):
        self.spec, self.sources, self.sr_src = spec, sources, sr_src

    def separate(self, audio, quality, progress, should_stop):
        from stems4u import audio_io
        out = {}
        n_src = int(round(next(iter(self.sources.values())).shape[-1] * 44100 / self.sr_src))
        if n_src != audio.shape[-1]:  # pré-visualização (excerto): divide o sinal pelas saídas
            k = len(self.spec.outputs)
            progress(1.0)
            return {s: audio / k for s in self.spec.outputs}
        for stem, _ in self.spec.outputs.items():
            if stem in self.sources:
                out[stem] = audio_io.resample(self.sources[stem], self.sr_src, 44100)
            else:
                out[stem] = np.zeros_like(audio)
        if self.spec.input is None and "other" in self.spec.outputs:
            covered = sum(v for k, v in out.items() if k != "other")
            out["other"] = audio - covered
        progress(1.0)
        return out


@pytest.fixture
def song(tmp_path):
    import soundfile as sf
    mix, src = synth_sources()
    p = tmp_path / "Teste Kuduro.wav"
    sf.write(str(p), mix.T, SR, subtype="FLOAT")
    return p, mix, src


def install_fake_models(ids):
    from stems4u import config
    from stems4u.models.registry import Registry
    reg = Registry()
    for mid in ids:
        m = reg.get(mid)
        d = config.MODELS_DIR / mid
        d.mkdir(parents=True, exist_ok=True)
        names = [m.model_filename] if m.backend == "audio_separator" else [f["name"] for f in m.files]
        for n in names:
            (d / n).write_bytes(b"x")
    return reg
