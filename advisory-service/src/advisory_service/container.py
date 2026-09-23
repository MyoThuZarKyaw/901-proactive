from advisory_service.config import Settings
from advisory_service.services import (
    PredictionService,
    PrometheusQueryService,
    RedisPublisherService,
)


class ServiceContainer:
    settings: Settings
    prometheus_query_service: PrometheusQueryService
    prediction_service: PredictionService
    redis_publisher_service: RedisPublisherService

    def initialize(
        self,
        settings: Settings,
        redis_client,
        prediction_model_bundle,
    ):
        """Called once during lifespan startup to wire dependencies."""
        self.settings = settings

        self.prometheus_query_service = PrometheusQueryService(
            base_url=settings.PROMETHEUS_BASE_URL,
            timeout_seconds=15,
        )

        self.prediction_service = PredictionService(
            predition_model_bundle=prediction_model_bundle
        )

        self.redis_publisher_service = RedisPublisherService(redis_client=redis_client)


# Global singleton instance
container = ServiceContainer()
