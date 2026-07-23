def test_embedding_profile_collection_name_is_stable():
    from engine.app.indexing.profiles import EmbeddingProfile

    profile = EmbeddingProfile("jina", "jina-embeddings-v3", 1024, "COSINE", True)

    assert profile.profile_id == "13d8329dc276a9a4"
    assert profile.document_collection == "prism_kb_13d8329dc276a9a4"
    assert profile.graph_collection == "prism_graph_13d8329dc276a9a4"


def test_embedding_profile_identity_changes_with_vector_contract():
    from engine.app.indexing.profiles import EmbeddingProfile

    base = EmbeddingProfile("jina", "jina-embeddings-v3", 1024, "COSINE", True)
    changed = EmbeddingProfile("jina", "jina-embeddings-v3", 768, "COSINE", True)

    assert base.profile_id != changed.profile_id
