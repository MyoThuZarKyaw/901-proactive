import logging
import time
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import requests

logger = logging.getLogger(__name__)

# Telemetry resolution (step is 2 seconds)
STEP_30S = 15  # 15 rows * 2s = 30 seconds
STEP_60S = 30  # 30 rows * 2s = 60 seconds
LOOK_AHEAD_STEPS = 20  # 20 rows * 2s = 40 seconds proactive lead-time runway


class PrometheusQueryService:

    def __init__(self, base_url: str, timeout_seconds: int = 15):
        # To ensure clean URL without trailing slashes
        self.base_url = base_url.rstrip("/")
        self.query_range_url = f"{self.base_url}/api/v1/query_range"
        self.timeout = timeout_seconds
        # Connection pooling: keeps TCP sockets alive across multiple queries
        self.session = requests.Session()

    @staticmethod
    def get_prometheus_time_range(minutes: int = 5) -> tuple[int, int]:
        """Returns (start_ts, end_ts) for Prometheus as UNIX epoch milliseconds."""
        # Usage:
        # START_TS, END_TS = get_prometheus_time_range(minutes=10)
        end_ts = int(time.time() * 1000)
        start_ts = end_ts - (minutes * 60 * 1000)
        return start_ts, end_ts

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
        return self.collect_and_process(
            service_name=service_name,
            start_ms=start_ts,
            end_ms=end_ts,
            exp_id="advisory-service",
        )

    def get_queries(self, service_name: str):
        return {
            # Process CPU (0 to 100%)
            "target_cpu": f'avg(otel_process_cpu_usage{{application="{service_name}"}}) * 100',
            # Memory (Used / Max Heap Ratio: 0.0 to 1.0)
            "target_mem": f'sum(otel_jvm_memory_used_bytes{{area="heap", application="{service_name}"}}) / sum(otel_jvm_memory_max_bytes{{area="heap", application="{service_name}"}} > 0)',
            # Throughput (RPS) - 10s window captures immediate shifts without phase lag
            "target_throughput": f'sum(rate(otel_http_server_requests_milliseconds_count{{application="{service_name}"}}[10s])) or vector(0)',
            # Average Latency (ms)
            "target_latency": f'(sum(rate(otel_http_server_requests_milliseconds_sum{{application="{service_name}"}}[10s])) / sum(rate(otel_http_server_requests_milliseconds_count{{application="{service_name}"}}[10s]))) or vector(0)',
            # Error Rate (5xx Ratio: 0.0 to 1.0, safe against empty series)
            "target_error_rate": f'(sum(rate(otel_http_server_requests_milliseconds_count{{application="{service_name}", status=~"5.."}}[10s])) or vector(0)) / (sum(rate(otel_http_server_requests_milliseconds_count{{application="{service_name}"}}[10s])) > 0) or vector(0)',
            # Live threads & Active in-flight requests
            "target_live_threads": f'sum(otel_jvm_threads_live{{application="{service_name}"}})',
            "target_active_requests": f'sum(otel_http_server_requests_active_milliseconds_count{{application="{service_name}"}}) or vector(0)',
        }

    def fetch_df_series(
        self,
        query_name: str,
        query_str: str,
        start_ms: int,
        end_ms: int,
        step: str = "2s",
    ) -> pd.Series:
        params = {
            "query": query_str,
            "start": start_ms / 1000.0,
            "end": end_ms / 1000.0,
            "step": step,
        }
        try:
            res = requests.get(self.query_range_url, params=params, timeout=15)
            res.raise_for_status()
            data = res.json().get("data", {}).get("result", [])

            if not data:
                return pd.Series(dtype=float)

            values = data[0]["values"]
            df_temp = pd.DataFrame(values, columns=["timestamp", query_name])
            df_temp["timestamp"] = df_temp["timestamp"].astype(int)
            df_temp[query_name] = pd.to_numeric(df_temp[query_name], errors="coerce")

            return df_temp.set_index("timestamp")[query_name]

        except Exception as e:
            print(f"  [ERROR] fetching {query_name}: {e}")
            return pd.Series(dtype=float)

    def compute_raw_state(self, df: pd.DataFrame) -> np.ndarray:
        """
        Defines service health at the exact instant t:
        - 2 (Failed): Severe breach of SLO / CB trip territory
        - 1 (Degraded): Incipient stress / high latency / memory pressure
        - 0 (Healthy): Normal bounds
        """
        # conditions = [
        #     # State 2: Failed
        #     (df["target_latency"] >= 1000.0) |
        #     (df["target_error_rate"] >= 0.30) |
        #     (df["target_live_threads"] == 0),

        #     # State 1: Degraded
        #     (df["target_latency"] >= 350.0) |
        #     (df["target_error_rate"] >= 0.03) |
        #     ((df["target_mem"] > 0.85) & (df["mem_delta_60s"] > 0.02)) |
        #     (df["target_cpu"] > 70.0)
        # ]

        conditions = [
            # State 2: Failed (Unchanged: CB trip territory)
            (df["target_latency"] >= 1000.0)
            | (df["target_error_rate"] >= 0.30)
            | (df["target_live_threads"] == 0)  # <-- Catches dead container
            | (
                (df["target_throughput"] == 0.0) & (df["target_active_requests"] == 0)
            ),  # <-- Total silence / outage
            # State 1: Degraded (Lowered to 200ms to catch 50% assault levels)
            (df["target_latency"] >= 200.0)
            | (df["target_error_rate"] >= 0.03)
            | ((df["target_mem"] > 0.85) & (df["mem_delta_60s"] > 0.02))
            | (df["target_cpu"] > 70.0),
        ]
        return np.select(conditions, [2, 1], default=0)

    def engineer_features_and_target(
        self, df: pd.DataFrame, service_name: str, exp_id: str
    ) -> pd.DataFrame:
        # Metadata
        df["service_name"] = service_name
        df["experiment_id"] = exp_id

        # A. Velocity & Slopes (Rate of change)
        df["latency_delta_30s"] = df["target_latency"] - df["target_latency"].shift(
            STEP_30S
        )
        df["latency_delta_60s"] = df["target_latency"] - df["target_latency"].shift(
            STEP_60S
        )
        df["mem_delta_60s"] = df["target_mem"] - df["target_mem"].shift(STEP_60S)
        df["cpu_delta_30s"] = df["target_cpu"] - df["target_cpu"].shift(STEP_30S)
        df["throughput_delta_30s"] = df["target_throughput"] - df[
            "target_throughput"
        ].shift(STEP_30S)
        df["latency_accel_30s"] = df["latency_delta_30s"] - df[
            "latency_delta_30s"
        ].shift(STEP_30S)

        # B. Rolling Statistics
        df["latency_rolling_mean_1m"] = (
            df["target_latency"].rolling(window=STEP_60S).mean()
        )
        df["latency_std_1m"] = (
            df["target_latency"].rolling(window=STEP_60S).std().fillna(0)
        )
        df["throughput_rolling_mean_1m"] = (
            df["target_throughput"].rolling(window=STEP_60S).mean()
        )
        df["active_req_rolling_mean_1m"] = (
            df["target_active_requests"].rolling(window=STEP_60S).mean()
        )

        # C. Relative Ratios (Feature boosts for Random Forest tree splits)
        df["latency_surge_ratio"] = df["target_latency"] / (
            df["latency_rolling_mean_1m"] + 1e-5
        )
        df["thread_pressure_ratio"] = df["target_active_requests"] / (
            df["target_live_threads"] + 1e-5
        )
        df["latency_zscore"] = (
            df["target_latency"] - df["latency_rolling_mean_1m"]
        ) / (df["latency_std_1m"] + 1e-5)

        # D. Instantaneous Raw State
        df["raw_state"] = self.compute_raw_state(df)

        # E. Sustained State (Eliminates single 2-second blips)
        sustained_state = (
            df["raw_state"].rolling(window=2, min_periods=1).max().astype(int)
        )

        # F. PROACTIVE LOOKAHEAD TARGET (Predicts ahead 40 seconds)
        # Target y = the worst state the system will enter over the next LOOK_AHEAD_STEPS
        df["proactive_state"] = (
            sustained_state.iloc[::-1]
            .rolling(window=LOOK_AHEAD_STEPS, min_periods=1)
            .max()
            .iloc[::-1]
            .astype(int)
        )

        # Friendly human-readable label
        df["proactive_label"] = df["proactive_state"].map(
            {0: "Healthy", 1: "Degraded", 2: "Failed"}
        )

        # Drop the first 60 seconds (STEP_60S) of warm-up rows which have NaN deltas
        df = df.dropna().reset_index(drop=True)
        return df

    def collect_and_process(
        self, service_name: str, start_ms: int, end_ms: int, exp_id: str
    ):
        logger.info(f"[*] Processing {exp_id} for {service_name}...")
        logger.info(
            f"[*] Time: {start_ms}={datetime.fromtimestamp(start_ms/1000.0, tz=UTC)} to {end_ms}={datetime.fromtimestamp(end_ms/1000.0, tz=UTC)}"
        )

        # 1. Fetch raw time-series
        queries = self.get_queries(service_name)
        df = pd.DataFrame(
            {
                name: self.fetch_df_series(name, q, start_ms, end_ms)
                for name, q in queries.items()
            }
        )

        if df.empty or len(df) < STEP_60S:
            logger.warning(
                f"[!] Insufficient data points fetched for {service_name}. Aborting."
            )
            return

        # If the container was dead, live threads and CPU are 0 (not forward-filled!)
        df["target_live_threads"] = df["target_live_threads"].fillna(0.0)
        df["target_throughput"] = df["target_throughput"].fillna(0.0)
        df["target_cpu"] = df["target_cpu"].fillna(0.0)
        df["target_active_requests"] = df["target_active_requests"].fillna(0.0)

        # If threads are 0 (dead container), error rate is 100% and latency is 0
        dead_mask = df["target_live_threads"] == 0.0
        df.loc[dead_mask, "target_error_rate"] = 1.0
        df.loc[dead_mask, "target_latency"] = 0.0

        # Clean missing points & restore timestamp column
        df = df.ffill().bfill().fillna(0.0)
        df = df.reset_index()
        if "index" in df.columns:
            df = df.rename(columns={"index": "timestamp"})

        df["local_datetime"] = df["timestamp"].apply(
            lambda ts: datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        )

        # 2. Compute Features & Proactive Labels
        df_engineered = self.engineer_features_and_target(df, service_name, exp_id)

        return df_engineered
