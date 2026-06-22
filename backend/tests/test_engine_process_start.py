import sys
from pathlib import Path
from urllib.error import URLError


def test_start_engine_uses_engine_run_file(monkeypatch):
    from backend.app import main

    calls = []
    health_urls = []
    pump_calls = []

    class FakeProcess:
        pid = 12345

        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    def fake_popen(args, cwd=None, env=None, **kwargs):
        calls.append({"args": args, "cwd": cwd, "env": env, "kwargs": kwargs})
        return FakeProcess()

    def fake_wait_for_engine_health(process):
        health_urls.append(process.pid)

    def fake_start_engine_output_pump(process, log_file):
        pump_calls.append((process.pid, log_file))

    monkeypatch.setattr(main.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(main, "_wait_for_engine_health", fake_wait_for_engine_health)
    monkeypatch.setattr(main, "_start_engine_output_pump", fake_start_engine_output_pump)
    monkeypatch.setattr(main, "_engine_proc", None)

    main._start_engine()

    root = Path(__file__).resolve().parent.parent.parent
    engine_run = root / "engine" / "run.py"
    assert calls == [
        {
            "args": [sys.executable, "-u", str(engine_run)],
            "cwd": str(root),
            "env": {**calls[0]["env"], "PYTHONPATH": str(root)},
            "kwargs": {
                "stdout": main.subprocess.PIPE,
                "stderr": main.subprocess.STDOUT,
                "text": True,
                "bufsize": 1,
                "encoding": "utf-8",
                "errors": "replace",
            },
        }
    ]
    assert pump_calls and pump_calls[0][0] == 12345
    assert pump_calls[0][1].writable()
    assert health_urls == [12345]
    main._stop_engine()


def test_wait_for_engine_health_default_allows_slow_startup():
    from backend.app import main

    defaults = main._wait_for_engine_health.__defaults__

    assert defaults[0] >= 60


def test_engine_output_pump_prints_and_writes_log(capsys, tmp_path):
    from backend.app import main

    class FakeStdout:
        def __iter__(self):
            return iter(["booting\n", "failed detail\n"])

    class FakeProcess:
        stdout = FakeStdout()

    log_path = tmp_path / "engine.log"
    with log_path.open("w", encoding="utf-8") as log_file:
        main._pump_engine_output(FakeProcess(), log_file)

    output = capsys.readouterr().out
    assert "[engine] booting" in output
    assert "[engine] failed detail" in output
    assert log_path.read_text(encoding="utf-8") == "booting\nfailed detail\n"


def test_engine_output_pump_survives_console_encoding_errors(monkeypatch, tmp_path):
    from backend.app import main

    printed = []

    class FakeStdout:
        def __iter__(self):
            return iter(["bad char \ufffd\n"])

    class FakeProcess:
        stdout = FakeStdout()

    def fake_print(*args, **kwargs):
        text = str(args[0])
        if "\ufffd" in text:
            raise UnicodeEncodeError("gbk", text, 0, 1, "nope")
        printed.append(text)

    monkeypatch.setattr(main, "print", fake_print, raising=False)

    log_path = tmp_path / "engine.log"
    with log_path.open("w", encoding="utf-8") as log_file:
        main._pump_engine_output(FakeProcess(), log_file)

    assert printed == ["[engine] bad char \\ufffd"]
    assert log_path.read_text(encoding="utf-8") == "bad char \ufffd\n"


def test_wait_for_engine_health_reports_process_logs(monkeypatch):
    from backend.app import main

    sleeps = []

    class FakeStdout:
        def read(self):
            return "engine boot failed\nmilvus unavailable\n"

    class FakeProcess:
        pid = 23456
        stdout = FakeStdout()

        def poll(self):
            return 1

    def fake_urlopen(url, timeout=None):
        raise URLError("connection refused")

    monkeypatch.setattr(main.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(main.time, "sleep", lambda seconds: sleeps.append(seconds))

    try:
        main._wait_for_engine_health(FakeProcess(), timeout_seconds=1, interval_seconds=0.1)
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected RuntimeError")

    assert "Engine failed to start" in message
    assert "engine boot failed" in message
    assert "milvus unavailable" in message
