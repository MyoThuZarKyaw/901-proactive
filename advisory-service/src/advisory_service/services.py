import json
import logging
import time
from enum import StrEnum
from typing import Any

import numpy as np
import pandas as pd
import redis.asyncio as aioredis
import requests
from pydantic import BaseModel

from advisory_service.exceptions import ApplicationException
from advisory_service.models import (
    PredictionInput,
    PredictionOutput,
    PredictionOutputState,
    PredictionStateProbabilities,
)

logger = logging.getLogger(__name__)


class RedisPublisherService:

    def __init__(self, redis_client: aioredis.Redis):
        self._r = redis_client

    async def publish(
        self,
        channel: str,
        payload: BaseModel | dict[str, Any],
    ) -> int:
        """Publish a JSON payload to a Redis channel asynchronously."""
        if isinstance(payload, BaseModel):
            message = payload.model_dump_json()
        else:
            message = json.dumps(payload)

        try:
            # Non-blocking async publish
            subscribers: int = await self._r.publish(channel, message)
            logger.info(
                "Alert sent to channel '%s'. Received by %d subscriber(s).",
                channel,
                subscribers,
            )
            return subscribers
        except aioredis.RedisError as e:
            logger.error("Failed to publish message to Redis: %s", str(e))
            raise


class MetricKey(StrEnum):
    # --- Core Target Metrics ---
    TARGET_CPU = "target_cpu"
    TARGET_MEM = "target_mem"
    TARGET_THROUGHPUT = "target_throughput"
    TARGET_LATENCY = "target_latency"
    TARGET_ERROR_RATE = "target_error_rate"
    TARGET_LIVE_THREADS = "target_live_threads"
    TARGET_ACTIVE_REQUESTS = "target_active_requests"

    # --- Delta / Change Metrics ---
    LATENCY_DELTA_30S = "latency_delta_30s"
    LATENCY_DELTA_60S = "latency_delta_60s"
    MEM_DELTA_60S = "mem_delta_60s"
    CPU_DELTA_30S = "cpu_delta_30s"
    THROUGHPUT_DELTA_30S = "throughput_delta_30s"

    # --- Rolling Aggregations (1-minute window) ---
    LATENCY_ROLLING_MEAN_1M = "latency_rolling_mean_1m"
    LATENCY_STD_1M = "latency_std_1m"
    THROUGHPUT_ROLLING_MEAN_1M = "throughput_rolling_mean_1m"
    ACTIVE_REQ_ROLLING_MEAN_1M = "active_req_rolling_mean_1m"

    # --- Derived / Anomaly Indicators ---
    LATENCY_ACCEL_30S = "latency_accel_30s"
    LATENCY_SURGE_RATIO = "latency_surge_ratio"
    THREAD_PRESSURE_RATIO = "thread_pressure_ratio"
    LATENCY_ZSCORE = "latency_zscore"


