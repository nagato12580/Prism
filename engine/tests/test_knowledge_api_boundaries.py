def test_engine_exposes_no_synchronous_knowledge_process_bypass():
    from engine.run import create_app

    paths = {route.path for route in create_app().routes}

    assert "/api/v1/knowledge/process" not in paths
