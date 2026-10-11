"""Métricas de áudio (Audio Metrics Engine).

Loudness segundo ITU-R BS.1770-4 / EBU R128 (filtro K, gating absoluto -70 LUFS
e relativo -10 LU). True peak com sobreamostragem 4x (BS.1770 anexo 2).
"""
from __future__ import annotations

import math

import numpy as np
from scipy.signal import lfilter, resample_poly, welch

EPS = 1e-12


def db(x: float) -> float:
    return 20.0 * math.log10(max(x, EPS))


def _biquads_k(sr: int):
    # Filtro K da BS.1770 recalculado para qualquer taxa (formulação pré-distorcida da libebur128;
    # a 48 kHz reproduz os coeficientes publicados na norma).
    f0, G, Q = 1681.974450955533, 3.999843853973347, 0.7071752369554196
    K = math.tan(math.pi * f0 / sr)
    Vh = 10 ** (G / 20)
    Vb = Vh ** 0.4996667741545416
    a0 = 1 + K / Q + K * K
    shelf = (np.array([(Vh + Vb * K / Q + K * K) / a0, 2 * (K * K - Vh) / a0, (Vh - Vb * K / Q + K * K) / a0]),
             np.array([1.0, 2 * (K * K - 1) / a0, (1 - K / Q + K * K) / a0]))
    f0, Q = 38.13547087602444, 0.5003270373238773
    K = math.tan(math.pi * f0 / sr)
    a0 = 1 + K / Q + K * K
    hp = (np.array([1.0, -2.0, 1.0]), np.array([1.0, 2 * (K * K - 1) / a0, (1 - K / Q + K * K) / a0]))
    return shelf, hp


def lufs_integrated(audio: np.ndarray, sr: int) -> float:
    x = np.asarray(audio, dtype=np.float64)
    (b1, a1), (b2, a2) = _biquads_k(sr)
    y = lfilter(b2, a2, lfilter(b1, a1, x, axis=-1), axis=-1)
    block, hop = int(0.4 * sr), int(0.1 * sr)
    n = y.shape[-1]
    if n < block:
        z = np.mean(y ** 2, axis=-1, keepdims=True)
    else:
        cs = np.concatenate([np.zeros((y.shape[0], 1)), np.cumsum(y ** 2, axis=-1)], axis=-1)
        starts = np.arange(0, n - block + 1, hop)
        z = (cs[:, starts + block] - cs[:, starts]) / block
    lk = -0.691 + 10 * np.log10(np.sum(z, axis=0) + EPS)  # canais L/R com peso 1
    z_abs = z[:, lk > -70]
    if z_abs.shape[1] == 0:
        return -math.inf
    rel = -0.691 + 10 * math.log10(np.sum(np.mean(z_abs, axis=1)) + EPS) - 10
    keep = (lk > -70) & (lk > rel)
    if not np.any(keep):
        return -math.inf
    return -0.691 + 10 * math.log10(np.sum(np.mean(z[:, keep], axis=1)) + EPS)


def true_peak(audio: np.ndarray) -> float:
    up = resample_poly(np.asarray(audio, dtype=np.float64), 4, 1, axis=-1)
    return float(np.max(np.abs(up))) if up.size else 0.0


def analyze(audio: np.ndarray, sr: int, full: bool = True) -> dict:
    x = np.asarray(audio, dtype=np.float64)
    peak = float(np.max(np.abs(x))) if x.size else 0.0
    rms = float(np.sqrt(np.mean(x ** 2))) if x.size else 0.0
    out = {"peak_db": round(db(peak), 2), "rms_db": round(db(rms), 2),
           "crest_db": round(db(peak) - db(rms), 2) if rms > 0 else None}
    if not full:
        return out
    lufs = lufs_integrated(x, sr)
    tp = true_peak(x)
    L, R = x[0], x[-1]
    mid, side = (L + R) / 2, (L - R) / 2
    em, es = float(np.sum(mid ** 2)), float(np.sum(side ** 2))
    den = math.sqrt(float(np.sum(L ** 2)) * float(np.sum(R ** 2)))
    corr = float(np.sum(L * R) / den) if den > 0 else 1.0
    f, p = welch(mid, fs=sr, nperseg=min(4096, max(256, len(mid))))
    centroid = float(np.sum(f * p) / np.sum(p)) if np.sum(p) > 0 else 0.0
    # Dynamic range simples: diferença entre percentil 95 e 10 de RMS em janelas de 3 s.
    win = 3 * sr
    if x.shape[-1] > 2 * win:
        frames = x[:, : (x.shape[-1] // win) * win].reshape(x.shape[0], -1, win)
        r = np.sqrt(np.mean(frames ** 2, axis=(0, 2)))
        r = r[r > 1e-6]
        dr = float(db(np.percentile(r, 95)) - db(np.percentile(r, 10))) if r.size > 2 else None
    else:
        dr = None
    out.update({
        "true_peak_db": round(db(tp), 2),
        "lufs": round(lufs, 2) if math.isfinite(lufs) else None,
        "dynamic_range_db": round(dr, 2) if dr is not None else None,
        "stereo_width": round(es / (em + es) * 2, 3) if em + es > 0 else 0.0,  # 0 mono, 1 = M e S iguais
        "correlation": round(corr, 3),
        "spectral_centroid_hz": round(centroid, 1),
    })
    return out


def reconstruction(mix: np.ndarray, estimate: np.ndarray) -> dict:
    """Compara a soma dos stems com a mistura original."""
    m = np.asarray(mix, dtype=np.float64)
    err = m - np.asarray(estimate, dtype=np.float64)
    em, ee = float(np.sum(m ** 2)), float(np.sum(err ** 2))
    snr = 10 * math.log10(em / ee) if ee > 0 else math.inf
    acc = max(0.0, 1.0 - ee / em) * 100 if em > 0 else 100.0
    return {"snr_db": round(snr, 2) if math.isfinite(snr) else None,
            "accuracy_pct": round(acc, 3),
            "max_abs_error": float(np.max(np.abs(err))) if err.size else 0.0}


def presence_db(stem: np.ndarray, mix: np.ndarray) -> float:
    """Energia do stem relativamente à mistura (dB). Muito baixo = sem conteúdo real."""
    es = float(np.mean(np.asarray(stem, dtype=np.float64) ** 2))
    em = float(np.mean(np.asarray(mix, dtype=np.float64) ** 2))
    return 10 * math.log10((es + EPS) / (em + EPS))


def peaks_for_waveform(audio: np.ndarray, buckets: int = 2000) -> list[list[float]]:
    mono = np.max(np.abs(audio), axis=0)
    n = mono.shape[-1]
    if n == 0:
        return []
    edges = np.linspace(0, n, buckets + 1).astype(int)
    return [round(float(mono[a:b].max()) if b > a else 0.0, 4) for a, b in zip(edges[:-1], edges[1:])]
