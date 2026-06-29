from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .executors import (
    GlobalFallbackExecutor,
    PkuGraphExpansionExecutor,
    PkuRequeryExecutor,
    ScopeFinderExecutor,
    ScopedChunkSearchExecutor,
    SourceBacktrackExecutor,
)
from .schemas import EvidenceRecord, ScopeResult, SearchDirective


class SearcherAgent:
    def __init__(self, session_factory: Callable[[], Any]) -> None:
        self.scope_finder = ScopeFinderExecutor(session_factory)
        self.source_backtrack = SourceBacktrackExecutor(session_factory)
        self.pku_graph_expansion = PkuGraphExpansionExecutor(session_factory)
        self.pku_requery = PkuRequeryExecutor(session_factory)
        self.scoped_chunk_search = ScopedChunkSearchExecutor(session_factory)
        self.global_fallback = GlobalFallbackExecutor(session_factory)

    def find_scope(self, query: str, limit: int) -> ScopeResult:
        return self.scope_finder.run(query, limit=limit)

    def initial_evidence(self, scope: ScopeResult, limit: int) -> list[EvidenceRecord]:
        return self.source_backtrack.run(scope, limit=limit)

    def follow_directive(self, directive: SearchDirective, scope: ScopeResult, limit: int) -> list[EvidenceRecord]:
        if directive.strategy == "pku_requery":
            return self.pku_requery.run(directive.query or scope.query, scope.seed_ckp_ids, limit=limit)
        if directive.strategy == "pku_graph_expansion":
            return self.pku_graph_expansion.run(scope.seed_pku_ids, limit=limit)
        if directive.strategy == "source_backtrack":
            return self.source_backtrack.run(scope, limit=limit)
        if directive.strategy == "ckp_rescope":
            refreshed = self.scope_finder.run(directive.query or scope.query, limit=limit)
            scope.seed_ckp_ids[:] = list(dict.fromkeys([*scope.seed_ckp_ids, *refreshed.seed_ckp_ids]))
            scope.seed_pku_ids[:] = list(dict.fromkeys([*scope.seed_pku_ids, *refreshed.seed_pku_ids]))
            scope.candidate_item_ids[:] = list(dict.fromkeys([*scope.candidate_item_ids, *refreshed.candidate_item_ids]))
            return self.source_backtrack.run(scope, limit=limit)
        if directive.strategy == "scoped_chunk_search":
            return self.scoped_chunk_search.run(directive.query or scope.query, scope, limit=limit)
        if directive.strategy == "global_fallback":
            return self.global_fallback.run(directive.query or scope.query, limit=limit)
        return []
