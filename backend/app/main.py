# prism/backend/app/main.py
import os
import sys
import subprocess
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import Base, engine, get_db
from .utils.auto_migrate import auto_migrate
from .api import register_routers
# 导入所有模型，确保注册到 Base.metadata
from .models import *  # noqa

_engine_proc = None


def _start_engine():
    """启动 Engine 子进程。"""
    global _engine_proc
    parent_dir = str(Path(__file__).resolve().parent.parent.parent)
    env = os.environ.copy()
    env["PYTHONPATH"] = parent_dir
    _engine_proc = subprocess.Popen(
        [sys.executable, "-m", "engine.run"],
        cwd=parent_dir,
        env=env,
    )
    print(f"[backend] Engine 已启动, PID={_engine_proc.pid}")


def _stop_engine():
    global _engine_proc
    if _engine_proc:
        _engine_proc.terminate()
        try:
            _engine_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _engine_proc.kill()
        _engine_proc = None
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
