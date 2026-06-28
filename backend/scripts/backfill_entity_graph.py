import argparse

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.config import settings
from backend.app.models import KnowledgeChunk
from backend.app.services.entity_extraction import extract_and_settle_entities
from backend.app.services.graph_client import GraphClient
from backend.app.services.graph_projection import project_ckp_graph, project_entity_graph


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill source-layer entity extraction and project graph data.",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    engine = create_engine(settings.DATABASE_URL)
    Session = sessionmaker(bind=engine)
    db = Session()

    try:
        query = db.query(KnowledgeChunk).order_by(
            KnowledgeChunk.created_at.asc(),
            KnowledgeChunk.id.asc(),
        )
        if args.limit is not None:
            query = query.limit(args.limit)
        chunks = query.all()

        for chunk in chunks:
            extract_and_settle_entities(
                db,
                source_kind="document_chunk",
                source_id=chunk.id,
                item_id=chunk.item_id,
                chunk_id=chunk.id,
                text=chunk.chunk_text or "",
            )

        if args.dry_run:
            db.rollback()
            print(f"dry-run extracted entities from {len(chunks)} chunks")
            return 0

        db.commit()

        graph = GraphClient()
        try:
            ckp_result = project_ckp_graph(db, graph)
            entity_result = project_entity_graph(db, graph)
        finally:
            graph.close()

        print(
            "backfilled entity graph "
            f"chunks={len(chunks)} "
            f"ckp_count={ckp_result.ckp_count} "
            f"pku_count={ckp_result.pku_count} "
            f"entity_count={entity_result.entity_count} "
            f"ckp_source_count={ckp_result.source_count} "
            f"entity_source_count={entity_result.source_count} "
            f"ckp_relation_count={ckp_result.relation_count} "
            f"entity_relation_count={entity_result.relation_count} "
            f"total_relation_count={ckp_result.relation_count + entity_result.relation_count}"
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
