import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .config import settings
from .exceptions import ApplicationException
from .routers import router as advisory_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # STARTUP: Create ONE pool for the entire application lifetime
    app.state.redis = aioredis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        decode_responses=settings.redis_decode_response,
    )
    yield
    # SHUTDOWN: Gracefully close connections
    await app.state.redis.close()


app = FastAPI(lifespan=lifespan)


# Registering Exception Handlers
@app.exception_handler(ApplicationException)
async def handle_application_exception(request: Request, ex: ApplicationException):
    # Log the exact error for server-side debugging
    logger.error(f"Advisory error occurred on {request.url.path}: {ex.message}")

    # Return a clean, structured response to the client
    return JSONResponse(
        status_code=ex.status_code,
        content={
            "success": False,
            # "error": ex.__class__.__name__,
            "reason": ex.message,
        },
    )


# Registering Other Routers
app.include_router(advisory_router, prefix="/api/v1")
# This creates:
#   GET  /api/v1/advisory/
#   GET  /api/v1/advisory/ping
#   POST /api/v1/advisory/advise


def main() -> None:
    print("Hello from advisory-service!")
