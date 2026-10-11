"""Taxonomia de stems.

Cada stem tem um id estável (usado em API, CLI, cache e ficheiros), um nome
para a interface (PT), um nome de ficheiro (EN, estilo DAW) e um "pai".
A hierarquia é o que permite a lógica de Other sem duplicar material:

    Other = mistura − Σ(folhas exportadas)

em que "folha" é um stem selecionado que não tem nenhum descendente selecionado.
Um pai exportado juntamente com filhos começa em mute no mixer.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Iterable


@dataclass(frozen=True)
class Stem:
    id: str
    label: str          # nome na interface
    file_label: str     # nome no ficheiro exportado
    family: str         # vocals | drums | bass | music | fx | other
    parent: str | None = None
    hint: str = ""
    order: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


STEMS: dict[str, Stem] = {s.id: s for s in [
    Stem("vocals", "Voz", "Vocals", "vocals", None, "Toda a voz (base para voz detalhada)", 10),
    Stem("lead_vocal", "Voz principal", "LeadVocal", "vocals", "vocals", "Voz à frente", 11),
    Stem("backing_vocals", "Coros e segundas vozes", "BackingVocals", "vocals", "vocals", "Harmonias e dobras", 12),
    Stem("lead_vocal_dry", "Voz principal (seca)", "LeadVocalDry", "vocals", "lead_vocal", "Voz principal sem reverb", 13),
    Stem("vocal_reverb", "Reverb vocal", "VocalReverb", "vocals", "lead_vocal", "Cauda e ambiência da voz principal", 14),

    Stem("drums", "Bateria", "Drums", "drums", None, "Bateria completa", 20),
    Stem("kick", "Bombo", "Kick", "drums", "drums", "Kick", 21),
    Stem("snare", "Tarola", "Snare", "drums", "drums", "Snare e clap", 22),
    Stem("toms", "Timbalões", "Toms", "drums", "drums", "Toms", 23),
    Stem("hihat", "Hi-hat", "HiHat", "drums", "drums", "Chimbal aberto e fechado", 24),
    Stem("cymbals", "Pratos", "Cymbals", "drums", "drums", "Crash, ride (e hi-hat se não separado)", 25),

    Stem("bass", "Baixo", "Bass", "bass", None, "Baixo eléctrico, synth bass e 808", 30),

    Stem("guitar", "Guitarra", "Guitar", "music", None, "Acústica e eléctrica", 40),
    Stem("piano", "Piano e teclados", "Piano", "music", None, "Piano, Rhodes, órgão", 41),

    Stem("noise", "Ruído", "Noise", "fx", None, "Ruído de fundo e artefactos", 60),
]}

OTHER = Stem("other", "Other", "Other", "other", None, "Tudo o que não foi seleccionado", 99)

# Categorias pedidas no caderno de requisitos que ainda não têm modelo fiável
# e licenciável. Aparecem na interface como indisponíveis, com o motivo.
ROADMAP: list[dict] = [
    {"id": "clap", "label": "Clap", "reason": "Sem modelo público que separe clap de snare com fiabilidade; vai em Tarola."},
    {"id": "percussion", "label": "Percussão (congas, djembé, shakers…)", "reason": "Nenhum modelo aberto treinado em percussão africana. Plano: dataset próprio (Kuduro, Afro House) — ver ARQUITETURA.md §9."},
    {"id": "sub_bass", "label": "Sub-bass / 808", "reason": "Divisão por banda é possível mas não é separação de fonte; planeado como ferramenta de split por frequência (Fase 3)."},
    {"id": "synth", "label": "Synth / Pads", "reason": "Modelos 'synth' existentes têm SDR baixo e licenças por confirmar."},
    {"id": "strings", "label": "Cordas", "reason": "Modelos comunitários existem (MVSep) mas licença dos pesos por confirmar."},
    {"id": "brass", "label": "Metais", "reason": "Idem — sem pesos com licença inequívoca."},
    {"id": "adlibs", "label": "Ad-libs", "reason": "Não existe modelo; ad-libs ficam com a voz principal ou coros."},
    {"id": "ambience", "label": "Ambiência / Reverb global", "reason": "Modelos de de-reverb existem só para voz; global é experimental."},
]


# Stems que só fazem sentido em par complementar (o modelo divide um sinal em dois).
COMPANIONS: dict[str, list[str]] = {"vocal_reverb": ["lead_vocal_dry"], "lead_vocal_dry": ["vocal_reverb"]}


def expand(selected: Iterable[str]) -> list[str]:
    sel = set(selected)
    for s in list(sel):
        sel.update(COMPANIONS.get(s, []))
    return ordered(sel - {"other"})


def get(stem_id: str) -> Stem:
    if stem_id == "other":
        return OTHER
    try:
        return STEMS[stem_id]
    except KeyError:
        raise ValueError(f"Stem desconhecido: {stem_id}") from None


def ancestors(stem_id: str) -> list[str]:
    out, cur = [], get(stem_id).parent
    while cur:
        out.append(cur)
        cur = get(cur).parent
    return out


def leaves(selected: Iterable[str]) -> list[str]:
    """Stems seleccionados sem descendentes seleccionados (entram na soma do Other)."""
    sel = set(selected)
    has_selected_child = {a for s in sel for a in ancestors(s) if a in sel}
    return sorted((s for s in sel if s not in has_selected_child), key=lambda s: get(s).order)


def default_muted(selected: Iterable[str]) -> list[str]:
    """Pais exportados juntamente com filhos: começam em mute para não duplicar."""
    sel = set(selected)
    return sorted({a for s in sel for a in ancestors(s) if a in sel}, key=lambda s: get(s).order)


def ordered(ids: Iterable[str]) -> list[str]:
    return sorted(ids, key=lambda s: get(s).order)
