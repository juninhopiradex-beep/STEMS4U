import json
import math
import threading
import time
import urllib.request
from functools import partial

import numpy as np
import pytest
import soundfile as sf

from conftest import SR, Oracle, install_fake_models, synth_sources


# ------------------------------------------------------------------ chunking
@pytest.mark.parametrize("n", [1000, 44100 * 7 + 13, 44100 * 30 + 1, 44100 * 61])
def test_chunking_identity_is_exact(n):
    from stems4u.chunking import process_chunked
    rng = np.random.default_rng(0)
    x = rng.standard_normal((2, n)).astype(np.float32)
    out = process_chunked(x, 44100, lambda b: {"a": b, "b": -0.5 * b}, chunk_s=5.0, overlap_s=1.0)
    assert out["a"].shape == x.shape
    assert np.max(np.abs(out["a"] - x)) < 1e-6
    assert np.max(np.abs(out["b"] + 0.5 * x)) < 1e-6


def test_chunk_crossfade_no_level_jump():
    """Um modelo que muda ligeiramente o ganho por bloco não pode criar degraus (clicks)."""
    from stems4u.chunking import process_chunked
    x = np.ones((2, 44100 * 20), dtype=np.float32)
    calls = iter([1.0, 0.9, 1.1, 0.95, 1.05, 1.0, 1.0, 1.0, 1.0])
    out = process_chunked(x, 44100, lambda b: {"a": b * next(calls)}, chunk_s=5.0, overlap_s=1.0)["a"][0]
    assert np.max(np.abs(np.diff(out))) < 1e-3  # transição suave, nunca um salto


def test_window_ramps_sum_to_one():
    from stems4u.chunking import _ramp
    r = _ramp(1000)
    assert np.allclose(r + r[::-1], 1.0)


# ------------------------------------------------------------------ métricas
def test_lufs_ebu_reference():
    from stems4u.metrics import lufs_integrated
    for sr in (44100, 48000, 96000):
        t = np.arange(sr * 10) / sr
        a = 10 ** (-23 / 20) * np.sin(2 * np.pi * 1000 * t)
        assert abs(lufs_integrated(np.stack([a, a]), sr) - (-23.0)) < 0.1


def test_true_peak_intersample():
    from stems4u.metrics import true_peak
    n = np.arange(4800)
    x = np.sin(2 * np.pi * n / 4 + np.pi / 4)  # amostras em ±0.707, pico real 1.0
    assert np.max(np.abs(x)) < 0.71
    assert true_peak(np.stack([x, x])) > 0.97


def test_reconstruction_metric():
    from stems4u.metrics import reconstruction
    x = np.random.default_rng(1).standard_normal((2, 1000))
    assert reconstruction(x, x)["accuracy_pct"] == 100.0
    r = reconstruction(x, x * 0.9)
    assert 98.9 < r["accuracy_pct"] < 99.1 and abs(r["snr_db"] - 20) < 0.01


# ------------------------------------------------------------------ taxonomia
def test_leaves_and_muted_parents():
    from stems4u import stems
    sel = ["vocals", "lead_vocal", "drums", "kick", "bass"]
    assert stems.leaves(sel) == ["lead_vocal", "kick", "bass"]
    assert stems.default_muted(sel) == ["vocals", "drums"]
    assert "lead_vocal_dry" in stems.expand(["vocal_reverb"])


# ------------------------------------------------------------------ planeamento
def test_plan_picks_specialised_models():
    from stems4u.pipeline import plan
    reg = install_fake_models(["htdemucs", "htdemucs_ft", "htdemucs_6s", "drumsep_inagoy", "melband_karaoke"])
    p = plan(["vocals"], "balanced", reg)
    assert [s.model_id for s in p] == ["htdemucs"]
    assert [s.model_id for s in plan(["vocals"], "high", reg)] == ["htdemucs_ft"]
    assert [s.model_id for s in plan(["guitar", "bass"], "high", reg)] == ["htdemucs_6s"]
    p = plan(["kick", "lead_vocal"], "balanced", reg)
    ids = [s.model_id for s in p]
    assert ids[0] == "htdemucs" and set(ids[1:]) == {"drumsep_inagoy", "melband_karaoke"}
    assert set(p[0].produces) == {"vocals", "drums"}  # dependências internas, invisíveis ao utilizador


