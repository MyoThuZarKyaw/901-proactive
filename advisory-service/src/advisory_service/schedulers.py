import logging
import os
import uuid

import numpy as np
from fastapi.concurrency import run_in_threadpool

from advisory_service.container import container
from advisory_service.exceptions import RedisPubishException
from advisory_service.logger_config import with_correlation_id, with_correlation_subid
from advisory_service.models import (
    AdvisoryEvent,
    PredictionInput,
    PredictionOutputState,
)

logger = logging.getLogger(__name__)


@with_correlation_id()
async def predict_service_metrics():
    # correlation_id_ctx.set(uuid.uuid4().hex)
    logger.info("Predicting the status of services, started.")
    services_to_process = container.settings.PROMETHEUS_QUERY_SERVICE_NAMES
    start_ts, end_ts = container.prometheus_query_service.get_prometheus_time_range(
        minutes=15
    )
    for service_name in services_to_process:
        await predict_for_service(
            service_name=service_name, start_ts=start_ts, end_ts=end_ts
        )
    logger.info("Predicting the status of services, done.")


@with_correlation_subid(suffix_arg="service_name")
async def predict_for_service(service_name, start_ts, end_ts):
    logger.info(
        f"===== #[Predicting for the service name, {service_name}(${start_ts}, ${end_ts})."
    )
    event = await run_in_threadpool(
        do_prediction, service_name=service_name, start_ts=start_ts, end_ts=end_ts
    )
    if event is not None:
        logger.info(
            f"Service, {service_name}, is unhealthy and in {event.status} state."
        )
        logger.info("Sending alert - %s", event.model_dump_json())
        if container.settings.REDIS_ADVISORY_ALERT_ON:
            try:
                await container.redis_publisher_service.publish(
                    channel=container.settings.REDIS_ADVISORY_ALERT_CHANNEL,
                    payload=event,
                )
            except Exception:
                logger.exception("Redis publisher encountered an unhandled exception.")
                raise RedisPubishException(
                    message="Advisory event distribution failed. Service unavailable."
                )
        else:
            logger.info("Redis Alert has been off. Alert is not sent.")
    else:
        logger.info(f"Service, {service_name}, is healthy")
    logger.info(f"Predicting for the service, {service_name}, completed.")


def do_prediction(service_name, start_ts, end_ts) -> AdvisoryEvent:
    # Get data from prometheus
    df = container.prometheus_query_service.fetch_all_metrics(
        service_name=service_name, start_ts=start_ts, end_ts=end_ts
    )

    # Check if we have data
    if df.empty:
        return

    if container.settings.EXPORT_TIMESERIES_DATA:
        # Print as csv
        output_file = f"raw_data/fetch_prometheus_{service_name}_data.csv"
        # Ensure the parent directory exists before saving (e.g., 'raw_data/')
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        df.to_csv(output_file, index=False)

    # Get the latest row as Pandas series (flat dictionary like {'target_cpu': 0.1061, 'target_mem': 0.883, 'target_latency': 7.81})
    last_metric_row = df.iloc[-1].replace({np.nan: None}).to_dict()

    # Prepare feature payload and predict
    prediction_payload = PredictionInput(
        service_name=service_name,
        features=last_metric_row,
        timestamp=last_metric_row["timestamp"],
    )
    logger.info("Prediction payload - %s", prediction_payload.model_dump_json())
    predicted_result = container.prediction_service.predict_health(prediction_payload)
    logger.info("***** #[Prediction result - %s", predicted_result)

    event = None
    if predicted_result.state in {
        PredictionOutputState.DEGRADED,
        PredictionOutputState.FAILED,
        # PredictionOutputState.HEALTHY,
    }:
        event = AdvisoryEvent(
            event_id=uuid.uuid4().hex,
            target_service=service_name,
            status=predicted_result.state,
        )
    return event
