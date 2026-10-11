"""Importação, conversão de taxa e exportação de áudio.

- WAV/AIFF/FLAC/MP3/OGG: libsndfile (soundfile).
- AAC/M4A/ALAC: afconvert no macOS (CoreAudio, já existe no sistema) ou
  ffmpeg no Windows/Linux (binário LGPL ao lado da app ou no PATH).
O ficheiro original nunca é alterado.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, asdict
from fractions import Fraction
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from .config import UserError, get_logger

log = get_logger("stems4u.audio")

SUPPORTED = {".wav", ".wave", ".aif", ".aiff", ".flac", ".mp3", ".ogg", ".m4a", ".aac", ".mp4", ".alac"}
NEEDS_CONVERTER = {".m4a", ".aac", ".mp4", ".alac"}

EXPORT_FORMATS = {
    # id: (extensão, formato libsndfile, subtipo, bits)
    "wav16": (".wav", "WAV", "PCM_16", 16),
    "wav24": (".wav", "WAV", "PCM_24", 24),
    "wav32f": (".wav", "WAV", "FLOAT", 32),
    "aiff24": (".aif", "AIFF", "PCM_24", 24),
    "flac24": (".flac", "FLAC", "PCM_24", 24),
    "flac16": (".flac", "FLAC", "PCM_16", 16),
}


@dataclass
class AudioInfo:
    path: str
    name: str
    format: str
    sample_rate: int
    channels: int
    frames: int
    duration: float
    bit_depth: int | None
    subtype: str
    title: str = ""
    artist: str = ""
    album: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


_BITS = {"PCM_16": 16, "PCM_24": 24, "PCM_32": 32, "FLOAT": 32, "DOUBLE": 64, "PCM_S8": 8, "PCM_U8": 8,
         "ALAC_16": 16, "ALAC_24": 24}


def _check_path(path: str | os.PathLike) -> Path:
    p = Path(path)
    if not p.exists():
        raise UserError("O ficheiro não existe.", f"Verifica o caminho: {p}", "file_not_found")
    if p.suffix.lower() not in SUPPORTED:
        raise UserError(f"Formato {p.suffix} não suportado.", "Usa WAV, AIFF, FLAC, MP3, M4A ou AAC.",
                        "unsupported_format")
    return p


def find_ffmpeg() -> str | None:
    here = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    for cand in (here / "bin" / "ffmpeg", here / "bin" / "ffmpeg.exe"):
        if cand.exists():
            return str(cand)
    return shutil.which("ffmpeg")


def _convert_to_wav(src: Path) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="s4u_")) / (src.stem + ".wav")
    if sys.platform == "darwin" and shutil.which("afconvert"):
        cmd = ["afconvert", "-f", "WAVE", "-d", "LEF32", str(src), str(tmp)]
    else:
        ff = find_ffmpeg()
        if not ff:
            raise UserError("Não foi possível descodificar M4A/AAC.",
                            "Converte para WAV ou instala o ffmpeg (incluído no instalador Windows).",
                            "codec_missing")
        cmd = [ff, "-v", "error", "-y", "-i", str(src), "-c:a", "pcm_f32le", str(tmp)]
    log.debug("A converter: %s", cmd)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not tmp.exists():
        log.error("Conversor falhou: %s", r.stderr)
        raise UserError("O ficheiro parece corrompido ou usa um codec não suportado.", r.stderr[-200:],
                        "decode_failed")
    return tmp


def probe(path: str | os.PathLike) -> AudioInfo:
    p = _check_path(path)
    src = _convert_to_wav(p) if p.suffix.lower() in NEEDS_CONVERTER else p
    try:
        info = sf.info(str(src))
    except Exception as exc:  # noqa: BLE001
        log.exception("probe falhou")
        raise UserError("Não foi possível ler o ficheiro.", str(exc), "decode_failed") from exc
    meta = {}
    try:
        with sf.SoundFile(str(src)) as f:
            meta = f.copy_metadata()
    except Exception:  # noqa: BLE001
        pass
    bits = _BITS.get(info.subtype)
    if p.suffix.lower() in NEEDS_CONVERTER:
        bits = None
    return AudioInfo(str(p), p.stem, p.suffix.lower().lstrip("."), info.samplerate, info.channels,
                     info.frames, info.frames / info.samplerate, bits, info.subtype,
                     meta.get("title", ""), meta.get("artist", ""), meta.get("album", ""))


def load(path: str | os.PathLike) -> tuple[np.ndarray, int]:
    """Devolve (áudio [canais, amostras] float32, sample rate). Mono vira estéreo dual-mono."""
    p = _check_path(path)
    src = _convert_to_wav(p) if p.suffix.lower() in NEEDS_CONVERTER else p
    try:
        data, sr = sf.read(str(src), dtype="float32", always_2d=True)
    except Exception as exc:  # noqa: BLE001
        log.exception("load falhou")
        raise UserError("Não foi possível descodificar o áudio.", str(exc), "decode_failed") from exc
    finally:
        if src is not p:
            shutil.rmtree(src.parent, ignore_errors=True)
    audio = data.T.copy()
    if audio.shape[0] == 1:
        audio = np.repeat(audio, 2, axis=0)
    elif audio.shape[0] > 2:
        raise UserError("Áudio multicanal (>2) ainda não é suportado.", "Exporta uma mistura estéreo.",
                        "too_many_channels")
    if audio.shape[1] == 0:
        raise UserError("O ficheiro não tem áudio.", "", "empty_file")
    return audio, sr


def resample(audio: np.ndarray, sr_from: int, sr_to: int) -> np.ndarray:
    """Conversão de taxa com filtro polifásico (fase linear, sem desvio temporal)."""
    if sr_from == sr_to:
        return audio
    fr = Fraction(sr_to, sr_from)
    out = resample_poly(audio, fr.numerator, fr.denominator, axis=-1).astype(np.float32)
    target = int(round(audio.shape[-1] * sr_to / sr_from))
    if out.shape[-1] > target:
        out = out[..., :target]
    elif out.shape[-1] < target:
        out = np.pad(out, [(0, 0)] * (out.ndim - 1) + [(0, target - out.shape[-1])])
    return out


def _tpdf_dither(audio: np.ndarray, bits: int, rng: np.random.Generator) -> np.ndarray:
    lsb = 1.0 / (2 ** (bits - 1))
    return audio + (rng.random(audio.shape) - rng.random(audio.shape)) * lsb


def write(path: str | os.PathLike, audio: np.ndarray, sr: int, fmt: str = "wav24",
          dither: bool = True) -> dict:
    """Exporta sem normalizar. Em formatos inteiros com pico > 0 dBFS, devolve aviso de clipping."""
    if fmt not in EXPORT_FORMATS:
        raise UserError(f"Formato de exportação desconhecido: {fmt}")
    ext, container, subtype, bits = EXPORT_FORMATS[fmt]
    path = Path(path).with_suffix(ext)
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    warn = None
    data = audio
    if subtype != "FLOAT":
        if dither and bits <= 16:
            data = _tpdf_dither(audio, bits, np.random.default_rng(0))
        if peak > 1.0:
            warn = (f"Pico de {20*np.log10(peak):+.2f} dBFS em {path.name}: haveria clipping em {bits} bits. "
                    f"Exporta em WAV 32-bit float para preservar o sinal.")
        data = np.clip(data, -1.0, 1.0)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(path), data.T, sr, format=container, subtype=subtype)
    except OSError as exc:
        if getattr(exc, "errno", None) == 28:
            raise UserError("Disco cheio.", "Liberta espaço ou escolhe outra pasta.", "disk_full") from exc
        raise UserError("Erro ao exportar.", str(exc), "export_failed") from exc
    except Exception as exc:  # noqa: BLE001
        raise UserError("Erro ao exportar.", str(exc), "export_failed") from exc
    return {"path": str(path), "peak": peak, "warning": warn}
