"""Teste com o modelo REAL HTDemucs. Só corre quando o modelo está instalado
(CI no GitHub Actions instala-o; localmente: stems4u models install htdemucs).

    STEMS4U_REAL=1 pytest tests/test_real_model.py -s
"""
import os

import numpy as np
import pytest
import soundfile as sf

from conftest import SR, synth_sources

pytestmark = pytest.mark.skipif(not os.environ.get("STEMS4U_REAL"), reason="definir STEMS4U_REAL=1")


@pytest.fixture(autouse=True)
def real_home(monkeypatch):
    # usa a instalação real de modelos (não a pasta temporária dos outros testes)
    from stems4u import config
    monkeypatch.setattr(config, "MODELS_DIR", config._base_dirs()[0] / "models")
    yield


def test_htdemucs_end_to_end(tmp_path):
    from stems4u.models.registry import Registry
    from stems4u.pipeline import JobRequest, run
    reg = Registry()
    if not reg.get("htdemucs").is_installed():
        reg.install("htdemucs")
    mix, src = synth_sources(seconds=20)
    p = tmp_path / "sintetico.wav"
    sf.write(str(p), mix.T, SR, subtype="FLOAT")
    res = run(JobRequest(str(p), ["vocals", "drums", "bass"], str(tmp_path / "o"), quality="fast", fmt="wav32f"), reg)
    tracks = {t["id"]: sf.read(t["file"], always_2d=True)[0].T for t in res.tracks}
    for k, v in tracks.items():
        assert v.shape == mix.shape, k                          # mesma duração e canais
    assert np.max(np.abs(sum(tracks.values()) - mix)) < 1e-4    # reconstrução exacta com Other
    mr = res.report["model_reconstruction"]
    print("\nReconstrução do modelo:", mr)
    for k in ("drums", "bass"):
        e, r = tracks[k], src[k]
        s = 10 * np.log10(np.sum(r ** 2) / (np.sum((r - e) ** 2) + 1e-12))
        print(f"SDR {k}: {s:.2f} dB")
        assert np.sqrt(np.mean(e ** 2)) > 1e-3, f"{k} saiu silencioso"
