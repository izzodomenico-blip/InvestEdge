from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.app.api.routes import router
from backend.app.config import ROOT_DIR, get_settings
from backend.app.database import init_db
from backend.app.services.backup_service import auto_backup_on_startup


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    # Backup automatico a ogni avvio (salta durante i test per non sporcare i temp).
    if "PYTEST_CURRENT_TEST" not in os.environ:
        auto_backup_on_startup()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version=settings.api_version,
        description="Local investment analysis API for InvestEdge.",
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=settings.cors_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.exception_handler(Exception)
    async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "type": exc.__class__.__name__},
        )

    application.include_router(router)

    if os.getenv("INVESTEDGE_SERVE_FRONTEND", "0") == "1":
        _mount_frontend(application)

    return application


def _mount_frontend(application: FastAPI) -> None:
    dist_dir = Path(os.getenv("INVESTEDGE_FRONTEND_DIST", ROOT_DIR / "frontend" / "dist"))
    if not dist_dir.is_absolute():
        dist_dir = ROOT_DIR / dist_dir
    index_file = dist_dir / "index.html"
    if not index_file.exists():
        return

    static_dir = dist_dir / "static"
    if static_dir.is_dir():
        application.mount("/static", StaticFiles(directory=static_dir), name="frontend-static")

    @application.get("/", include_in_schema=False)
    async def _spa_root() -> FileResponse:
        return FileResponse(index_file)

    @application.get("/{full_path:path}", include_in_schema=False)
    async def _spa_fallback(full_path: str) -> FileResponse:
        candidate = (dist_dir / full_path).resolve()
        try:
            candidate.relative_to(dist_dir.resolve())
        except ValueError:
            raise HTTPException(status_code=404) from None
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index_file)


app = create_app()
