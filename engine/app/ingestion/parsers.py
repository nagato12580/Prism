# engine/app/ingestion/parsers.py
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


class UnsupportedDocument(ValueError):
    pass


@dataclass(frozen=True)
class ParsedDocument:
    markdown: str
    parser_id: str
    page_count: int | None = None
    assets: tuple[str, ...] = ()
    metadata: dict = field(default_factory=dict)


class DocumentParser(Protocol):
    parser_id: str
    extensions: frozenset[str]

    def parse(self, path: Path, config: dict) -> ParsedDocument: ...


class ParserRegistry:
    def __init__(self, parsers: list[DocumentParser]):
        self._parsers = parsers

    def parse(self, path: Path, media_type: str, config: dict) -> ParsedDocument:
        suffix = path.suffix.lower()
        parser = next((candidate for candidate in self._parsers if suffix in candidate.extensions), None)
        if parser is None:
            raise UnsupportedDocument(f"Unsupported file extension: {suffix}")
        return parser.parse(path, config)

    def capabilities(self) -> list[dict]:
        return [{"parser_id": p.parser_id, "extensions": sorted(p.extensions)} for p in self._parsers]


class MarkdownParser:
    parser_id = "markdown"
    extensions = frozenset({".md", ".markdown"})

    def parse(self, path: Path, config: dict) -> ParsedDocument:
        return ParsedDocument(markdown=path.read_text(encoding="utf-8"), parser_id=self.parser_id)


class TextParser:
    parser_id = "text"
    extensions = frozenset({".txt"})

    def parse(self, path: Path, config: dict) -> ParsedDocument:
        return ParsedDocument(markdown=path.read_text(encoding="utf-8"), parser_id=self.parser_id)


def build_default_registry() -> ParserRegistry:
    return ParserRegistry([MarkdownParser(), TextParser()])
