from datetime import datetime, timezone
from typing import Dict, List, Optional
import numpy as np
import pandas as pd
import requests
from six import ensure_text

from experiment import Experiment

class TargetServiceConfig:
    """Holds configuration for a downstream target service and its circuit breaker."""

    def __init__(self, cb_name: str, target_service_name: str):
        self.cb_name = cb_name
        self.target_service_name = target_service_name

class PrometheusCollector:
    """Encapsulates Prometheus metrics collection for caller & target microservices."""

    DEFAULT_TARGETS = [
        TargetServiceConfig(
            cb_name="inventoryService", target_service_name="inventory_service"
        ),
        TargetServiceConfig(
            cb_name="paymentService", target_service_name="payment_service"
        )
    ]

    # Explicit order of all 21 raw columns
    OUTPUT_COLUMNS = [
        "timestamp",
        "caller_cpu",
        "caller_mem",
        "target_cpu",
        "target_mem",
        "target_latency",
        "target_error_rate",
        "cb_slow_call_rate",
        "cb_failure_rate",
        "cb_state",
        "cb_name",
        "target_service",
        "cluster_cpu",
        "cluster_mem",
        "cluster_throughput",
        "cluster_error_rate",
        "UTC Datetime",
        "Local Datetime",
        "feat_threshold",
        "latency_ratio",
        "status",
        "experiment_id",
    ]

    def __init__(
        self,
        base_url: str="http://localhost:9090/api/v1/query_range",
        step: str = "1s",
        caller_service: str = "order_service",
        targets: Optional[List[TargetServiceConfig]] = None,
    ):
        self.base_url = base_url
        self.step = step
        self.caller_service = caller_service
        self.targets = targets or self.DEFAULT_TARGETS

    def _fetch_series(self, query: str, start_ts: int, end_ts: int) -> pd.Series:
        """Execute query against Prometheus and return a numeric Series indexed by timestamp."""
        params = {
            "query": query,
            "start": start_ts,
            "end": end_ts,
            "step": self.step,
        }

        try:
            res = requests.get(self.base_url, params=params, timeout=30)
            res.raise_for_status()
            results = res.json().get("data", {}).get("result", [])
            if not results:
                return pd.Series(dtype=float)

            values = results[0]["values"]
            df_t = pd.DataFrame(values, columns=["timestamp", "val"])

            # Safely handle '+Inf', '-Inf', and 'NaN'
            df_t["val"] = pd.to_numeric(df_t["val"], errors="coerce")
            df_t["val"] = df_t["val"].replace([np.inf, -np.inf], np.nan)
            df_t["timestamp"] = df_t["timestamp"].astype(int)

            return df_t.set_index("timestamp")["val"]
        except requests.RequestException as exc:
            print(f"    [!] HTTP Error running query '{query}': {exc}")
            return pd.Series(dtype=float)

    def _fetch_common_metrics(self, start_ts: int, end_ts: int) -> pd.DataFrame:
        """Fetches Global cluster metrics and Caller (order_service) metrics once per experiment."""
        caller = self.caller_service
        df_common = pd.DataFrame()

        # 1. Global / Cluster Metrics (across backend services)
        df_common["cluster_cpu"] = self._fetch_series(
            "avg(otel_process_cpu_usage) * 100", start_ts, end_ts
        )

        df_common["cluster_mem"] = self._fetch_series(
            "sum(otel_jvm_memory_used_bytes) / sum(otel_jvm_memory_committed_bytes)",
            start_ts,
            end_ts,
        )
        df_common["cluster_throughput"] = self._fetch_series(
            "sum(rate(otel_http_server_requests_milliseconds_count[1m]))",
            start_ts,
            end_ts,
        )
        df_common["cluster_error_rate"] = self._fetch_series(
            "sum(rate(otel_http_server_requests_milliseconds_count{status=~'5..'}[1m])) / "
            "sum(rate(otel_http_server_requests_milliseconds_count[1m]))",
            start_ts,
            end_ts,
        )

        # 2. Caller Metrics (order_service)
        df_common["caller_cpu"] = self._fetch_series(
            f'otel_process_cpu_usage{{application="{caller}"}} * 100',
            start_ts,
            end_ts,
        )
        df_common["caller_mem"] = self._fetch_series(
            f'otel_jvm_memory_used_bytes{{application="{caller}"}} / '
            f'otel_jvm_memory_committed_bytes{{application="{caller}"}}',
            start_ts,
            end_ts,
        )

        return df_common

    def _extract_breaker_data(
        self,
        target: TargetServiceConfig,
        start_ts: int,
        end_ts: int,
        common_df: pd.DataFrame
    ) -> pd.DataFrame:
        """Collects target-specific and Resilience4j metrics, merging them onto the common metrics."""
        cb_name = target.cb_name
        target_name = target.target_service_name
        caller = self.caller_service

        # Start with a copy of the pre-fetched global/caller metrics
        df = common_df.copy()

        # Target Service Metrics(inventory or payment)
        df["target_cpu"] = self._fetch_series(
            f'otel_process_cpu_usage{{application="{target_name}"}} * 100',
            start_ts,
            end_ts,
        )
        df["target_mem"] = self._fetch_series(
            f'otel_jvm_memory_used_bytes{{application="{target_name}"}} / '
            f'otel_jvm_memory_committed_bytes{{application="{target_name}"}}',
            start_ts,
            end_ts,
        )
        df["target_latency"] = self._fetch_series(
            f'sum(rate(otel_http_server_requests_milliseconds_sum{{application="{target_name}"}}[1m])) / '
            f'sum(rate(otel_http_server_requests_milliseconds_count{{application="{target_name}"}}[1m]))',
            start_ts,
            end_ts,
        )
        df["target_error_rate"] = self._fetch_series(
            f'sum(rate(otel_http_server_requests_milliseconds_count{{application="{target_name}", status=~"5.."}}[1m])) / '
            f'sum(rate(otel_http_server_requests_milliseconds_count{{application="{target_name}"}}[1m]))',
            start_ts,
            end_ts,
        )

        # Resilience4j Metrics in order_service
        df["cb_slow_call_rate"] = self._fetch_series(
            f'otel_resilience4j_circuitbreaker_slow_call_rate{{application="{caller}", name="{cb_name}"}}',
            start_ts,
            end_ts,
        )

        df["cb_failure_rate"] = self._fetch_series(
            f'otel_resilience4j_circuitbreaker_failure_rate{{application="{caller}", name="{cb_name}"}}',
            start_ts,
            end_ts,
        )
        df["cb_state"] = self._fetch_series(
            f'otel_resilience4j_circuitbreaker_state{{application="{caller}", name="{cb_name}", state="open"}}',
            start_ts,
            end_ts,
        )

        # Fill gaps and reset index
        df = df.ffill().bfill().fillna(0.0)
        df.reset_index(inplace=True)
        df.rename(columns={"index": "timestamp"}, inplace=True)

        # Indentifiers
        df["cb_name"] = cb_name
        df["target_service"] = target_name

        # Replace Resilience4j warmup value (-1.0) with 0.0
        df["cb_slow_call_rate"] = df["cb_slow_call_rate"].clip(lower=0.0)
        df["cb_failure_rate"] = df["cb_failure_rate"].clip(lower=0.0)

        return df

    @staticmethod
    def _assign_status(row: pd.Series) -> str:
        """Assigns classification based on error rate, latency ratio, and circuit breaker state"""
        if row["cb_state"] > 0 or row["target_error_rate"] > 0.5:
            return "Failed"
        elif row["target_error_rate"] > 0.1 or row["latency_ratio"] > 0.6:
            return "Degraded"
        return "Healthy"

    def _enrich_dataset(
        self,
        df: pd.DataFrame, experiment: Experiment
    ) -> pd.DataFrame:
        """Adds human-readable datetimes, thresholds, latency_ratio, experiment_id, and status."""
        df["UTC Datetime"] = df["timestamp"].apply(
            lambda ts: datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        )

        df["Local Datetime"] = df["timestamp"].apply(
            lambda ts: datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        )

        # Thresholds and status labeling
        df["feat_threshold"] = experiment.threshold
        df["latency_ratio"] = df["target_latency"] / df["feat_threshold"]
        df["status"] = df.apply(self._assign_status, axis=1)
        df["experiment_id"] = experiment.id

        return df

    def collect_and_save(self, experiment: Experiment) -> None:
        """Collects metrics for all targets, merges them, and saves the CSV."""
        print(f"\n--- Running Exp #{experiment.id}: '{experiment.name}' ---")
        print(
            f"  Time window: {experiment.start_time_str} -> {experiment.end_time_str}"
        )

        # 1. Fetch common (global cluster + order_service) metrics once
        print("  Fetching common cluster and caller metrics...")
        common_df = self._fetch_common_metrics(
            start_ts=experiment.start_timestamp, end_ts=experiment.end_timestamp
        )

        # 2. Extract metrics for each target breaker
        frames = []
        for target in self.targets:
            print(
                f" Fetching metrics for: {target.cb_name} ({target.target_service_name})"
            )
            df_target = self._extract_breaker_data(
                target=target,
                start_ts=experiment.start_timestamp,
                end_ts=experiment.end_timestamp,
                common_df=common_df
            )
            if not df_target.empty:
                frames.append(df_target)

        if not frames:
            print(f"    [!] No data collected for experiment #{experiment.id}.")
            return

        # 3. Combine datasets
        combined_df = pd.concat(frames, ignore_index=True)

        # 4. Sort by timestamp so inventory and payment stay aligned per second
        combined_df.sort_values(by=["timestamp", "cb_name"], inplace=True)

        # 5. Enrich with datetimes, threshold, latency_ratio, and status
        final_df = self._enrich_dataset(combined_df, experiment)

        #print(final_df)
        # 6. Reorder strictly to the 21 columns
        final_df = final_df[self.OUTPUT_COLUMNS]
        final_df.reset_index(drop=True, inplace=True)

        # 7. Save to CSV
        output_file = experiment.output_filename
        final_df.to_csv(output_file, index=False)
        print(
            f"  [✓] Successfully saved {len(final_df)} rows with {len(final_df.columns)} columns to '{output_file}'"
        )


