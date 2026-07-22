# engine/app/ingestion/presets.py
from dataclasses import dataclass
from .chunker import ParentChunk, chunk_parent_child


class UnknownChunkPreset(ValueError):
    pass


@dataclass(frozen=True)
class ChunkPreset:
    preset_id: str
    parent_tokens: int
    child_tokens: int
    overlap_tokens: int
    separator: str | None = None


PRESETS: dict[str, ChunkPreset] = {
    "general": ChunkPreset("general", 1200, 384, 64),
    "qa": ChunkPreset("qa", 900, 320, 32, "\nQ:"),
    "book": ChunkPreset("book", 1600, 420, 80),
    "laws": ChunkPreset("laws", 1200, 360, 40, "\n第"),
    "semantic": ChunkPreset("semantic", 1200, 320, 48),
    "separator": ChunkPreset("separator", 1200, 384, 0, "\n---\n"),
}


def chunk_with_preset(text: str, preset_id: str, overrides: dict) -> list[ParentChunk]:
    if preset_id not in PRESETS:
        raise UnknownChunkPreset(preset_id)
    preset = PRESETS[preset_id]
    parent_tokens = int(overrides.get("parent_tokens", preset.parent_tokens))
    child_tokens = int(overrides.get("child_tokens", preset.child_tokens))
    overlap_tokens = int(overrides.get("overlap_tokens", preset.overlap_tokens))
    return chunk_parent_child(
        text,
        parent_tokens=parent_tokens,
        child_tokens=child_tokens,
        overlap_tokens=overlap_tokens,
    )
