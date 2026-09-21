import os
import requests
import pandas as pd
from datetime import datetime

# ==============================================================================
# 1. CONFIGURATION FOR EXPERIMENT 6
# ==============================================================================
PROMETHEUS_URL = "http://localhost:9090/api/v1/query_range"
TARGET_SERVICE = "payment_service" #   inventory_service or payment_service
STEP = "2s"
STEP_SECONDS = 2

# Update with your Experiment 6 timestamps
START_TIME_STR = "2026-09-20 12:22:15"  # <--- UPDATE THIS
END_TIME_STR = "2026-09-20 12:32:15"  # <--- UPDATE THIS

OUTPUT_FILE = "raw_data/exp10_container_kill_payment.csv"  # exp10_container_kill_inventory or exp10_container_kill_payment


# ==============================================================================
# 2. TIMESTAMP CONVERSION
# ==============================================================================
start_dt = datetime.strptime(START_TIME_STR, "%Y-%m-%d %H:%M:%S")
end_dt = datetime.strptime(END_TIME_STR, "%Y-%m-%d %H:%M:%S")

START_TS = int(start_dt.timestamp())
END_TS = int(end_dt.timestamp())
# ==============================================================================
# 3. QUERIES
# ==============================================================================
QUERIES = {
    "target_cpu": f'avg(otel_process_cpu_usage{{application="{TARGET_SERVICE}"}}) * 100',
    "target_mem": f'sum(otel_jvm_memory_used_bytes{{application="{TARGET_SERVICE}"}}) / sum(otel_jvm_memory_committed_bytes{{application="{TARGET_SERVICE}"}})',
    "target_throughput": f'sum(rate(otel_http_server_requests_milliseconds_count{{application="{TARGET_SERVICE}"}}[1m]))',
    "target_latency": f'sum(rate(otel_http_server_requests_milliseconds_sum{{application="{TARGET_SERVICE}"}}[1m])) / sum(rate(otel_http_server_requests_milliseconds_count{{application="{TARGET_SERVICE}"}}[1m]))',
    "target_error_rate": f'sum(rate(otel_http_server_requests_milliseconds_count{{application="{TARGET_SERVICE}", status=~"5.."}}[1m])) / sum(rate(otel_http_server_requests_milliseconds_count{{application="{TARGET_SERVICE}"}}[1m]))',
    "target_live_threads": f'max(otel_jvm_threads_live{{application="{TARGET_SERVICE}"}})',
    "target_active_requests": f'sum(otel_http_server_requests_active_milliseconds_count{{application="{TARGET_SERVICE}"}})'
}


# ==============================================================================
# 4. EXTRACTION ENGINE
# ==============================================================================
def fetch_series(query_name, query_str):
    params = {
        "query": query_str,
        "start": START_TS,
        "end": END_TS,
        "step": STEP
    }
    try:
        res = requests.get(PROMETHEUS_URL, params=params, timeout=15)
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
        print(f"  [ERROR] {query_name}: {e}")
        return pd.Series(dtype=float)


def assign_status(row):
    """
    Classifies system state:
    - Failed: Container dead (0 threads) OR Latency > 1000ms OR Error rate > 15%
    - Degraded: Early warning (Errors > 3%, Latency > 300ms, Memory > 80%, CPU > 70%)
    - Healthy: Normal operating range
    """
    if row["target_live_threads"] == 0 or row["target_error_rate"] > 0.15 or row["target_latency"] > 1000.0:
        return "Failed"
    elif (row["target_error_rate"] > 0.03 or
          row["target_latency"] > 300.0 or
          row["target_mem"] > 0.80 or
          row["target_cpu"] > 70.0):
        return "Degraded"
    else:
        return "Healthy"


def main():
    print(f"[*] Extracting Experiment 10: {START_TIME_STR} -> {END_TIME_STR}")
    df = pd.DataFrame({name: fetch_series(name, q) for name, q in QUERIES.items()})

    # Continuous 2-second timeline spanning the full window (handles container downtime gap)
    full_timeline = range(START_TS, END_TS + 1, STEP_SECONDS)
    df = df.reindex(full_timeline)
    df.index.name = "timestamp"

    # Fill downtime gaps with 0.0
    df = df.fillna(0.0)
    df.reset_index(inplace=True)

    df["Local Datetime"] = df["timestamp"].apply(
        lambda ts: datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    )

    df["status"] = df.apply(assign_status, axis=1)

    df.to_csv(OUTPUT_FILE, index=False)
    print(f"\n[✓] Successfully saved {len(df)} rows to '{OUTPUT_FILE}'")
    print("\n--- Status Distribution ---")
    print(df["status"].value_counts())


if __name__ == "__main__":
    main()