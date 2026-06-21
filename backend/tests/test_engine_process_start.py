import sys
from pathlib import Path


def test_start_engine_uses_engine_run_file(monkeypatch):
    from backend.app import main

    calls = []

    class FakeProcess:
        pid = 12345

        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    def fake_popen(args, cwd=None, env=None):
        calls.append({"args": args, "cwd": cwd, "env": env})
        return FakeProcess()

    monkeypatch.setattr(main.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(main, "_engine_proc", None)

    main._start_engine()

    root = Path(__file__).resolve().parent.parent.parent
    engine_run = root / "engine" / "run.py"
    assert calls == [
        {
            "args": [sys.executable, str(engine_run)],
            "cwd": str(root),
            "env": {**calls[0]["env"], "PYTHONPATH": str(root)},
        }
    ]
    main._stop_engine()
