# engine/app/ingestion/presets.py
from dataclasses import asdict, dataclass

from .chunker import ParentChunk, chunk_parent_child


class UnknownChunkPreset(ValueError):
    pass


class SemanticChunkerUnavailable(ValueError):
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


@dataclass(frozen=True)
class ChunkConfigSnapshot:
    preset_id: str
    parent_tokens: int
    child_tokens: int
    overlap_tokens: int
    separator: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _validate_overrides(preset: ChunkPreset, overrides: dict) -> dict:
    valid_keys = {"parent_tokens", "child_tokens", "overlap_tokens"}
    unknown = set(overrides.keys()) - valid_keys
    if unknown:
        raise ValueError(f"Unknown override keys: {sorted(unknown)}")
    result = dict(overrides)
    for key in ("parent_tokens", "child_tokens", "overlap_tokens"):
        if key in result and (not isinstance(result[key], (int, float)) or result[key] <= 0):
            raise ValueError(f"Override {key} must be positive integer: {result[key]}")
    return result


def _chunk_semantic(text: str, preset: ChunkPreset) -> list[ParentChunk]:
    try:
        try:
            from langchain.text_splitter import RecursiveCharacterTextSplitter
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=preset.parent_tokens,
                chunk_overlap=preset.overlap_tokens,
                separators=["\n\n", "\n", "。", ".", " "],
            )
            docs = splitter.create_documents([text])
            result = []
            for doc in docs:
                parent = ParentChunk(doc.page_content, 1, None)
                parent.children = chunk_parent_child(
                    doc.page_content,
                    parent_tokens=preset.parent_tokens,
                    child_tokens=preset.child_tokens,
                    overlap_tokens=preset.overlap_tokens,
                )
                result.append(parent)
            return result
        except ImportError:
            raise SemanticChunkerUnavailable(
                "Semantic chunker requires langchain-text-splitters"
            )
    except SemanticChunkerUnavailable:
        raise
    except Exception as exc:
        raise SemanticChunkerUnavailable(
            f"semantic chunker error: {type(exc).__name__}: {exc}"
        )


def chunk_with_preset(text: str, preset_id: str, overrides: dict | None = None) -> list[ParentChunk]:
    if preset_id not in PRESETS:
        raise UnknownChunkPreset(preset_id)
    preset = PRESETS[preset_id]

    overrides = overrides or {}
    _validate_overrides(preset, overrides)

    parent_tokens = int(overrides.get("parent_tokens", preset.parent_tokens))
    child_tokens = int(overrides.get("child_tokens", preset.child_tokens))
    overlap_tokens = int(overrides.get("overlap_tokens", preset.overlap_tokens))

    if preset_id == "semantic":
        return _chunk_semantic(text, preset)

    return chunk_parent_child(
        text,
        parent_tokens=parent_tokens,
        child_tokens=child_tokens,
        overlap_tokens=overlap_tokens,
        separator=preset.separator,
    )


def chunk_config_snapshot(preset_id: str, overrides: dict | None = None) -> ChunkConfigSnapshot:
    if preset_id not in PRESETS:
        raise UnknownChunkPreset(preset_id)
    preset = PRESETS[preset_id]
    overrides = overrides or {}
    return ChunkConfigSnapshot(
        preset_id=preset_id,
        parent_tokens=int(overrides.get("parent_tokens", preset.parent_tokens)),
        child_tokens=int(overrides.get("child_tokens", preset.child_tokens)),
        overlap_tokens=int(overrides.get("overlap_tokens", preset.overlap_tokens)),
        separator=preset.separator,
    )
