# prism/backend/app/main.py
import os
import sys
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import Base, engine, get_db
from .utils.auto_migrate import auto_migrate
from .api import register_routers
# 导入所有模型，确保注册到 Base.metadata
from .models import *  # noqa

_engine_proc = None
_engine_log_file = None
_engine_log_thread = None


def _read_engine_output(process) -> str:
    log_path = getattr(process, "_prism_log_path", None)
    if log_path:
        try:
            return Path(log_path).read_text(encoding="utf-8", errors="replace").strip()
        except Exception:
            return ""
    if not getattr(process, "stdout", None):
        return ""
    try:
        output = process.stdout.read()
    except Exception:
        return ""
    return output.strip() if output else ""


def _pump_engine_output(process, log_file) -> None:
    if not getattr(process, "stdout", None):
        return
    for line in process.stdout:
        log_file.write(line)
        log_file.flush()
        text = f"[engine] {line.rstrip()}"
        try:
            print(text, flush=True)
        except UnicodeEncodeError:
            safe_text = text.encode("ascii", errors="backslashreplace").decode("ascii")
            print(safe_text, flush=True)


def _start_engine_output_pump(process, log_file) -> threading.Thread:
    thread = threading.Thread(
        target=_pump_engine_output,
        args=(process, log_file),
        daemon=True,
    )
    thread.start()
    return thread


def _wait_for_engine_health(process, timeout_seconds: float = 90, interval_seconds: float = 0.5):
    deadline = time.monotonic() + timeout_seconds
    health_url = f"http://127.0.0.1:{settings.ENGINE_PORT}/health"
    last_error = ""

    while time.monotonic() < deadline:
        if process.poll() is not None:
            logs = _read_engine_output(process)
            detail = f"\nEngine logs:\n{logs}" if logs else ""
            raise RuntimeError(f"Engine failed to start, PID={process.pid}.{detail}")

        try:
            with urllib.request.urlopen(health_url, timeout=1) as resp:
                if 200 <= resp.status < 300:
                    return
        except (OSError, urllib.error.URLError) as exc:
            last_error = str(exc)

        time.sleep(interval_seconds)

    logs = _read_engine_output(process)
    detail = f"\nLast health error: {last_error}" if last_error else ""
    if logs:
        detail += f"\nEngine logs:\n{logs}"
    raise RuntimeError(f"Engine health check timed out, PID={process.pid}, url={health_url}.{detail}")


def _start_engine():
    """启动 Engine 子进程。"""
    global _engine_proc, _engine_log_file, _engine_log_thread
    root = Path(__file__).resolve().parent.parent.parent
    parent_dir = str(root)
    engine_run = str(root / "engine" / "run.py")
    log_path = root / "output" / "logs" / "engine.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    _engine_log_file = log_path.open("w", encoding="utf-8", errors="replace")
    env = os.environ.copy()
    env["PYTHONPATH"] = parent_dir
    _engine_proc = subprocess.Popen(
        [sys.executable, "-u", engine_run],
        cwd=parent_dir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding="utf-8",
        errors="replace",
    )
    _engine_proc._prism_log_path = str(log_path)
    _engine_log_thread = _start_engine_output_pump(_engine_proc, _engine_log_file)
    print(f"[backend] Engine starting, PID={_engine_proc.pid}")
    try:
        _wait_for_engine_health(_engine_proc)
    except Exception:
        _stop_engine()
        raise
    print(f"[backend] Engine health check passed, PID={_engine_proc.pid}")


def _stop_engine():
    global _engine_proc, _engine_log_file, _engine_log_thread
    if _engine_proc:
        _engine_proc.terminate()
        try:
            _engine_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _engine_proc.kill()
        _engine_proc = None
        if _engine_log_file:
            _engine_log_file.close()
            _engine_log_file = None
        _engine_log_thread = None
        print("[backend] Engine 已停止")


def create_app() -> FastAPI:
    app = FastAPI(title="Prism Backend")
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
    )

    register_routers(app)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.on_event("startup")
    def startup():
        try:
            auto_migrate(Base, engine)
            print("[backend] 数据库迁移完成")
        except Exception as e:
            print(f"[backend] 数据库迁移失败（首次启动可忽略）: {e}")
        if os.getenv("SKIP_ENGINE") != "1":
            _start_engine()

    @app.on_event("shutdown")
    def shutdown():
        _stop_engine()

    return app


app = create_app()