class PrometheusQueryService:

    def __init__(self, base_url: str, timeout_seconds: int = 15):
        # To ensure clean URL without trailing slashes
        self.base_url = base_url.rstrip("/")
        self.query_range_url = f"{self.base_url}/api/v1/query_range"
        self.timeout = timeout_seconds
        # Connection pooling: keeps TCP sockets alive across multiple queries
        self.session = requests.Session()

    @staticmethod
    def get_prometheus_time_range(minutes: int = 10) -> tuple[int, int]:
        """Returns (start_ts, end_ts) for Prometheus as UNIX epoch seconds."""
        # Usage:
        # START_TS, END_TS = get_prometheus_time_range(minutes=10)
        end_ts = int(time.time())
        start_ts = end_ts - (minutes * 60)
        return start_ts, end_ts

    @staticmethod
    def build_queries(service_name: str, window: str = "1m") -> dict[MetricKey, str]:
        return {
            MetricKey.TARGET_CPU: (
                f'avg(otel_process_cpu_usage{{application="{service_name}"}}) * 100'
            ),
            MetricKey.TARGET_MEM: (
                f'sum(otel_jvm_memory_used_bytes{{area="heap", application="{service_name}"}}) / '
                f'sum(otel_jvm_memory_max_bytes{{area="heap", application="{service_name}"}} > 0)'
                # f'sum(otel_jvm_memory_committed_bytes{{application="{service_name}"}})'
            ),
            MetricKey.TARGET_THROUGHPUT: (
                f'sum(rate(otel_http_server_requests_milliseconds_count{{application="{service_name}"}}[{window}]))'
            ),
            MetricKey.TARGET_LATENCY: (
                f'sum(rate(otel_http_server_requests_milliseconds_sum{{application="{service_name}"}}[{window}])) / '
                f'sum(rate(otel_http_server_requests_milliseconds_count{{application="{service_name}"}}[{window}]))'
            ),
            MetricKey.TARGET_ERROR_RATE: (
                f'sum(rate(otel_http_server_requests_milliseconds_count{{application="{service_name}", status=~"5.."}}[{window}])) / '
                f'sum(rate(otel_http_server_requests_milliseconds_count{{application="{service_name}"}}[{window}]))'
            ),
            MetricKey.TARGET_LIVE_THREADS: (
                f'max(otel_jvm_threads_live{{application="{service_name}"}})'
            ),
            MetricKey.TARGET_ACTIVE_REQUESTS: (
                f'sum(otel_http_server_requests_active_milliseconds_count{{application="{service_name}"}})'
            ),
        }

    def fetch_series(
        self,
        query_name: MetricKey | str,
        query_str: str,
        start_ts: int,
        end_ts: int,
        step: str = "2s",
    ):
        """
        Executes a single Prometheus query and converts the response into a Pandas Series.
        """
        # The URL parameters sent with our GET request to Prometheus
        params = {"query": query_str, "start": start_ts, "end": end_ts, "step": step}
        col_name = str(query_name)
        try:
            # Send HTTP GET request with a 15-second timeout
            res = requests.get(
                self.query_range_url, params=params, timeout=self.timeout
            )
            # Raises an HTTPError if Prometheus returned an error status code (e.g., 400, 500)
            res.raise_for_status()

            # Parse JSON and drill down: response -> 'data' -> 'result'
            # If any key is missing, fallback safely using default values {} or []
            payload: dict[str, Any] = res.json()
            results = payload.get("data", {}).get("result", [])

            # If the result list is empty (no data found for this query),
            # return an empty Pandas Series (a single empty column)
            if not results or "values" not in results[0]:
                return pd.Series(dtype="float64", name=col_name)

            # Prometheus returns time series in data[0]["values"] as a list of:
            # [[1695200000, "12.34"], [1695200002, "12.80"], ...]
            raw_values = results[0]["values"]
            timestamps, metric_values = zip(*raw_values)

            # Build Series directly (3x faster than creating an intermediate DataFrame)
            return pd.Series(
                data=pd.to_numeric(metric_values, errors="coerce"),
                index=pd.Index([int(ts) for ts in timestamps], name="timestamp"),
                name=col_name,
                dtype="float64",
            )

        except requests.RequestException as e:
            logger.error(f"HTTP error querying Prometheus for '{col_name}': {e}")
            return pd.Series(dtype="float64", name=col_name)
        except Exception as e:
            logger.exception(f"Unexpected error parsing metric '{col_name}': {e}")
            return pd.Series(dtype="float64", name=col_name)

    def fetch_all_metrics(
        self,
        service_name: str,
        start_ts: int,
        end_ts: int,
        step_seconds: int = 2,
    ) -> pd.DataFrame:
        """
        Fetches all base metrics and joins them into a single, time-aligned DataFrame.
        """
        queries = self.build_queries(service_name=service_name)
        series_dict = {
            name: self.fetch_series(name, q_str, start_ts, end_ts, step_seconds)
            for name, q_str in queries.items()
        }
        df = pd.DataFrame(series_dict)

        # Fail fast if Prometheus returned zero data for all queries
        if df.empty or df.dropna(how="all").empty:
            logger.warning(
                f"xxxxx #[No metric data returned from Prometheus for service '{service_name}'."
            )
            return pd.DataFrame()

        # Create an uninterrupted sequence of timestamps from START_TS to END_TS in n-second intervals.
        # range(start, stop, step) generates the numbers.
        full_timeline = range(start_ts, end_ts + 1, step_seconds)
        # .reindex(...) forces the DataFrame to have EXACTLY the rows specified in 'full_timeline'.
        # If the target container died for 30 seconds, Prometheus returned no data for those 30 seconds.
        # reindex forces those missing 30 seconds into the DataFrame as empty (NaN) rows!
        df = df.reindex(full_timeline)
        df.index.name = "timestamp"

        # --- Handling Missing Values ---
        # Replace all NaN (empty / downtime gaps) with 0.0 across all numeric columns.
        df = df.fillna(0.0)
        df = self._compute_derived_features(df, step_seconds)

        # --- Resetting Index ---
        # Move 'timestamp' from being the row index back to being a normal, regular column.
        # 'inplace=True' applies the modification directly to 'df' without needing 'df = df.reset_index()'.
        df.reset_index(inplace=True)

        # Aligns all series automatically by timestamp index
        return df

    def _compute_derived_features(
        self, df: pd.DataFrame, step_seconds: int
    ) -> pd.DataFrame:
        """
        Vectorized computation of deltas, rolling windows, surge ratios, and z-scores.
        """
        # Dynamic periods based on step resolution
        p_30s = max(1, 30 // step_seconds)
        p_60s = max(1, 60 // step_seconds)

        # 1. Deltas (Rate of change)
        df[MetricKey.LATENCY_DELTA_30S] = (
            df[MetricKey.TARGET_LATENCY].diff(periods=p_30s).fillna(0.0)
        )
        df[MetricKey.LATENCY_DELTA_60S] = (
            df[MetricKey.TARGET_LATENCY].diff(periods=p_60s).fillna(0.0)
        )
        df[MetricKey.MEM_DELTA_60S] = (
            df[MetricKey.TARGET_MEM].diff(periods=p_60s).fillna(0.0)
        )
        df[MetricKey.CPU_DELTA_30S] = (
            df[MetricKey.TARGET_CPU].diff(periods=p_30s).fillna(0.0)
        )
        df[MetricKey.THROUGHPUT_DELTA_30S] = (
            df[MetricKey.TARGET_THROUGHPUT].diff(periods=p_30s).fillna(0.0)
        )

        # Latency Acceleration (change in delta)
        df[MetricKey.LATENCY_ACCEL_30S] = (
            df[MetricKey.LATENCY_DELTA_30S].diff(periods=p_30s).fillna(0.0)
        )

        # 2. Rolling Aggregations (min_periods=1 prevents leading NaNs)
        rolling_latency = df[MetricKey.TARGET_LATENCY].rolling(
            window=p_60s, min_periods=1
        )
        df[MetricKey.LATENCY_ROLLING_MEAN_1M] = rolling_latency.mean()
        df[MetricKey.LATENCY_STD_1M] = rolling_latency.std().fillna(0.0)

        df[MetricKey.THROUGHPUT_ROLLING_MEAN_1M] = (
            df[MetricKey.TARGET_THROUGHPUT].rolling(window=p_60s, min_periods=1).mean()
        )
        df[MetricKey.ACTIVE_REQ_ROLLING_MEAN_1M] = (
            df[MetricKey.TARGET_ACTIVE_REQUESTS]
            .rolling(window=p_60s, min_periods=1)
            .mean()
        )

        # 3. Ratios (Protected using np.where against zero-division)
        mean_baseline = df[MetricKey.LATENCY_ROLLING_MEAN_1M]
        df[MetricKey.LATENCY_SURGE_RATIO] = np.where(
            mean_baseline > 0.0,
            df[MetricKey.TARGET_LATENCY] / mean_baseline,
            1.0,  # 1.0 indicates normal/neutral ratio when idle
        )

        live_threads = df[MetricKey.TARGET_LIVE_THREADS]
        df[MetricKey.THREAD_PRESSURE_RATIO] = np.where(
            live_threads > 0.0,
            df[MetricKey.TARGET_ACTIVE_REQUESTS] / live_threads,
            0.0,
        )

        # 4. Numerically Stable Z-Score (Prevents micro-noise alert explosions)
        std_series = df[MetricKey.LATENCY_STD_1M]
        delta_from_mean = (
            df[MetricKey.TARGET_LATENCY] - df[MetricKey.LATENCY_ROLLING_MEAN_1M]
        )

        # If std < 0.001 ms, there is no meaningful variance -> Z-Score is 0.0
        df[MetricKey.LATENCY_ZSCORE] = np.where(
            std_series > 1e-3,
            delta_from_mean / std_series,
            0.0,
        )

        return df


class PredictionService:

    def __init__(self, predition_model_bundle: Any):
        self.bundle = predition_model_bundle
        self.model = self.bundle["model"]
        self.feature_cols = self.bundle["features"]
        logger.info(
            f"Model loaded successfully! Features count: {len(self.feature_cols)}"
        )

    def predict_health(self, payload: PredictionInput) -> PredictionOutput:
        if self.model is None:
            raise ApplicationException(
                status_code=500, message="Prediction model is not available."
            )

        try:
            # Convert incoming dictionary to a DataFrame
            df_input = pd.DataFrame([payload.features])

            # Ensure all required model features are present; default missing ones to 0.0
            for col in self.feature_cols:
                if col not in df_input.columns:
                    df_input[col] = 0.0

            # Align column order strictly to what the model was trained on
            X = df_input[self.feature_cols]

            # Run inference
            pred_class = int(self.model.predict(X)[0])
            probabilities = self.model.predict_proba(X)[0]
            confidence = float(max(probabilities))

            state_map = {
                0: PredictionOutputState.HEALTHY,
                1: PredictionOutputState.DEGRADED,
                2: PredictionOutputState.FAILED,
            }

            return PredictionOutput(
                service_name=payload.service_name,
                prediction=pred_class,
                state=state_map.get(pred_class, "Unknown"),
                confidence=round(confidence, 3),
                probabilities=PredictionStateProbabilities(
                    healthy=round(float(probabilities[0]), 3),
                    degraded=round(float(probabilities[1]), 3),
                    failed=round(float(probabilities[2]), 3),
                ),
            )

        except Exception as e:
            raise ApplicationException(
                status_code=500, message=f"Inference error: {e!s}"
            )
