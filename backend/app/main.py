import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import database
from app.config import settings
from app.observability.error_handlers import (
    AppError, app_error_handler, http_exception_handler, validation_error_handler,
)
from app.observability.middleware import ObservabilityMiddleware
from app.routes import admin, auth, events, orders, performance, products
from app.services import performance_service

logging.basicConfig(level=logging.INFO, format="%(message)s")  # events are already JSON lines


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    await database.wait_for_primary()
    await database.ensure_indexes(database.get_db())
    monitor = None
    if settings.monitor_enabled:
        monitor = asyncio.create_task(performance_service.monitor_loop())
    yield
    if monitor:
        monitor.cancel()
    await database.close_db()


app = FastAPI(
    title="MiniShop — Application-Level Rectification POC",
    version="1.0.0",
    description="E-commerce POC with application-level observability and APP-R-056 latency monitoring.",
    lifespan=lifespan,
)

app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)

# Observability is innermost of our middlewares; CORS is outermost (handles preflight first).
app.add_middleware(ObservabilityMiddleware)
app.add_middleware(
    CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False,
    allow_methods=["*"], allow_headers=["*"], expose_headers=["X-Request-ID", "X-Trace-Id", "Idempotent-Replay"],
)

for r in (auth.router, products.router, orders.router, admin.router, events.router, performance.router):
    app.include_router(r)

if settings.dev_enabled:  # never mounted in production
    from app.routes import dev
    app.include_router(dev.router)


@app.get("/health", tags=["health"])
async def health():
    try:
        await database.get_client().admin.command("ping")
    except Exception:  # noqa: BLE001
        return JSONResponse(status_code=503, content={"status": "unhealthy", "database": "down"})
    return {"status": "ok", "database": "up", "environment": settings.environment}
