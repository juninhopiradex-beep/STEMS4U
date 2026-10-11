"""Processamento por blocos com sobreposição.

Cada bloco é multiplicado por uma janela trapezoidal com rampas sin²; na zona
de sobreposição a rampa de saída de um bloco (cos²) e a de entrada do seguinte
(sin²) somam exactamente 1, por isso não há variação de volume nas junções.
As contribuições são ainda divididas pela soma das janelas (segurança numérica).
Não há deslocamento temporal: cada amostra de saída corresponde à mesma amostra
de entrada — sem clicks, gaps nem mudanças de fase introduzidas pelo chunking.
"""
from __future__ import annotations

from typing import Callable

import numpy as np


class Cancelled(Exception):
    pass


def _ramp(n: int) -> np.ndarray:
    return np.sin(0.5 * np.pi * (np.arange(n) + 0.5) / n) ** 2


def window(length: int, fade_in: int, fade_out: int) -> np.ndarray:
    w = np.ones(length, dtype=np.float64)
    if fade_in > 0:
        w[:fade_in] = _ramp(fade_in)
    if fade_out > 0:
        w[length - fade_out:] *= _ramp(fade_out)[::-1]
    return w


def plan_blocks(n: int, chunk: int, overlap: int) -> list[tuple[int, int]]:
    if n <= chunk:
        return [(0, n)]
    hop = chunk - overlap
    starts = list(range(0, n - chunk + 1, hop))
    if starts[-1] + chunk < n:
        starts.append(n - chunk)
    return [(s, s + chunk) for s in starts]


def process_chunked(audio: np.ndarray, sr: int, fn: Callable[[np.ndarray], dict[str, np.ndarray]],
                    chunk_s: float = 60.0, overlap_s: float = 4.0,
                    progress: Callable[[float], None] | None = None,
                    should_stop: Callable[[], bool] | None = None) -> dict[str, np.ndarray]:
    """Aplica `fn` (bloco [C, N] -> {stem: [C, N]}) a um sinal longo, bloco a bloco."""
    n = audio.shape[-1]
    chunk, ov = int(chunk_s * sr), int(overlap_s * sr)
    blocks = plan_blocks(n, chunk, ov) if chunk > 2 * ov else [(0, n)]
    acc: dict[str, np.ndarray] = {}
    norm = np.zeros(n, dtype=np.float64)
    for i, (s, e) in enumerate(blocks):
        if should_stop and should_stop():
            raise Cancelled()
        fin = blocks[i - 1][1] - s if i > 0 else 0
        fout = e - blocks[i + 1][0] if i < len(blocks) - 1 else 0
        w = window(e - s, fin, fout)
        out = fn(audio[..., s:e])
        for k, v in out.items():
            if k not in acc:
                acc[k] = np.zeros((audio.shape[0], n), dtype=np.float64)
            acc[k][:, s:e] += fit(v, e - s) * w
        norm[s:e] += w
        if progress:
            progress((i + 1) / len(blocks))
    norm[norm == 0] = 1.0
    return {k: (v / norm).astype(np.float32) for k, v in acc.items()}


def fit(x: np.ndarray, n: int) -> np.ndarray:
    """Garante exactamente n amostras (corta ou acrescenta zeros no fim; nunca desloca)."""
    if x.shape[-1] == n:
        return x
    if x.shape[-1] > n:
        return x[..., :n]
    return np.pad(x, [(0, 0)] * (x.ndim - 1) + [(0, n - x.shape[-1])])
