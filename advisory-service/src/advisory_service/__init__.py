from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI

from .config import settings
from .routers import router as advisory_router


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

app.include_router(advisory_router, prefix="/api/v1")
# This creates:
#   GET  /api/v1/advisory/
#   GET  /api/v1/advisory/ping
#   POST /api/v1/advisory/advise


def main() -> None:
    print("Hello from advisory-service!")
