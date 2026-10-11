"""Pipeline de separação: import → plano → separação → reconstrução → métricas → export.

Garantias:
- Todos os stems têm exactamente o mesmo nº de amostras, a mesma taxa e começam
  no mesmo sample que a mistura original.
- Other = mistura − Σ(folhas), por isso Σ(folhas) + Other reconstrói a mistura
  (até ao arredondamento do formato de exportação).
- Nenhum stem é normalizado. Stems sem conteúdo real não são exportados
  (ficam dentro de Other) e o relatório diz porquê.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable

import numpy as np

from . import __version__, audio_io, config, metrics, stems
from .chunking import Cancelled
from .config import UserError, get_logger
from .models import backends
from .models.registry import ModelSpec, Registry

log = get_logger("stems4u.pipeline")

QUALITIES = ("fast", "balanced", "high", "ultra")
EMPTY_THRESHOLD_DB = -50.0   # stem 50 dB abaixo da mistura = sem conteúdo útil


@dataclass
class JobRequest:
    input: str
    stems: list[str]
    outdir: str
    quality: str = "balanced"
    fmt: str = "wav24"
    device: str = "auto"
    drop_empty: bool = True
    preview_seconds: float | None = None
    use_cache: bool = True


@dataclass
class Stage:
    model_id: str
    input: str | None          # None = mistura; senão id do stem de entrada
    produces: list[str]

    def to_dict(self):
        return asdict(self)


@dataclass
class JobResult:
    outdir: str
    tracks: list[dict] = field(default_factory=list)
    report: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- plano
def available_stems(reg: Registry) -> dict[str, list[str]]:
    """stem_id -> modelos utilizáveis que o produzem (respeitando dependências de entrada)."""
    usable = reg.usable()
    roots = {s for m in usable if m.input is None for s in m.outputs}
    avail: dict[str, list[str]] = {}
    changed = True
    while changed:
        changed = False
        for m in usable:
            if m.input is None or m.input in roots or m.input in avail:
                for s in m.outputs:
                    if s == "other":
                        continue
                    if m.id not in avail.setdefault(s, []):
                        avail[s].append(m.id)
                        changed = True
    return avail


def _pick(models: list[ModelSpec], quality: str) -> ModelSpec:
    # Preferência: (1) tier inclui o modo pedido, (2) modelo mais especializado (menos saídas),
    # (3) o mais lento — em modelos da mesma família, mais lento = mais passagens = melhor.
    return max(models, key=lambda m: (quality in m.tiers, -len(m.outputs), m.speed_cpu_rt))


def plan(selected: list[str], quality: str, reg: Registry) -> list[Stage]:
    if quality not in QUALITIES:
        raise UserError(f"Modo de qualidade inválido: {quality}")
    sel = stems.expand(selected)
    if not sel:
        raise UserError("Escolhe pelo menos um instrumento para separar.", "", "nothing_selected")
    for s in sel:
        stems.get(s)
    usable = {m.id: m for m in reg.usable()}
    avail = available_stems(reg)
    missing = [s for s in sel if s not in avail]
    if missing:
        names = ", ".join(stems.get(s).label for s in missing)
        raise UserError(f"Sem modelo instalado para: {names}.", "Instala o modelo no gestor de modelos.",
                        "model_not_found")

    stages: list[Stage] = []
    needed: set[str] = set(sel)
    # Resolve dependências de cima para baixo: filhos precisam do stem de entrada do seu modelo.
    child_models: dict[str, ModelSpec] = {}
    for s in sel:
        producers = [usable[i] for i in avail[s]]
        mix_level = [m for m in producers if m.input is None]
        if mix_level:
            continue
        m = _pick(producers, quality)
        child_models[m.id] = m
    frontier = list(child_models.values())
    while frontier:
        m = frontier.pop()
        needed.add(m.input)
        producers = [usable[i] for i in avail.get(m.input, [])]
        if not any(p.input is None for p in producers):
            p = _pick(producers, quality)
            if p.id not in child_models:
                child_models[p.id] = p
                frontier.append(p)

    base_needed = {s for s in needed if any(usable[i].input is None for i in avail.get(s, []))}
    if base_needed:
        cands = [m for m in usable.values() if m.input is None and base_needed <= set(m.outputs)]
        if not cands:  # nenhum modelo cobre tudo: um estágio por stem (ex.: noise vem de outro modelo)
            groups: dict[str, set[str]] = {}
            for s in base_needed:
                m = _pick([usable[i] for i in avail[s] if usable[i].input is None], quality)
                groups.setdefault(m.id, set()).add(s)
            for mid, ss in groups.items():
                stages.append(Stage(mid, None, stems.ordered(ss)))
        else:
            # Prefere o modelo "base" principal (Demucs) que cobre tudo; 6s só se guitarra/piano forem pedidos.
            m = _pick(cands, quality)
            stages.append(Stage(m.id, None, stems.ordered(base_needed & set(m.outputs))))
    # filhos por ordem topológica (entrada já produzida)
    produced = {s for st in stages for s in st.produces}
    pending = list(child_models.values())
    while pending:
        progressed = False
        for m in list(pending):
            if m.input in produced:
                prod = [s for s in m.outputs if s in needed or s in sel]
                stages.append(Stage(m.id, m.input, stems.ordered(prod)))
                produced |= set(prod)
                pending.remove(m)
                progressed = True
        if not progressed:
            raise UserError("Dependências de modelos impossíveis de resolver.")
    return stages


# --------------------------------------------------------------------------- execução
def _safe_name(s: str) -> str:
    return re.sub(r"[^\w\-. ]+", "_", s).strip() or "Mistura"


def _cache_path(key: str) -> Path:
    return config.CACHE_DIR / "separations" / f"{key}.npz"


def run(req: JobRequest, reg: Registry | None = None,
        emit: Callable[[dict], None] = lambda e: None,
        should_stop: Callable[[], bool] = lambda: False,
        separator_factory: Callable[[ModelSpec, str], backends.Separator] | None = None) -> JobResult:
    t0 = time.time()
    reg = reg or Registry()
    factory = separator_factory or backends.make
    outdir_root = Path(req.outdir)
    if not str(req.outdir).strip():
        raise UserError("Escolhe uma pasta de trabalho antes de separar.", "", "no_outdir")

    def ev(stage: str, progress: float, message: str = "", **kw):
        emit({"stage": stage, "progress": round(min(max(progress, 0), 1), 4), "message": message,
              "elapsed": round(time.time() - t0, 1), **kw})
        if should_stop():
            raise Cancelled()

    ev("import", 0.0, "A ler o ficheiro")
    info = audio_io.probe(req.input)
    mix, sr = audio_io.load(req.input)
    if req.preview_seconds:
        n = int(req.preview_seconds * sr)
        start = int(max(0, min(mix.shape[1] * 0.3, mix.shape[1] - n)))
        mix = mix[:, start:start + n]
    stages = plan(req.stems, req.quality, reg)
    log.info("Plano: %s", [s.to_dict() for s in stages])
    ev("import", 0.04, "A converter para 44,1 kHz", plan=[s.to_dict() for s in stages])

    x = audio_io.resample(mix, sr, config.MODEL_SR)
    produced: dict[str, np.ndarray] = {}
    base_recon = None
    span = 0.80 / max(1, len(stages))
    in_hash = hashlib.sha256(x.tobytes()).hexdigest()[:24]
    for i, st in enumerate(stages):
        spec = reg.get(st.model_id)
        src = x if st.input is None else produced[st.input]
        p0 = 0.05 + i * span
        key = hashlib.sha256(f"{in_hash}|{st.input}|{spec.id}|{spec.version}|{req.quality}".encode()).hexdigest()[:32]
        cpath = _cache_path(key)
        out = None
        if req.use_cache and cpath.exists():
            try:
                with np.load(cpath) as z:
                    out = {k: z[k] for k in z.files}
                ev("separate", p0 + span, f"{spec.name}: resultado em cache", model=spec.name, cached=True)
            except Exception:  # noqa: BLE001
                out = None
        if out is None:
            ev("separate", p0, f"{spec.name}: a separar", model=spec.name, stems=st.produces)
            sep = factory(spec, req.device)
            out = sep.separate(src, req.quality, lambda f, p0=p0: ev("separate", p0 + f * span,
                                                                    f"{spec.name}: a separar", model=spec.name),
                               should_stop)
            try:
                cpath.parent.mkdir(parents=True, exist_ok=True)
                np.savez(cpath, **{k: v.astype(np.float32) for k, v in out.items()})
            except OSError:
                log.warning("Cache não gravada (disco?)")
        for k, v in out.items():
            if v.shape != src.shape:
                raise UserError(f"{spec.name} devolveu um stem com tamanho errado.", f"{k}: {v.shape}", "model_output")
        if st.input is None and base_recon is None:
            base_recon = metrics.reconstruction(src, sum(v for k, v in out.items()))
            base_recon["model"] = spec.name
        for k, v in out.items():
            if k != "other":
                produced[k] = v

    ev("reconstruct", 0.86, "A reconstruir à taxa original")
    selected = stems.expand(req.stems)
    final: dict[str, np.ndarray] = {}
    for s in selected:
        final[s] = audio_io.resample(produced[s], config.MODEL_SR, sr)
        final[s] = final[s][:, : mix.shape[1]] if final[s].shape[1] >= mix.shape[1] else np.pad(
            final[s], ((0, 0), (0, mix.shape[1] - final[s].shape[1])))

    dropped = []
    presence = {s: round(metrics.presence_db(final[s], mix), 1) for s in selected}
    if req.drop_empty:
        for s in list(final):
            if presence[s] < EMPTY_THRESHOLD_DB:
                dropped.append({"id": s, "label": stems.get(s).label, "presence_db": presence[s],
                                "reason": "Sem conteúdo audível na mistura — mantido dentro de Other."})
                del final[s]
    kept = list(final)
    leaf_ids = stems.leaves(kept)
    other = mix - (sum(final[s] for s in leaf_ids) if leaf_ids else 0)
    other = other.astype(np.float32)
    other_presence = metrics.presence_db(other, mix)
    # Se tudo o que existe foi seleccionado e sobra só resíduo inaudível, não se cria Other vazio.
    export_other = other_presence >= EMPTY_THRESHOLD_DB or not leaf_ids
    recon = metrics.reconstruction(mix, sum(final[s] for s in leaf_ids) + other)

    ev("export", 0.90, "A exportar")
    song = _safe_name(info.title or info.name)
    folder = outdir_root / f"{song} — STEMS4U"
    if req.preview_seconds:
        folder = outdir_root / f"{song} — STEMS4U preview {int(req.preview_seconds)}s"
    folder.mkdir(parents=True, exist_ok=True)
    order = stems.ordered(kept) + (["other"] if export_other else [])
    muted = set(stems.default_muted(kept))
    tracks, warnings = [], []
    for n, sid in enumerate(order, 1):
        audio = other if sid == "other" else final[sid]
        st = stems.get(sid)
        res = audio_io.write(folder / f"{n:02d}_{song}_{st.file_label}", audio, sr, req.fmt)
        if res["warning"]:
            warnings.append(res["warning"])
        tracks.append({
            "id": sid, "label": st.label, "family": st.family, "file": res["path"],
            "muted": sid in muted, "is_leaf": sid in leaf_ids or sid == "other",
            "presence_db": round(other_presence, 1) if sid == "other" else presence[sid],
            "metrics": metrics.analyze(audio, sr),
            "peaks": metrics.peaks_for_waveform(audio, 1200),
        })
        ev("export", 0.90 + 0.09 * n / len(order), f"Exportado {st.label}")

    report = {
        "app": f"STEMS4U {__version__}", "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": info.to_dict(), "request": asdict(req),
        "plan": [s.to_dict() | {"model": reg.get(s.model_id).name,
                                "license": reg.get(s.model_id).license} for s in stages],
        "frames": int(mix.shape[1]), "sample_rate": sr,
        "model_reconstruction": base_recon,
        "final_reconstruction": recon,
        "dropped": dropped, "warnings": warnings,
        "elapsed_s": round(time.time() - t0, 1),
        "mix_metrics": metrics.analyze(mix, sr),
    }
    project = {"type": "stems4u-project", "version": 1, "name": song, "report": report,
               "tracks": [{k: t[k] for k in ("id", "label", "family", "file", "muted")} | {"volume": 1.0}
                          for t in tracks]}
    (folder / f"{song}.s4u").write_text(json.dumps(project, indent=2, ensure_ascii=False), encoding="utf-8")
    (folder / "relatorio.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    ev("done", 1.0, "Exportação pronta")
    return JobResult(str(folder), tracks, report)
