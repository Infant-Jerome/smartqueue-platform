from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy import text
from app.core.config import get_settings
from app.core.database import create_tables, engine
from app.core.response import ok
from app.api.v1.router import api_router

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Dev/test convenience only: auto-create tables for local SQLite usage.
    # Production uses Alembic migrations (see render.yaml: `alembic upgrade head`),
    # so never run create_all when DEBUG is False.
    if settings.DEBUG:
        create_tables()
    # N1-Core (Phase 5B) wiring only: subscribe notification fan-out to
    # queue events; never touches queue/appointment business logic.
    try:
        from app.notifications.service import subscribe_notifications

        subscribe_notifications()
    except Exception:
        pass
    yield
    try:
        from app.notifications.service import unsubscribe_notifications

        unsubscribe_notifications()
    except Exception:
        pass


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


@app.exception_handler(StarletteHTTPException)
async def starlette_http_exception_handler(request: Request, exc: StarletteHTTPException):
    # Unmatched routes / direct Starlette errors -> uniform envelope, no tracebacks.
    detail = exc.detail if isinstance(exc.detail, str) else "Not found"
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "message": detail, "data": None},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "message": exc.detail, "data": None},
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"success": False, "message": "Invalid request", "data": None},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"success": False, "message": "Internal server error", "data": None},
    )


@app.get("/api/health")
def health_check():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_status = "up"
    except Exception:
        return JSONResponse(
            status_code=503,
            content={
                "success": False,
                "message": "Service unavailable",
                "data": {"status": "degraded", "database": "down"},
            },
        )
    return ok(
        {
            "status": "ok",
            "service": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "database": db_status,
        },
        message="Service is healthy",
    )
