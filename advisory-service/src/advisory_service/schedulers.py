import logging
import os

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

# # Define a ContextVar to safely store the ID per prediction
# correlation_id_ctx: ContextVar[str] = ContextVar("correlation_id", default="")


# # Create the Logging Filter
# class CorrelationIdFilter(logging.Filter):
#     def filter(self, record):
#         # Fetch the current ID from the context window
#         record.correlation_id = correlation_id_ctx.get()
#         return True


# # Configure the Logging System
# handler = logging.StreamHandler()
# handler.addFilter(CorrelationIdFilter())

# # Include '%(correlation_id)s' in format string
# formatter = logging.Formatter(
#     "[%(asctime)s] [%(levelname)s] [ID: %(correlation_id)s] %(message)s"
# )
# handler.setFormatter(formatter)

# schedulers_log = logging.getLogger("schedulers_logger")
# schedulers_log.addHandler(handler)
# schedulers_log.setLevel(logging.INFO)

schedulers_log = logging.getLogger(__name__)


@with_correlation_id()
async def predict_service_metrics():
    # correlation_id_ctx.set(uuid.uuid4().hex)
    schedulers_log.info("Predicting the status of services, started.")
    services_to_process = container.settings.PROMETHEUS_QUERY_SERVICE_NAMES
    for service_name in services_to_process:
        await predict_for_service(service_name=service_name)
    schedulers_log.info("Predicting the status of services, done.")


@with_correlation_subid(suffix_arg="service_name")
async def predict_for_service(service_name):
    schedulers_log.info(f"Predicting for the service name, {service_name}.")
    event = await run_in_threadpool(do_prediction, service_name=service_name)
    if event is not None:
        schedulers_log.info(
            f"Service, {service_name}, is unhealthy and in {event.status} state."
        )
        schedulers_log.info("Sending alert - %s", event.model_dump_json())
        try:
            await container.redis_publisher_service.publish(
                channel=container.settings.REDIS_ADVISORY_ALERT_CHANNEL,
                payload=event,
            )
        except Exception:
            schedulers_log.exception(
                "Redis publisher encountered an unhandled exception."
            )
            raise RedisPubishException(
                message="Advisory event distribution failed. Service unavailable."
            )
    else:
        schedulers_log.info(f"Service, {service_name}, is healthy")
    schedulers_log.info(f"Predicting for the service, {service_name}, completed.")


def do_prediction(service_name) -> AdvisoryEvent:
    # Get data from prometheus
    start_ts, end_ts = container.prometheus_query_service.get_prometheus_time_range(
        minutes=15
    )
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
    schedulers_log.info("Prediction payload - %s", prediction_payload.model_dump_json())
    predicted_result = container.prediction_service.predict_health(prediction_payload)

    event = None
    if predicted_result.state in {
        PredictionOutputState.DEGRADED,
        PredictionOutputState.FAILED,
        PredictionOutputState.HEALTHY,
    }:
        event = AdvisoryEvent(
            target_service=service_name, status=predicted_result.state
        )
    return event
