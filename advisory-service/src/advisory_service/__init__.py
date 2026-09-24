import logging
from contextlib import asynccontextmanager

import joblib
import redis.asyncio as aioredis
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from advisory_service.config import settings
from advisory_service.container import container
from advisory_service.exceptions import ApplicationException
from advisory_service.logger_config import CorrelationIdMiddleware, setup_global_logging
from advisory_service.routers import router as advisory_router
from advisory_service.schedulers import predict_service_metrics


@asynccontextmanager
async def lifespan(app: FastAPI):

    # ==========================================
    # --- STARTUP LOGIC ---
    # ==========================================

    # - Configure Logging
    setup_global_logging()

    logger = logging.getLogger(__name__)

    logger.info("Starting up application...")

    logger.info("Initializing dependencies...")
    # Create ONE pool for the entire application lifetime
    app.state.redis = aioredis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        decode_responses=settings.REDIS_DECODE_RESPONSE,
    )

    # Preload modle file at the application startup
    try:
        app.state.predition_model_bundle = joblib.load(settings.MODEL_BUNDLE_FILE)
    except Exception as e:
        logger.exception(f"Failed to load model bundle: {e}")

    # app.state.prometheus_query_service = PrometheusQueryService(
    #     base_url=settings.PROMETHEUS_BASE_URL, timeout_seconds=15
    # )
    # # (TODO!): Health-check dependencies at boot time!
    # # If Prometheus is completely unreachable, fail early during boot:
    # try:
    #     # e.g., quick ping to prometheus /-/healthy or /api/v1/status/buildinfo
    #     logger.info("Validating Prometheus connectivity...")
    # except Exception as e:
    #     logger.error(f"Failed to connect to Prometheus on startup: {e}")
    #     # Raising an exception here will prevent the container from booting up unhealthy
    #     raise e

    container.initialize(
        settings=settings,
        redis_client=app.state.redis,
        prediction_model_bundle=app.state.predition_model_bundle,
    )
    logger.info("All dependencies initialized successfully.")

    logger.info("Initializing schedulers...")
    # Initialize the async scheduler
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        predict_service_metrics,
        "interval",
        seconds=settings.PREDICTION_SCHEDULE_INTERVAL_SECONDS,
    )
    scheduler.start()
    logger.info("All schedulers initialized successfully.")

    yield
    # SHUTDOWN: Gracefully close connections
    scheduler.shutdown()
    await app.state.redis.close()


# -------------------------------------------------------------------
# FastAPI Setup
# -------------------------------------------------------------------
app = FastAPI(lifespan=lifespan)
app.add_middleware(CorrelationIdMiddleware)

logger = logging.getLogger(__name__)


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
