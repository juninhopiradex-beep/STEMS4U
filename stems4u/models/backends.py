"""Backends de inferência. Cada um recebe áudio [2, N] float32 à taxa do modelo
e devolve {stem_id: [2, N]} com exactamente N amostras (sem deslocamento).

Novos backends (ONNX, MLX, cloud) implementam a mesma interface.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Callable

import numpy as np

from ..chunking import Cancelled, fit, process_chunked
from ..config import UserError, get_logger
from .registry import ModelSpec

log = get_logger("stems4u.backends")

# Parâmetros por modo de qualidade (shifts = nº de passagens com deslocamento aleatório).
QUALITY_PARAMS = {
    "fast": {"shifts": 0, "overlap": 0.10},
    "balanced": {"shifts": 1, "overlap": 0.25},
    "high": {"shifts": 2, "overlap": 0.25},
    "ultra": {"shifts": 5, "overlap": 0.50},
}


def torch_device(prefer: str = "auto"):
    try:
        import torch
    except ImportError as exc:
        raise UserError("Motor de IA (PyTorch) não está instalado.",
                        "Reinstala o STEMS4U ou corre: pip install -r requirements.txt", "torch_missing") from exc
    if prefer in ("auto", "cuda") and torch.cuda.is_available():
        return torch.device("cuda")
    if prefer in ("auto", "mps") and getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
        return torch.device("mps")
    torch.set_num_threads(max(1, (os.cpu_count() or 2)))
    return torch.device("cpu")


class Separator:
    def __init__(self, spec: ModelSpec, device: str = "auto"):
        self.spec, self.device_pref = spec, device

    def separate(self, audio: np.ndarray, quality: str, progress: Callable[[float], None],
                 should_stop: Callable[[], bool]) -> dict[str, np.ndarray]:
        raise NotImplementedError


class DemucsSeparator(Separator):
    _cache: dict[str, object] = {}

    def _model(self):
        key = f"{self.spec.id}@{self.device_pref}"
        if key not in self._cache:
            try:
                from demucs.pretrained import get_model
            except ImportError as exc:
                raise UserError("Pacote demucs em falta.", "pip install demucs==4.0.1 --no-deps",
                                "demucs_missing") from exc
            dev = torch_device(self.device_pref)
            log.info("A carregar %s em %s", self.spec.id, dev)
            model = get_model(self.spec.demucs_name, repo=Path(self.spec.dir))
            model.to(dev).eval()
            self._cache.clear()  # um modelo de cada vez em memória (máquinas com pouca RAM)
            self._cache[key] = (model, dev)
        return self._cache[key]

    def separate(self, audio, quality, progress, should_stop):
        import torch
        from demucs.apply import apply_model

        model, dev = self._model()
        params = QUALITY_PARAMS.get(quality, QUALITY_PARAMS["balanced"])
        sources = list(model.sources)
        inv = {src: stem for stem, src in self.spec.outputs.items()}

        def run(block: np.ndarray) -> dict[str, np.ndarray]:
            wav = torch.from_numpy(np.ascontiguousarray(block))
            ref = wav.mean(0)
            mean, std = ref.mean(), ref.std() + 1e-8
            x = ((wav - mean) / std)[None]
            try:
                with torch.no_grad():
                    out = apply_model(model, x, shifts=params["shifts"], split=True,
                                      overlap=params["overlap"], device=dev, progress=False)[0]
            except RuntimeError as exc:
                if "out of memory" in str(exc).lower():
                    raise UserError("Memória de vídeo (VRAM) insuficiente.",
                                    "Escolhe o modo Rápido ou processamento por CPU.", "oom") from exc
                raise
            out = (out * std + mean).cpu().numpy()
            return {inv[s]: fit(out[i], block.shape[-1]) for i, s in enumerate(sources) if s in inv}

        # Blocos de 30 s: progresso real, cancelamento e memória limitada em máquinas antigas.
        return process_chunked(audio, self.spec.sample_rate, run, chunk_s=30.0, overlap_s=3.0,
                               progress=progress, should_stop=should_stop)


class AudioSeparatorBackend(Separator):
    """Roformer / MDX23C via python-audio-separator (código MIT). Só build de desenvolvimento
    enquanto as licenças dos pesos não estiverem confirmadas."""

    def separate(self, audio, quality, progress, should_stop):
        try:
            from audio_separator.separator import Separator as AS
        except ImportError as exc:
            raise UserError("Backend Roformer não instalado.", "pip install audio-separator", "backend_missing") from exc
        import soundfile as sf

        if should_stop():
            raise Cancelled()
        tmp = Path(tempfile.mkdtemp(prefix="s4u_as_"))
        try:
            src = tmp / "in.wav"
            sf.write(str(src), audio.T, self.spec.sample_rate, subtype="FLOAT")
            sep = AS(model_file_dir=str(self.spec.dir), output_dir=str(tmp), output_format="WAV",
                     log_level=30)
            sep.load_model(model_filename=self.spec.model_filename)
            progress(0.1)
            files = sep.separate(str(src))
            progress(1.0)
            result = {}
            for f in files:
                p = Path(f) if Path(f).is_absolute() else tmp / f
                tag = p.stem.split("(")[-1].rstrip(")").lower() if "(" in p.stem else p.stem.lower()
                # nome mais longo primeiro: "noreverb" não pode ser confundido com "reverb"
                for stem, name in sorted(self.spec.outputs.items(), key=lambda kv: -len(kv[1])):
                    if name.lower() in tag and stem not in result:
                        data, _ = sf.read(str(p), dtype="float32", always_2d=True)
                        result[stem] = fit(data.T, audio.shape[-1])
                        break
            if not result:
                raise UserError("O modelo não devolveu os stems esperados.", ", ".join(map(str, files)))
            return result
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def make(spec: ModelSpec, device: str = "auto") -> Separator:
    if spec.backend == "demucs":
        return DemucsSeparator(spec, device)
    if spec.backend == "audio_separator":
        return AudioSeparatorBackend(spec, device)
    raise UserError(f"Backend desconhecido: {spec.backend}")
