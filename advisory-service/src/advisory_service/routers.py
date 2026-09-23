import logging
from typing import Annotated

import numpy as np
from fastapi import APIRouter, Depends, Path, status

from .config import Settings, get_settings
from .dependencies import (
    get_prediction_service,
    get_prometheus_query_service,
    get_redis_publisher,
)
from .exceptions import RedisPubishException
from .models import (
    AdviseResponse,
    AdvisoryEvent,
    PredictionInput,
    PredictionOutputState,
)
from .services import PredictionService, PrometheusQueryService, RedisPublisherService

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
    alert = AdvisoryEvent(
        target_service="inventory-service",
        status=PredictionOutputState.DEGRADED,
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


@router.post(
    "/predict/{target_service}",
    response_model=list[AdviseResponse],
    status_code=status.HTTP_200_OK,
    summary="Process metrics and publish advisory event for all or a specific service",
)
async def predict_metrics(
    target_service: Annotated[
        str,
        Path(
            description="Service name to evaluate, or 'all' to evaluate all configured services",
            examples=["all", "inventory_service", "payment-service"],
        ),
    ],
    query_service: Annotated[
        PrometheusQueryService, Depends(get_prometheus_query_service)
    ],
    prediction_service: Annotated[PredictionService, Depends(get_prediction_service)],
    publisher: Annotated[RedisPublisherService, Depends(get_redis_publisher)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> list[AdviseResponse]:

    # Determine which services to process
    target = target_service.strip()
    configured_services = settings.PROMETHEUS_QUERY_SERVICE_NAMES

    if target.lower() == "all":
        services_to_process = list(configured_services)
    elif target in configured_services:
        services_to_process = [target]
    elif target.replace("-", "_") in configured_services:
        # Handles kebab-case incoming from Java Gateway (e.g., payment-service -> payment_service)
        services_to_process = [target.replace("-", "_")]
    else:
        # Service name is not recognized in settings -> do nothing
        logger.warning(
            f"Service '{target}' not found in configured services: {configured_services}. Doing nothing."
        )
        return []

    result: list[AdviseResponse] = []

    # Process the selected services
    for service_name in services_to_process:
        # Get data from prometheus
        start_ts, end_ts = query_service.get_prometheus_time_range(minutes=15)
        df = query_service.fetch_all_metrics(
            service_name=service_name, start_ts=start_ts, end_ts=end_ts
        )

        # Check if we have data
        if df.empty:
            result.append(
                AdviseResponse(
                    metric=None,
                    prediction=None,
                    event=None,
                )
            )
            continue

        # # Print as csv
        # output_file = f"raw_data/fetch_prometheus_{service_name}_data.csv"
        # # Ensure the parent directory exists before saving (e.g., 'raw_data/')
        # os.makedirs(os.path.dirname(output_file), exist_ok=True)
        # df.to_csv(output_file, index=False)

        # Get the latest row as Pandas series (flat dictionary like {'target_cpu': 0.1061, 'target_mem': 0.883, 'target_latency': 7.81})
        last_metric_row = df.iloc[-1].replace({np.nan: None}).to_dict()

        # Prepare feature payload and predict
        prediction_payload = PredictionInput(
            service_name=service_name,
            features=last_metric_row,
            timestamp=last_metric_row["timestamp"],
        )
        predicted_result = prediction_service.predict_health(prediction_payload)

        event = None
        if predicted_result.state in {
            PredictionOutputState.DEGRADED,
            PredictionOutputState.FAILED,
            PredictionOutputState.HEALTHY,
        }:
            event = AdvisoryEvent(
                target_service=service_name, status=predicted_result.state
            )
            logger.info(
                f"{predicted_result.state} state has been detected. Sending alert..."
            )
            try:
                await publisher.publish(
                    channel=settings.REDIS_ADVISORY_ALERT_CHANNEL, payload=event
                )
            except Exception:
                logger.exception("Redis publisher encountered an unhandled exception.")
                raise RedisPubishException(
                    message="Advisory event distribution failed. Service unavailble."
                )

        result.append(
            AdviseResponse(
                metric=prediction_payload.model_dump(),
                prediction=predicted_result.model_dump(),
                event=event,
            )  # event="ADVISORY_EVENT_PUBLISHED",
        )
    return result
