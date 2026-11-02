"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from esphea import __version__
from esphea.api.infrastructure import Infrastructure, build_infrastructure
from esphea.api.routes import experiments, runs
from esphea.services.errors import ConflictError, NotFoundError
from esphea.settings import Settings, get_settings


def create_app(
    infrastructure: Infrastructure | None = None, settings: Settings | None = None
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        infra = infrastructure or build_infrastructure(settings)
        app.state.infrastructure = infra
        yield
        await infra.close()

    app = FastAPI(
        title="ESPHEA API",
        version=__version__,
        summary="Configure, run and inspect evolutionary multi-objective experiments.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(NotFoundError)
    async def not_found(_: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ConflictError)
    async def conflict(_: Request, exc: ConflictError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.get("/api/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    app.include_router(experiments.router, prefix="/api")
    app.include_router(runs.router, prefix="/api")
    return app
