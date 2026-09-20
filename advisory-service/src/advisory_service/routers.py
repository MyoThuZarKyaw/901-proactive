import logging
from typing import Annotated

from fastapi import APIRouter, Depends, status

from .dependencies import get_redis_publisher
from .exceptions import RedisPubishException
from .models import AdviseResponse, CircuitBreakerPayload
from .services import RedisPublisherService

logger = logging.getLogger(__name__)

# Export a single router for this domain/feature
router = APIRouter(prefix="/advisory", tags=["Advisory"])


@router.get(
    "/",
    summary="Root advisory welcome",
    response_model=str,
)
async def welcome() -> str:
    return "Welcome to advisory service!"


@router.get(
    "/ping",
    summary="Health check",
    response_model=str,
)
async def ping() -> str:
    return "PONG"


@router.post(
    "/advise",
    response_model=AdviseResponse,
    status_code=status.HTTP_200_OK,
    summary="Process metrics and publish advisory event",
)
async def advise(
    publisher: Annotated[RedisPublisherService, Depends(get_redis_publisher)],
) -> AdviseResponse:

    # Now dynamic instead of hardcoded
    alert = CircuitBreakerPayload(
        target_service="payment-service",
        status="DEGRADED",
        reason="Average latency > 3500ms detected over last 10s",
    )

    try:
        """Gather Prometheus metrics, evaluate via the brain engine, and publish actions."""
        await publisher.publish(channel="circuit-breaker-channel", payload=alert)
    except Exception:
        logger.exception("Redis publisher encountered an unhandled exception.")
        raise RedisPubishException(
            message="Advisory event distribution failed. Service unavailble."
        )

    return AdviseResponse(
        metric="The data retrieved from Prometheus and passed to the brain",
        response="The response returned from the brain",
        event="The event triggered based on the response",
    )
