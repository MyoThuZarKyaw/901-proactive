from fastapi import Depends, Request

from .config import Settings, get_settings
from .services import PredictionService, PrometheusQueryService, RedisPublisherService


def get_redis_publisher(request: Request) -> RedisPublisherService:
    # Uses the single Redis client created once during app startup
    return RedisPublisherService(redis_client=request.app.state.redis)


def get_prometheus_query_service(
    settings: Settings = Depends(get_settings),
) -> PrometheusQueryService:
    return PrometheusQueryService(
        base_url=settings.PROMETHEUS_BASE_URL, timeout_seconds=15
    )


def get_prediction_service(request: Request) -> PredictionService:
    return PredictionService(
        predition_model_bundle=request.app.state.predition_model_bundle
    )