def test_plan_refuses_missing_models():
    from stems4u.config import UserError
    from stems4u.pipeline import plan
    reg = install_fake_models(["htdemucs"])
    with pytest.raises(UserError):
        plan(["kick"], "balanced", reg)


def test_public_build_fails_closed(monkeypatch):
    from stems4u.models.registry import Registry, check_public_build
    reg = install_fake_models(["htdemucs", "drumsep_inagoy"])
    assert any("drumsep" in p for p in check_public_build(reg, ["drumsep_inagoy"]))
    assert check_public_build(reg, ["nao_existe"])
    monkeypatch.setenv("STEMS4U_BUILD", "public")
    assert not Registry().get("drumsep_inagoy").usable()[0]


# ------------------------------------------------------------------ pipeline completo
def _run(song, tmp_path, stems_sel, **kw):
    from stems4u.pipeline import JobRequest, run
    p, mix, src = song
    reg = install_fake_models(["htdemucs", "htdemucs_6s", "drumsep_inagoy"])
    factory = lambda spec, dev: Oracle(spec, src, SR)  # noqa: E731
    events = []
    req = JobRequest(input=str(p), stems=stems_sel, outdir=str(tmp_path / "out"), **kw)
    return run(req, reg, events.append, separator_factory=factory), events, mix, src


def test_pipeline_vocals_only_gives_other_complement(song, tmp_path):
    res, events, mix, src = _run(song, tmp_path, ["vocals"], fmt="wav32f")
    ids = [t["id"] for t in res.tracks]
    assert ids == ["vocals", "other"]
    v, sr = sf.read(res.tracks[0]["file"], always_2d=True)
    o, _ = sf.read(res.tracks[1]["file"], always_2d=True)
    assert sr == SR and v.shape[0] == mix.shape[1] == o.shape[0]           # mesma taxa e duração
    assert np.max(np.abs(v.T + o.T - mix)) < 1e-5                          # Σ = mistura
    assert np.sqrt(np.mean((o.T - (mix - src["vocals"])) ** 2)) < 2e-3     # Other = tudo menos voz
    assert res.report["final_reconstruction"]["accuracy_pct"] > 99.999
    assert events[-1]["stage"] == "done"
    assert [e["progress"] for e in events] == sorted(e["progress"] for e in events)


def test_pipeline_drum_detail_parent_muted_and_sync(song, tmp_path):
    res, _, mix, src = _run(song, tmp_path, ["drums", "kick", "snare", "bass"], fmt="wav32f")
    by = {t["id"]: t for t in res.tracks}
    assert list(by) == ["drums", "kick", "snare", "bass", "other"]
    assert by["drums"]["muted"] and not by["kick"]["muted"]
    leaves = [sf.read(by[i]["file"], always_2d=True)[0].T for i in ("kick", "snare", "bass", "other")]
    assert np.max(np.abs(sum(leaves) - mix)) < 1e-5      # sem duplicação: pai fora da soma
    k = leaves[0]
    # alinhamento sample-a-sample: correlação máxima no atraso 0
    xc = [np.dot(k[0, 10000:200000], src["kick"][0, 10000 + d:200000 + d]) for d in (-2, -1, 0, 1, 2)]
    assert int(np.argmax(xc)) == 2
    assert (tmp_path / "out" / "Teste Kuduro — STEMS4U" / "Teste Kuduro.s4u").exists()


