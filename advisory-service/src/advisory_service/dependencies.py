from advisory_service.config import Settings
from advisory_service.container import container
from advisory_service.services import (
    PredictionService,
    PrometheusQueryService,
    RedisPublisherService,
)


def get_redis_publisher() -> RedisPublisherService:
    return container.redis_publisher_service


def get_prometheus_query_service() -> PrometheusQueryService:
    return container.prometheus_query_service


def get_prediction_service() -> PredictionService:
    return container.prediction_service


def get_settings() -> Settings:
    return container.settings