def test_pipeline_drops_empty_stems(song, tmp_path):
    res, _, mix, _ = _run(song, tmp_path, ["vocals", "piano"])
    ids = [t["id"] for t in res.tracks]
    assert "piano" not in ids
    assert res.report["dropped"][0]["id"] == "piano"


def test_pipeline_preview_and_16bit(song, tmp_path):
    res, _, mix, _ = _run(song, tmp_path, ["bass"], preview_seconds=5, fmt="wav16")
    d, sr = sf.read(res.tracks[0]["file"], always_2d=True)
    assert d.shape[0] == 5 * SR and sf.info(res.tracks[0]["file"]).subtype == "PCM_16"


def test_cancel(song, tmp_path):
    from stems4u.chunking import Cancelled
    from stems4u.pipeline import JobRequest, run
    p, _, src = song
    reg = install_fake_models(["htdemucs"])
    with pytest.raises(Cancelled):
        run(JobRequest(str(p), ["vocals"], str(tmp_path)), reg, should_stop=lambda: True,
            separator_factory=lambda s, d: Oracle(s, src, SR))


def test_write_clip_warning(tmp_path):
    from stems4u import audio_io
    x = np.stack([np.linspace(-1.5, 1.5, 1000)] * 2).astype(np.float32)
    assert audio_io.write(tmp_path / "a", x, 44100, "wav24")["warning"]
    assert audio_io.write(tmp_path / "b", x, 44100, "wav32f")["warning"] is None
    y, _ = sf.read(str(tmp_path / "b.wav"), always_2d=True)
    assert np.allclose(y.T, x)  # float não corta nem normaliza


def test_mono_and_mp3_import(tmp_path):
    from stems4u import audio_io
    t = np.arange(44100) / 44100
    sf.write(str(tmp_path / "m.flac"), 0.3 * np.sin(2 * np.pi * 440 * t), 44100)
    a, sr = audio_io.load(tmp_path / "m.flac")
    assert a.shape == (2, 44100) and sr == 44100


# ------------------------------------------------------------------ API
def test_api_token_and_job(song, tmp_path):
    from stems4u.server import Engine, serve
    p, mix, src = song
    install_fake_models(["htdemucs"])
    eng = Engine(separator_factory=lambda s, d: Oracle(s, src, SR))
    httpd, url = serve(eng)
    base = url.split("/?")[0]
    try:
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(base + "/api/info")
        def call(path, body=None):
            req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                         headers={"X-S4U-Token": eng.token, "Content-Type": "application/json"})
            return urllib.request.urlopen(req, timeout=30)
        info = json.load(call("/api/info"))
        avail = {c["id"] for c in info["categories"] if c["available"]}
        assert {"vocals", "drums", "bass"} <= avail and "kick" not in avail
        job = json.load(call("/api/jobs", {"input": str(p), "stems": ["vocals", "bass"], "outdir": str(tmp_path / "o")}))
        stream = call(f"/api/jobs/{job['id']}/events").read().decode()
        assert "event: end" in stream and '"completed"' in stream
        snap = json.load(call(f"/api/jobs/{job['id']}"))
        f = snap["result"]["tracks"][0]["file"]
        assert call("/api/file?path=" + urllib.parse.quote(f)).status == 200
        r = call("/api/pcm?path=" + urllib.parse.quote(f))
        n, ch = int(r.headers["X-S4U-Frames"]), int(r.headers["X-S4U-Channels"])
        pcm = np.frombuffer(r.read(), dtype="<f4").reshape(ch, n)
        ref, _ = sf.read(f, dtype="float32", always_2d=True)
        assert np.array_equal(pcm, ref.T) and int(r.headers["X-S4U-SR"]) == SR
        with pytest.raises(urllib.error.HTTPError):
            call("/api/file?path=" + urllib.parse.quote("/etc/passwd"))
        with pytest.raises(urllib.error.HTTPError):
            call("/api/pcm?path=" + urllib.parse.quote("/etc/passwd"))
    finally:
        httpd.shutdown()
